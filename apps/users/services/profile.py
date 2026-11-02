from django.db import transaction
from apps.users.models import User, UserProfile


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

    profile_allowed = [
        "address",
        "city",
        "country",
        "date_of_birth",
        "sex",
        "nationality",
        "is_private",
    ]
    for field in profile_allowed:
        if field in profile_data and profile_data[field] is not None:
            setattr(profile, field, profile_data[field])
    profile.save()

    user.profile = profile
    return user
