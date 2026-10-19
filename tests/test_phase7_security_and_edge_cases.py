import io
import uuid
import pytest
from PIL import Image
from unittest.mock import patch, MagicMock

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.members.models import Member
from apps.members.services import create_member
from apps.authentication.services import issue_context_token
from apps.posts.models import GymPost, GymPostMedia
from apps.posts.services import (
    create_post,
    update_post,
    delete_post,
    update_video_thumbnail,
    validate_media_file,
)
from apps.posts.selectors import (
    list_gym_feed,
    get_post_detail,
    get_post_media_by_id,
    stream_gym_feed,
)
from apps.posts.tasks import optimize_post_media_task
from common.enums import (
    TokenContextType,
    UserStatus,
    StaffStatus,
    PostPrivacyEnum,
    MediaTypeEnum,
    ProcessingStatus,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def create_user_with_tokens(email="test.phase7@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Phase7",
        last_name="Tester",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


def create_mock_image(filename="test.png", format="PNG", size=(50, 50), color="blue"):
    bio = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(bio, format=format)
    bio.seek(0)
    return SimpleUploadedFile(filename, bio.read(), content_type=f"image/{format.lower()}")


def create_mock_video(filename="test.mp4", size_bytes=1024):
    content = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (max(0, size_bytes - 8))
    return SimpleUploadedFile(filename, content, content_type="video/mp4")


@pytest.fixture
def post_gym_setup(db):
    # 1. Gym Owner
    owner, owner_client, _ = create_user_with_tokens(email="post.owner@manygym.com")
    gym = create_gym(
        owner_user=owner,
        name="Phase 7 Community Gym",
        timezone="America/New_York",
    )

    # 2. Staff with posts:manage
    staff_user, staff_client, _ = create_user_with_tokens(email="post.staff@manygym.com")
    staff_role = Role.objects.get(slug="staff")
    GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=staff_role,
        status=StaffStatus.ACTIVE,
    )

    # 3. Staff without posts:manage (trainer with removed perms)
    limited_staff, limited_client, _ = create_user_with_tokens(email="post.limited@manygym.com")
    custom_role = Role.objects.create(
        gym=gym,
        slug="limited_role",
        name="Limited Staff",
        is_custom=True,
    )
    GymStaffAssignment.objects.create(
        gym=gym,
        user=limited_staff,
        role=custom_role,
        status=StaffStatus.ACTIVE,
    )

    # 4. Inactive Staff
    inactive_staff, inactive_client, _ = create_user_with_tokens(email="post.inactive@manygym.com")
    GymStaffAssignment.objects.create(
        gym=gym,
        user=inactive_staff,
        role=staff_role,
        status=StaffStatus.INACTIVE,
    )

    # 5. Verified Active Member
    member_user, member_client, _ = create_user_with_tokens(email="post.member@manygym.com")
    member = create_member(
        gym=gym,
        first_name="Active",
        last_name="Member",
        email=member_user.email,
        phone="+12025550188",
    )

    # 6. Unauthenticated Client
    anon_client = APIClient()

    # 7. Unrelated Non-member Client
    other_user, other_client, _ = create_user_with_tokens(email="post.stranger@manygym.com")

    # 8. Another Gym (for cross-tenant IDOR checks)
    other_owner, other_gym_client, _ = create_user_with_tokens(email="post.otherowner@manygym.com")
    gym_b = create_gym(
        owner_user=other_owner,
        name="Gym B Cross Tenant",
        timezone="America/Chicago",
    )

    return {
        "gym": gym,
        "gym_b": gym_b,
        "owner": owner,
        "owner_client": owner_client,
        "staff_user": staff_user,
        "staff_client": staff_client,
        "limited_staff": limited_staff,
        "limited_client": limited_client,
        "inactive_client": inactive_client,
        "member_user": member_user,
        "member": member,
        "member_client": member_client,
        "anon_client": anon_client,
        "other_client": other_client,
        "other_gym_client": other_gym_client,
    }


# ==============================================================================
# 1. CORE INVARIANT & SERVICE VALIDATION TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPostInvariantsAndServices:
    def test_post_creation_requires_text_or_media(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]

        # Completely empty -> Fails
        with pytest.raises(DomainValidationError, match="either text or at least one media attachment"):
            create_post(gym=gym, author_user=owner, content_text="", media_files=[])

        # Whitespace text only -> Fails
        with pytest.raises(DomainValidationError, match="either text or at least one media attachment"):
            create_post(gym=gym, author_user=owner, content_text="   \n\t  ")

        # Text only -> Succeeds
        post1 = create_post(gym=gym, author_user=owner, content_text="Welcome to our gym community!")
        assert post1.id is not None
        assert post1.content_text == "Welcome to our gym community!"
        assert post1.media_attachments.count() == 0

        # Media only without text -> Succeeds
        img_file = create_mock_image("only_photo.png")
        post2 = create_post(gym=gym, author_user=owner, content_text="", media_files=[img_file])
        assert post2.id is not None
        assert post2.content_text is None
        assert post2.media_attachments.count() == 1
        assert post2.media_attachments.first().media_type == MediaTypeEnum.PICTURE

        # Both text and media -> Succeeds
        vid_file = create_mock_video("promo.mp4")
        post3 = create_post(
            gym=gym,
            author_user=owner,
            content_text="Check out our new equipment video!",
            media_files=[vid_file],
        )
        assert post3.id is not None
        assert post3.content_text == "Check out our new equipment video!"
        assert post3.media_attachments.count() == 1
        assert post3.media_attachments.first().media_type == MediaTypeEnum.VIDEO

    def test_media_file_validation_constraints(self):
        # 1. Allowed image formats: JPG, JPEG, PNG, WEBP
        for fmt, ext in [("PNG", "photo.png"), ("JPEG", "photo.jpg"), ("JPEG", "photo.jpeg")]:
            f = create_mock_image(filename=ext, format=fmt)
            assert validate_media_file(f) == MediaTypeEnum.PICTURE

        # 2. Allowed video formats: MP4, MOV
        mp4_f = create_mock_video("workout.mp4")
        assert validate_media_file(mp4_f) == MediaTypeEnum.VIDEO
        mov_f = SimpleUploadedFile("workout.mov", b"fake mov stream", content_type="video/quicktime")
        assert validate_media_file(mov_f) == MediaTypeEnum.VIDEO

        # 3. Disallowed image formats: GIF, SVG, BMP, EXE
        with pytest.raises(DomainValidationError, match="Unsupported image format"):
            gif_f = SimpleUploadedFile("anim.gif", b"GIF89a", content_type="image/gif")
            validate_media_file(gif_f)

        with pytest.raises(DomainValidationError, match="Unsupported file format"):
            exe_f = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/octet-stream")
            validate_media_file(exe_f)

        # 4. Disallowed video formats: AVI, MKV, WEBM
        with pytest.raises(DomainValidationError, match="Unsupported video format"):
            avi_f = SimpleUploadedFile("movie.avi", b"RIFF....AVI", content_type="video/x-msvideo")
            validate_media_file(avi_f)

        # 5. Picture size constraint (> 10MB)
        mock_large_img = SimpleUploadedFile("huge.jpg", b"0", content_type="image/jpeg")
        mock_large_img.size = 11 * 1024 * 1024
        with pytest.raises(DomainValidationError, match="exceeds the 10 MB limit"):
            validate_media_file(mock_large_img)

        # 6. Video size constraint (> 200MB)
        mock_large_vid = SimpleUploadedFile("huge.mp4", b"0", content_type="video/mp4")
        mock_large_vid.size = 205 * 1024 * 1024
        with pytest.raises(DomainValidationError, match="exceeds the 200 MB limit"):
            validate_media_file(mock_large_vid)

    def test_custom_video_thumbnail_replaces_only_video(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]

        img_file = create_mock_image("picture.png")
        post = create_post(gym=gym, author_user=owner, content_text="Pic post", media_files=[img_file])
        pic_media = post.media_attachments.first()

        thumb_file = create_mock_image("thumb.png")
        # Attempting custom thumbnail on picture must fail
        with pytest.raises(DomainValidationError, match="only be uploaded for video"):
            update_video_thumbnail(post_media=pic_media, custom_thumbnail_file=thumb_file)

        # Uploading on a video succeeds
        vid_file = create_mock_video("clip.mp4")
        post_vid = create_post(gym=gym, author_user=owner, content_text="Vid post", media_files=[vid_file])
        vid_media = post_vid.media_attachments.first()

        updated_vid = update_video_thumbnail(post_media=vid_media, custom_thumbnail_file=thumb_file)
        assert updated_vid.thumbnail_url is not None

    def test_update_post_prevents_emptying_without_media(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]

        post = create_post(gym=gym, author_user=owner, content_text="Initial text")
        # Trying to strip text when no media exists raises DomainValidationError
        with pytest.raises(DomainValidationError, match="cannot be left empty"):
            update_post(post=post, content_text="")

        with pytest.raises(DomainValidationError, match="cannot be left empty"):
            update_post(post=post, content_text="   \n  ")

        # But updating text with valid string succeeds
        updated = update_post(post=post, content_text="Updated gym schedule for summer!")
        assert updated.content_text == "Updated gym schedule for summer!"

    def test_delete_post_cleans_up_record_and_media(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]

        img = create_mock_image("to_delete.png")
        post = create_post(gym=gym, author_user=owner, content_text="Will be deleted", media_files=[img])
        post_id = post.id
        media_id = post.media_attachments.first().id

        delete_post(post)

        assert not GymPost.objects.filter(id=post_id).exists()
        assert not GymPostMedia.objects.filter(id=media_id).exists()


# ==============================================================================
# 2. PRIVACY & ACCESS CONTROL (GUEST VS MEMBER VS STAFF)
# ==============================================================================

@pytest.mark.django_db
class TestCommunityFeedPrivacyAndVisibility:
    def test_feed_visibility_rules(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]
        anon_client = post_gym_setup["anon_client"]
        other_client = post_gym_setup["other_client"]
        member_client = post_gym_setup["member_client"]
        staff_client = post_gym_setup["staff_client"]

        # Create 1 public post and 1 members_only post
        public_post = create_post(
            gym=gym,
            author_user=owner,
            content_text="Public announcements for everyone!",
            privacy=PostPrivacyEnum.PUBLIC,
        )
        members_post = create_post(
            gym=gym,
            author_user=owner,
            content_text="Exclusive member discount and locker codes!",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )

        # 1. Anonymous guest querying feed sees ONLY public post
        res_anon = anon_client.get(f"/api/v1/posts/?gym_id={gym.id}")
        assert res_anon.status_code == status.HTTP_200_OK
        ids_anon = [p["id"] for p in res_anon.data.get("results", res_anon.data)]
        assert str(public_post.id) in ids_anon
        assert str(members_post.id) not in ids_anon

        # 2. Anonymous guest explicitly requesting ?privacy=members_only gets empty results
        res_anon_filtered = anon_client.get(f"/api/v1/posts/?gym_id={gym.id}&privacy=members_only")
        assert res_anon_filtered.status_code == status.HTTP_200_OK
        ids_anon_filt = [p["id"] for p in res_anon_filtered.data.get("results", res_anon_filtered.data)]
        assert str(members_post.id) not in ids_anon_filt

        # 3. Authenticated Non-member stranger sees ONLY public post
        res_other = other_client.get(f"/api/v1/posts/?gym_id={gym.id}")
        assert res_other.status_code == status.HTTP_200_OK
        ids_other = [p["id"] for p in res_other.data.get("results", res_other.data)]
        assert str(public_post.id) in ids_other
        assert str(members_post.id) not in ids_other

        # 4. Verified active member sees BOTH public and members_only posts
        res_member = member_client.get(f"/api/v1/posts/?gym_id={gym.id}")
        assert res_member.status_code == status.HTTP_200_OK
        ids_member = [p["id"] for p in res_member.data.get("results", res_member.data)]
        assert str(public_post.id) in ids_member
        assert str(members_post.id) in ids_member

        # 5. Member filtering by ?privacy=members_only sees only members_post
        res_m_filter = member_client.get(f"/api/v1/posts/?gym_id={gym.id}&privacy=members_only")
        assert res_m_filter.status_code == status.HTTP_200_OK
        ids_m_filt = [p["id"] for p in res_m_filter.data.get("results", res_m_filter.data)]
        assert str(members_post.id) in ids_m_filt
        assert str(public_post.id) not in ids_m_filt

        # 6. Gym staff sees both public and members_only posts
        res_staff = staff_client.get(f"/api/v1/posts/?gym_id={gym.id}")
        assert res_staff.status_code == status.HTTP_200_OK
        ids_staff = [p["id"] for p in res_staff.data.get("results", res_staff.data)]
        assert str(public_post.id) in ids_staff
        assert str(members_post.id) in ids_staff

    def test_single_post_detail_privacy_enforcement(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]
        anon_client = post_gym_setup["anon_client"]
        other_client = post_gym_setup["other_client"]
        member_client = post_gym_setup["member_client"]

        members_post = create_post(
            gym=gym,
            author_user=owner,
            content_text="Secret member workout tips",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )

        # Anonymous request for members_only post detail returns 403 Forbidden
        res_anon = anon_client.get(f"/api/v1/posts/{members_post.id}/?gym_id={gym.id}")
        assert res_anon.status_code == status.HTTP_403_FORBIDDEN

        # Non-member authenticated request returns 403 Forbidden
        res_other = other_client.get(f"/api/v1/posts/{members_post.id}/?gym_id={gym.id}")
        assert res_other.status_code == status.HTTP_403_FORBIDDEN

        # Member request returns 200 OK
        res_member = member_client.get(f"/api/v1/posts/{members_post.id}/?gym_id={gym.id}")
        assert res_member.status_code == status.HTTP_200_OK
        assert res_member.data["content_text"] == "Secret member workout tips"


# ==============================================================================
# 3. RBAC & PERMISSION MUTATION ENFORCEMENT
# ==============================================================================

@pytest.mark.django_db
class TestPostRBACAndMutations:
    def test_create_post_rbac(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        anon_client = post_gym_setup["anon_client"]
        other_client = post_gym_setup["other_client"]
        member_client = post_gym_setup["member_client"]
        limited_client = post_gym_setup["limited_client"]
        inactive_client = post_gym_setup["inactive_client"]
        staff_client = post_gym_setup["staff_client"]
        owner_client = post_gym_setup["owner_client"]

        payload = {"content_text": "Community motivation quote", "privacy": "public"}

        # 1. Anonymous -> 401
        res = anon_client.post(f"/api/v1/posts/?gym_id={gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

        # 2. Non-staff member -> 403
        res = member_client.post(f"/api/v1/posts/?gym_id={gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 3. Unrelated stranger -> 403
        res = other_client.post(f"/api/v1/posts/?gym_id={gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 4. Inactive staff -> 403
        res = inactive_client.post(f"/api/v1/posts/?gym_id={gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 5. Staff without posts:manage -> 403
        res = limited_client.post(f"/api/v1/posts/?gym_id={gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 6. Staff with posts:manage -> 201 Created
        res = staff_client.post(f"/api/v1/posts/?gym_id={gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["content_text"] == "Community motivation quote"

        # 7. Gym owner -> 201 Created
        res = owner_client.post(
            f"/api/v1/posts/?gym_id={gym.id}",
            {"content_text": "Owner special broadcast"},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED

    def test_patch_and_delete_post_rbac(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]
        anon_client = post_gym_setup["anon_client"]
        member_client = post_gym_setup["member_client"]
        staff_client = post_gym_setup["staff_client"]

        post = create_post(gym=gym, author_user=owner, content_text="Initial post")

        # Anonymous PATCH -> 401
        res = anon_client.patch(f"/api/v1/posts/{post.id}/?gym_id={gym.id}", {"content_text": "Hacked"}, format="json")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

        # Member PATCH -> 403
        res = member_client.patch(f"/api/v1/posts/{post.id}/?gym_id={gym.id}", {"content_text": "Hacked"}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Staff with posts:manage PATCH -> 200
        res = staff_client.patch(f"/api/v1/posts/{post.id}/?gym_id={gym.id}", {"content_text": "Staff edit"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["content_text"] == "Staff edit"

        # Member DELETE -> 403
        res = member_client.delete(f"/api/v1/posts/{post.id}/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Staff DELETE -> 200
        res = staff_client.delete(f"/api/v1/posts/{post.id}/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        assert not GymPost.objects.filter(id=post.id).exists()


# ==============================================================================
# 4. MULTIPART FILE UPLOADS & ATTACHMENT REORDERING
# ==============================================================================

@pytest.mark.django_db(transaction=True)
class TestMultipartUploadsAndMediaOrder:
    @patch("apps.posts.tasks.optimize_post_media_task.delay")
    def test_multipart_file_upload_post(self, mock_task, post_gym_setup):
        gym = post_gym_setup["gym"]
        staff_client = post_gym_setup["staff_client"]

        img1 = create_mock_image("img1.png")
        img2 = create_mock_image("img2.jpg", format="JPEG")

        res = staff_client.post(
            f"/api/v1/posts/?gym_id={gym.id}",
            {
                "content_text": "Check out these two event photos!",
                "privacy": "public",
                "media_files": [img1, img2],
            },
            format="multipart",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["media_count"] == 2
        assert len(res.data["media_attachments"]) == 2
        assert mock_task.called

    def test_reordering_media_attachments(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]
        owner_client = post_gym_setup["owner_client"]

        img1 = create_mock_image("first.png")
        img2 = create_mock_image("second.png")

        post = create_post(
            gym=gym,
            author_user=owner,
            content_text="Reorder test",
            media_files=[img1, img2],
        )
        media_list = list(post.media_attachments.order_index_asc()) if hasattr(post.media_attachments, "order_index_asc") else list(post.media_attachments.order_by("order_index"))
        m1, m2 = media_list[0], media_list[1]
        assert m1.order_index == 0
        assert m2.order_index == 1

        # Re-order: swap orders
        res = owner_client.patch(
            f"/api/v1/posts/{post.id}/?gym_id={gym.id}",
            {
                "media_order": [
                    {"media_id": str(m1.id), "order_index": 10},
                    {"media_id": str(m2.id), "order_index": 5},
                ]
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK

        m1.refresh_from_db()
        m2.refresh_from_db()
        assert m1.order_index == 10
        assert m2.order_index == 5


# ==============================================================================
# 5. CUSTOM VIDEO THUMBNAIL ENDPOINT
# ==============================================================================

@pytest.mark.django_db
class TestCustomVideoThumbnailEndpoint:
    def test_custom_video_thumbnail_api(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]
        owner_client = post_gym_setup["owner_client"]
        member_client = post_gym_setup["member_client"]

        vid = create_mock_video("lesson.mp4")
        post = create_post(gym=gym, author_user=owner, content_text="Video workout", media_files=[vid])
        vid_media = post.media_attachments.first()

        thumb_img = create_mock_image("custom_thumb.jpg", format="JPEG")

        # 1. Member cannot upload thumbnail -> 403
        res = member_client.patch(
            f"/api/v1/posts/{post.id}/media/{vid_media.id}/thumbnail/?gym_id={gym.id}",
            {"thumbnail_image": thumb_img},
            format="multipart",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 2. Missing thumbnail file -> 400
        res = owner_client.patch(
            f"/api/v1/posts/{post.id}/media/{vid_media.id}/thumbnail/?gym_id={gym.id}",
            {},
            format="multipart",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Invalid file type for thumbnail (e.g. upload video as thumbnail) -> 400
        fake_mp4_thumb = SimpleUploadedFile("bad_thumb.mp4", b"fake", content_type="video/mp4")
        res = owner_client.patch(
            f"/api/v1/posts/{post.id}/media/{vid_media.id}/thumbnail/?gym_id={gym.id}",
            {"thumbnail_image": fake_mp4_thumb},
            format="multipart",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 4. Valid image thumbnail -> 200 OK
        thumb_img.seek(0)
        res = owner_client.patch(
            f"/api/v1/posts/{post.id}/media/{vid_media.id}/thumbnail/?gym_id={gym.id}",
            {"thumbnail_image": thumb_img},
            format="multipart",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["thumbnail_url"] is not None


# ==============================================================================
# 6. TENANT ISOLATION & IDOR ATTACK PREVENTION
# ==============================================================================

@pytest.mark.django_db
class TestPostTenantIsolationAndIDOR:
    def test_cross_tenant_isolation(self, post_gym_setup):
        gym_a = post_gym_setup["gym"]
        gym_b = post_gym_setup["gym_b"]
        owner_client = post_gym_setup["owner_client"]
        other_gym_client = post_gym_setup["other_gym_client"]

        post_a = create_post(
            gym=gym_a,
            author_user=post_gym_setup["owner"],
            content_text="Gym A private confidential post",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )

        # 1. Other gym owner querying Gym A's post with Gym B's context -> 404
        res = other_gym_client.get(f"/api/v1/posts/{post_a.id}/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # 2. Other gym owner attempting to PATCH Gym A's post -> 404
        res = other_gym_client.patch(
            f"/api/v1/posts/{post_a.id}/?gym_id={gym_b.id}",
            {"content_text": "Malicious takeover"},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # 3. Other gym owner attempting to DELETE Gym A's post -> 404
        res = other_gym_client.delete(f"/api/v1/posts/{post_a.id}/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 7. DATA TYPE MISMATCHES, BOUNDARIES & ROBUSTNESS
# ==============================================================================

@pytest.mark.django_db
class TestPostEdgeCasesAndBoundaries:
    def test_malformed_uuids_return_clean_400_or_404(self, post_gym_setup):
        owner_client = post_gym_setup["owner_client"]
        gym = post_gym_setup["gym"]

        # Malformed gym_id in query
        res = owner_client.get("/api/v1/posts/?gym_id=not-a-valid-uuid")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        # Missing gym_id entirely
        res = owner_client.get("/api/v1/posts/")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        # Malformed post_id in URL path
        res = owner_client.get(f"/api/v1/posts/invalid-post-uuid/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_type_juggling_in_create_payload(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner_client = post_gym_setup["owner_client"]

        # Integer instead of string for content_text
        res = owner_client.post(
            f"/api/v1/posts/?gym_id={gym.id}",
            {"content_text": 1234567},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Boolean instead of string for content_text
        res = owner_client.post(
            f"/api/v1/posts/?gym_id={gym.id}",
            {"content_text": True},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Invalid privacy enum value
        res = owner_client.post(
            f"/api/v1/posts/?gym_id={gym.id}",
            {"content_text": "Hello", "privacy": "super_secret_vip"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_search_and_pagination(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]
        owner_client = post_gym_setup["owner_client"]

        for i in range(15):
            create_post(gym=gym, author_user=owner, content_text=f"Cardio marathon #{i:02d}")

        # Search matching
        res = owner_client.get(f"/api/v1/posts/?gym_id={gym.id}&search=marathon")
        assert res.status_code == status.HTTP_200_OK
        results = res.data.get("results", res.data)
        assert len(results) > 0

        # Search non-matching
        res_none = owner_client.get(f"/api/v1/posts/?gym_id={gym.id}&search=nonexistentwordxyz")
        assert res_none.status_code == status.HTTP_200_OK
        assert len(res_none.data.get("results", res_none.data)) == 0

        # Pagination: page_size=5
        res_p = owner_client.get(f"/api/v1/posts/?gym_id={gym.id}&page=1&page_size=5")
        assert res_p.status_code == status.HTTP_200_OK
        assert len(res_p.data["results"]) == 5

    def test_http_method_not_allowed_405(self, post_gym_setup):
        gym = post_gym_setup["gym"]
        owner_client = post_gym_setup["owner_client"]

        # PUT /api/v1/posts/
        res = owner_client.put(f"/api/v1/posts/?gym_id={gym.id}", {})
        assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # POST /api/v1/posts/{id}/
        fake_id = uuid.uuid4()
        res = owner_client.post(f"/api/v1/posts/{fake_id}/?gym_id={gym.id}", {})
        assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # GET /api/v1/posts/{id}/media/{media_id}/thumbnail/
        res = owner_client.get(f"/api/v1/posts/{fake_id}/media/{fake_id}/thumbnail/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ==============================================================================
# 8. CELERY ASYNC MEDIA OPTIMIZATION TASK
# ==============================================================================

@pytest.mark.django_db
class TestCeleryMediaOptimizationTask:
    def test_optimize_post_media_task_execution(self, post_gym_setup, tmp_path):
        gym = post_gym_setup["gym"]
        owner = post_gym_setup["owner"]

        # 1. Image optimization task
        img = create_mock_image("task_test.png")
        post = create_post(gym=gym, author_user=owner, content_text="Task post", media_files=[img])
        media_obj = post.media_attachments.first()

        # Run task synchronously
        optimize_post_media_task(str(media_obj.id))

        media_obj.refresh_from_db()
        assert media_obj.processing_status == ProcessingStatus.COMPLETED
        assert media_obj.thumbnail_url is not None
        assert media_obj.width is not None
        assert media_obj.height is not None

        # 2. Non-existent media task gracefully handles
        with pytest.raises(Exception):
            optimize_post_media_task(str(uuid.uuid4()))
