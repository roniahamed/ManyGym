import uuid
from apps.gyms.models import GymGallery


def list_gallery_items(gym_id: str, category: str = None):
    """Retrieves gallery assets filtered by category with field projections."""
    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return GymGallery.objects.none()

    queryset = (
        GymGallery.objects.filter(gym_id=gym_id)
        .only(
            "id",
            "gym_id",
            "media_url",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "media_type",
            "category",
            "caption",
            "order_index",
            "processing_status",
            "width",
            "height",
            "size_bytes",
            "optimized_size_bytes",
            "created_at",
        )
    )
    if category:
        queryset = queryset.filter(category=category)
    return queryset.order_by("order_index", "-created_at")
