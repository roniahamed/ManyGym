import io
import os
import pytest
from PIL import Image
from pathlib import Path
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse

from apps.users.models import User
from apps.gyms.models import Gym, GymGallery
from apps.gyms.services import create_gym, add_gallery_item
from apps.gyms.tasks import optimize_gallery_media_task
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, GalleryCategoryEnum, MediaTypeEnum, ProcessingStatus


def generate_test_image(width=800, height=600, color=(200, 50, 50)):
    file_obj = io.BytesIO()
    img = Image.new("RGB", (width, height), color=color)
    img.save(file_obj, "jpeg")
    file_obj.seek(0)
    return SimpleUploadedFile("sample_workout.jpg", file_obj.read(), content_type="image/jpeg")


@pytest.fixture
def gym_owner(db):
    return User.objects.create_user(
        email="media.owner@example.com",
        password="Password123!",
        first_name="Media",
        last_name="Owner",
        is_verified=True,
    )


@pytest.fixture
def auth_client(gym_owner):
    tokens = issue_context_token(gym_owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def test_gym(gym_owner):
    return create_gym(owner_user=gym_owner, name="Apex Media Gym")


@pytest.mark.django_db
class TestMediaOptimizationPipeline:

    def test_upload_image_saves_locally_first(self, auth_client, test_gym):
        """
        First step: File is saved locally immediately with PENDING status,
        original_url set, and available right away.
        """
        url = reverse("gyms_v1:gym-gallery-list")
        img_file = generate_test_image(width=1200, height=900)

        res = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {
                "file": img_file,
                "category": GalleryCategoryEnum.WORKOUT_AREAS,
                "caption": "Heavy dumbbells and squat racks",
            },
            format="multipart",
        )
        assert res.status_code == status.HTTP_201_CREATED
        data = res.data

        item_id = data["id"]
        assert data["processing_status"] == ProcessingStatus.PENDING
        assert data["original_url"] is not None
        assert "original/" in data["original_url"]
        assert data["media_url"] == data["original_url"]

        # Verify file exists on local disk
        item = GymGallery.objects.get(id=item_id)
        local_rel = item.original_url.replace(settings.MEDIA_URL, "")
        local_path = Path(settings.MEDIA_ROOT) / local_rel
        assert local_path.exists()

    def test_background_optimization_creates_webp_and_thumbnail_while_retaining_original(self, test_gym):
        """
        Background process:
        1. Keeps original file intact ('ager ta reke').
        2. Generates WebP optimized version ('new optimisation ta thakbo').
        3. Generates WebP thumbnail.
        4. Calculates dimensions and size savings.
        """
        img_file = generate_test_image(width=2400, height=1800)
        item = add_gallery_item(
            gym=test_gym,
            file=img_file,
            category=GalleryCategoryEnum.EQUIPMENT,
            caption="Plate loaded leg press",
        )

        orig_url_before = item.original_url
        assert item.processing_status == ProcessingStatus.PENDING

        # Execute optimization task (synchronous invocation of the Celery task function)
        optimize_gallery_media_task(str(item.id))

        item.refresh_from_db()
        assert item.processing_status == ProcessingStatus.COMPLETED
        # Original is preserved intact ('ager ta reke')
        assert item.original_url == orig_url_before
        local_orig_rel = item.original_url.replace(settings.MEDIA_URL, "")
        assert (Path(settings.MEDIA_ROOT) / local_orig_rel).exists()

        # Optimized WebP is generated ('new optimisation ta thakbo')
        assert item.optimized_url is not None
        assert item.optimized_url.endswith(".webp")
        local_opt_rel = item.optimized_url.replace(settings.MEDIA_URL, "")
        opt_path = Path(settings.MEDIA_ROOT) / local_opt_rel
        assert opt_path.exists()

        # WebP Thumbnail is generated
        assert item.thumbnail_url is not None
        assert item.thumbnail_url.endswith(".webp")
        local_thumb_rel = item.thumbnail_url.replace(settings.MEDIA_URL, "")
        thumb_path = Path(settings.MEDIA_ROOT) / local_thumb_rel
        assert thumb_path.exists()

        # Media URL points to optimized WebP
        assert item.media_url == item.optimized_url

        # Dimensions & byte sizes recorded
        assert item.width == 2400
        assert item.height == 1800
        assert item.size_bytes > 0
        assert item.optimized_size_bytes > 0

        # Verify image formats
        with Image.open(opt_path) as opt_img:
            assert opt_img.format == "WEBP"
            assert opt_img.width <= 1920

        with Image.open(thumb_path) as thumb_img:
            assert thumb_img.format == "WEBP"
            assert thumb_img.width <= 400

        # Verify reusable mixin properties
        assert item.is_processed is True
        assert item.resolved_media_url == item.optimized_url
        assert item.resolved_thumbnail_url == item.thumbnail_url

    def test_video_optimization_extracts_poster_thumbnail(self, test_gym):
        """
        Video upload:
        Background process extracts poster thumbnail and marks completed.
        """
        # Create a dummy video file
        video_content = b"\x00\x00\x00 ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 1024
        video_file = SimpleUploadedFile("sample_workout.mp4", video_content, content_type="video/mp4")

        item = add_gallery_item(
            gym=test_gym,
            file=video_file,
            category=GalleryCategoryEnum.WORKOUT_AREAS,
            caption="Quick video tour",
        )
        assert item.media_type == MediaTypeEnum.VIDEO
        assert item.processing_status == ProcessingStatus.PENDING

        optimize_gallery_media_task(str(item.id))

        item.refresh_from_db()
        assert item.processing_status == ProcessingStatus.COMPLETED
        assert item.original_url is not None
        assert item.size_bytes > 0
        assert item.is_processed is True

    def test_reusable_media_optimizer_service_direct(self):
        """
        Test direct invocation of the reusable MediaOptimizerService methods.
        """
        from common.media import MediaOptimizerService

        # 1. Test save_uploaded_file
        dummy_file = generate_test_image(width=500, height=500)
        saved_path, public_url = MediaOptimizerService.save_uploaded_file(dummy_file, subfolder="avatars/test")
        assert saved_path.exists()
        assert "avatars/test/" in public_url

        # 2. Test optimize_image
        result = MediaOptimizerService.optimize_image(
            src_path=saved_path,
            subfolder="avatars/test",
            max_dims=(400, 400),
            thumb_dims=(150, 150),
        )
        assert result["width"] == 500
        assert result["height"] == 500
        assert result["optimized_url"].endswith(".webp")
        assert result["thumbnail_url"].endswith(".webp")
        assert result["optimized_size_bytes"] > 0
        assert result["size_bytes"] > 0

