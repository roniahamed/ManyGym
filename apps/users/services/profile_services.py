from django.db import transaction
from apps.users.models import User, UserProfile


from typing import Optional, List, Dict, Any, Union
import uuid
from django.db import transaction
from apps.users.models import User, UserProfile, UserEducation, UserSocialLink
from common.enums import GenderEnum, SocialPlatformEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError


@transaction.atomic
def update_user_profile(user: User, **profile_data) -> User:
    """
    Updates user personal info and UserProfile attributes.
    """
    user_fields = ["first_name", "last_name", "phone"]
    for field in user_fields:
        if field in profile_data and profile_data[field] is not None:
            setattr(user, field, profile_data[field])
    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)

    if "avatar" in profile_data or "avatar_url" in profile_data:
        from common.media import MediaOptimizerService
        avatar_file = profile_data.pop("avatar", None)
        avatar_url = profile_data.pop("avatar_url", None)
        resolved_avatar = MediaOptimizerService.process_image_upload(
            file=avatar_file,
            url=avatar_url,
            subfolder="avatars",
            max_dims=(400, 400),
            thumb_dims=(150, 150),
        )
        if resolved_avatar is not None or avatar_file is not None or avatar_url is not None:
            profile.avatar_url = resolved_avatar

    # Address / Current Address mapping
    if "current_address" in profile_data and profile_data["current_address"] is not None:
        profile.address = profile_data["current_address"]
    elif "address" in profile_data and profile_data["address"] is not None:
        profile.address = profile_data["address"]

    # Gender / Sex synchronization
    if "gender" in profile_data and profile_data["gender"] is not None:
        profile.gender = profile_data["gender"]
        profile.sex = profile_data["gender"]
    elif "sex" in profile_data and profile_data["sex"] is not None:
        profile.sex = profile_data["sex"]
        if profile_data["sex"] in GenderEnum.values:
            profile.gender = profile_data["sex"]

    profile_allowed = [
        "home_town",
        "city",
        "country",
        "date_of_birth",
        "nationality",
        "hobbies",
        "about_you",
        "favourite_quote",
        "is_private",
    ]
    for field in profile_allowed:
        if field in profile_data and profile_data[field] is not None:
            setattr(profile, field, profile_data[field])
    profile.save()

    user.profile = profile
    return user


