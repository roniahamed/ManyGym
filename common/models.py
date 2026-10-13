from django.db import models
from common.enums import ProcessingStatus


class TimeStampedModel(models.Model):
    """
    Abstract base model providing self-updating created_at and updated_at fields.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OptimizedMediaMixin(models.Model):
    """
    Reusable abstract model mixin for media assets requiring background optimization.
    Maintains the original media ('ager ta reke') while storing optimized WebP
    and thumbnail variants with processing lifecycle status.
    """
    original_url = models.CharField(max_length=1000, blank=True, null=True)
    optimized_url = models.CharField(max_length=1000, blank=True, null=True)
    thumbnail_url = models.CharField(max_length=1000, blank=True, null=True)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    optimized_size_bytes = models.BigIntegerField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def resolved_media_url(self) -> str | None:
        """Returns the best available optimized URL, falling back to original."""
        return self.optimized_url or getattr(self, "media_url", None) or self.original_url

    @property
    def resolved_thumbnail_url(self) -> str | None:
        """Returns the thumbnail variant URL, falling back to optimized or original."""
        return self.thumbnail_url or self.optimized_url or getattr(self, "media_url", None) or self.original_url

    @property
    def is_processed(self) -> bool:
        """Returns True if background optimization completed successfully."""
        return self.processing_status == ProcessingStatus.COMPLETED