@transaction.atomic
def update_user_about(user: User, **about_data) -> User:
    """
    Updates the Public Profile -> About sections for the given user:
    1. Personal Details (current_address, home_town, date_of_birth, gender)
    2. Education list (university_name, from_year, till_year, subject, graduated)
    3. Hobbies (list of free text strings)
    4. Contact info (phone_number, social_links; registered email cannot be changed)
    5. Details about you (about_you <= 320 chars, favourite_quote <= 160 chars)
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)

    # Flatten nested structures if passed under section dictionaries
    personal_details = about_data.pop("personal_details", {}) or {}
    contact_info = about_data.pop("contact_info", {}) or {}
    details_about_you = about_data.pop("details_about_you", {}) or {}

    # Merge personal details
    current_address = personal_details.get("current_address") or about_data.get("current_address")
    if current_address is not None:
        profile.address = current_address
    elif "address" in personal_details:
        profile.address = personal_details["address"]
    elif "address" in about_data:
        profile.address = about_data["address"]

    home_town = personal_details.get("home_town") or about_data.get("home_town")
    if home_town is not None:
        profile.home_town = home_town

    date_of_birth = personal_details.get("date_of_birth") or about_data.get("date_of_birth")
    if date_of_birth is not None:
        profile.date_of_birth = date_of_birth

    gender = personal_details.get("gender") or about_data.get("gender")
    if gender is not None:
        if gender and gender not in GenderEnum.values:
            raise DomainValidationError(f"Invalid gender choice: '{gender}'. Must be one of {GenderEnum.values}.")
        profile.gender = gender
        profile.sex = gender

    # Merge contact info
    phone_number = contact_info.get("phone_number") or about_data.get("phone_number") or about_data.get("phone")
    if phone_number is not None:
        user.phone = phone_number
        user.save(update_fields=["phone", "updated_at"])

    # Email cannot be changed - discard if present
    about_data.pop("email", None)
    contact_info.pop("email", None)

    # Merge details about you
    about_you = details_about_you.get("about_you") or about_data.get("about_you")
    if about_you is not None:
        if len(about_you) > 320:
            raise DomainValidationError("About you exceeds maximum allowed length of 320 characters.")
        profile.about_you = about_you

    favourite_quote = details_about_you.get("favourite_quote") or about_data.get("favourite_quote")
    if favourite_quote is not None:
        if len(favourite_quote) > 160:
            raise DomainValidationError("Favourite quote exceeds maximum allowed length of 160 characters.")
        profile.favourite_quote = favourite_quote

    # Merge hobbies
    hobbies = about_data.get("hobbies")
    if hobbies is not None:
        if not isinstance(hobbies, list):
            raise DomainValidationError("Hobbies must be a list of strings.")
        profile.hobbies = [str(h).strip() for h in hobbies if str(h).strip()]

    profile.save()

    # Merge Education List (Atomic Replacement / Sync)
    education_list = about_data.get("education_list")
    if education_list is not None:
        if not isinstance(education_list, list):
            raise DomainValidationError("Education list must be a list of education objects.")
        _sync_user_educations(user, education_list)

    # Merge Social Links (Atomic Replacement / Sync)
    social_links = contact_info.get("social_links") or about_data.get("social_links")
    if social_links is not None:
        if not isinstance(social_links, list):
            raise DomainValidationError("Social links must be a list of social link objects.")
        _sync_user_social_links(user, social_links)

    user.profile = profile
    return user


def _sync_user_educations(user: User, education_list: List[Dict[str, Any]]) -> None:
    """Synchronizes full education items for a user."""
    # Delete existing and recreate or update
    UserEducation.objects.filter(user=user).delete()
    for item in education_list:
        from_year = item.get("from_year")
        till_year = item.get("till_year")
        university_name = (item.get("university_name") or "").strip()
        subject = (item.get("subject") or "").strip()
        graduated = bool(item.get("graduated", False))

        if not university_name:
            raise DomainValidationError("University name is required for each education entry.")
        if not from_year:
            raise DomainValidationError("From year is required for each education entry.")
        if not subject:
            raise DomainValidationError("Subject is required for each education entry.")

        if till_year and from_year and till_year < from_year:
            raise DomainValidationError("Till year cannot be earlier than from year.")

        UserEducation.objects.create(
            user=user,
            university_name=university_name,
            from_year=from_year,
            till_year=till_year,
            subject=subject,
            graduated=graduated,
        )


def _sync_user_social_links(user: User, social_links: List[Dict[str, Any]]) -> None:
    """Synchronizes full social links for a user."""
    UserSocialLink.objects.filter(user=user).delete()
    for item in social_links:
        platform = (item.get("platform") or "").strip()
        link = (item.get("link") or "").strip()

        if not platform:
            raise DomainValidationError("Platform selection is required for each social link.")
        if platform not in SocialPlatformEnum.values:
            raise DomainValidationError(
                f"Invalid platform '{platform}'. Must be one of {SocialPlatformEnum.values}."
            )
        if not link:
            raise DomainValidationError("Link URL is required for each social link.")

        UserSocialLink.objects.create(
            user=user,
            platform=platform,
            link=link,
        )


@transaction.atomic
def create_user_education(
    user: User,
    university_name: str,
    from_year,
    subject: str,
    till_year=None,
    graduated: bool = False,
) -> UserEducation:
    """Creates a single UserEducation record."""
    if not university_name or not str(university_name).strip():
        raise DomainValidationError("University name is required.")
    if not from_year:
        raise DomainValidationError("From year is required.")
    if not subject or not str(subject).strip():
        raise DomainValidationError("Subject is required.")
    if till_year and from_year and till_year < from_year:
        raise DomainValidationError("Till year cannot be earlier than from year.")

    return UserEducation.objects.create(
        user=user,
        university_name=university_name.strip(),
        from_year=from_year,
        till_year=till_year,
        subject=subject.strip(),
        graduated=graduated,
    )


@transaction.atomic
def update_user_education(user: User, education_id: Union[str, uuid.UUID], **data) -> UserEducation:
    """Updates an existing UserEducation record owned by the user."""
    try:
        edu_uuid = uuid.UUID(str(education_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid education ID.")

    edu = UserEducation.objects.filter(id=edu_uuid, user=user).first()
    if not edu:
        raise ResourceNotFoundError("Education record not found.")

    if "university_name" in data and data["university_name"] is not None:
        edu.university_name = str(data["university_name"]).strip()
    if "from_year" in data and data["from_year"] is not None:
        edu.from_year = data["from_year"]
    if "till_year" in data:
        edu.till_year = data["till_year"]
    if "subject" in data and data["subject"] is not None:
        edu.subject = str(data["subject"]).strip()
    if "graduated" in data and data["graduated"] is not None:
        edu.graduated = bool(data["graduated"])

    if edu.till_year and edu.from_year and edu.till_year < edu.from_year:
        raise DomainValidationError("Till year cannot be earlier than from year.")

    edu.save()
    return edu


@transaction.atomic
def delete_user_education(user: User, education_id: Union[str, uuid.UUID]) -> None:
    """Deletes an existing UserEducation record owned by the user."""
    try:
        edu_uuid = uuid.UUID(str(education_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid education ID.")

    deleted_count, _ = UserEducation.objects.filter(id=edu_uuid, user=user).delete()
    if not deleted_count:
        raise ResourceNotFoundError("Education record not found.")


@transaction.atomic
def create_user_social_link(user: User, platform: str, link: str) -> UserSocialLink:
    """Creates a single UserSocialLink record."""
    if not platform or platform.strip() not in SocialPlatformEnum.values:
        raise DomainValidationError(f"Invalid platform '{platform}'. Must be one of {SocialPlatformEnum.values}.")
    if not link or not str(link).strip():
        raise DomainValidationError("Link URL is required.")

    return UserSocialLink.objects.create(
        user=user,
        platform=platform.strip(),
        link=link.strip(),
    )


@transaction.atomic
def update_user_social_link(user: User, link_id: Union[str, uuid.UUID], **data) -> UserSocialLink:
    """Updates an existing UserSocialLink record owned by the user."""
    try:
        link_uuid = uuid.UUID(str(link_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid social link ID.")

    social_link = UserSocialLink.objects.filter(id=link_uuid, user=user).first()
    if not social_link:
        raise ResourceNotFoundError("Social link record not found.")

    if "platform" in data and data["platform"] is not None:
        p = str(data["platform"]).strip()
        if p not in SocialPlatformEnum.values:
            raise DomainValidationError(f"Invalid platform '{p}'. Must be one of {SocialPlatformEnum.values}.")
        social_link.platform = p
    if "link" in data and data["link"] is not None:
        social_link.link = str(data["link"]).strip()

    social_link.save()
    return social_link


@transaction.atomic
def delete_user_social_link(user: User, link_id: Union[str, uuid.UUID]) -> None:
    """Deletes an existing UserSocialLink record owned by the user."""
    try:
        link_uuid = uuid.UUID(str(link_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid social link ID.")

    deleted_count, _ = UserSocialLink.objects.filter(id=link_uuid, user=user).delete()
    if not deleted_count:
        raise ResourceNotFoundError("Social link record not found.")
