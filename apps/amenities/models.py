import uuid
from django.db import models
from common.enums import AmenityGroupEnum


class AmenityCatalog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_name = models.CharField(
        max_length=50,
        choices=AmenityGroupEnum.choices,
        db_index=True,
    )
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "amenity_catalog"
        verbose_name = "Amenity Catalog Item"
        verbose_name_plural = "Amenity Catalog Items"
        unique_together = (("group_name", "name"),)
        ordering = ["group_name", "name"]

    def __str__(self):
        return f"[{self.get_group_name_display()}] {self.name}"


class GymAmenity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="gym_amenities",
    )
    amenity = models.ForeignKey(
        AmenityCatalog,
        on_delete=models.CASCADE,
        related_name="gym_instances",
    )
    is_paid = models.BooleanField(
        default=False,
        help_text="True if paid extra amenity; False if complimentary/free",
    )
    default_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gym_amenities"
        verbose_name = "Gym Configured Amenity"
        verbose_name_plural = "Gym Configured Amenities"
        unique_together = (("gym", "amenity"),)
        ordering = ["is_paid", "amenity__group_name", "amenity__name"]

    def __str__(self):
        paid_label = f"Paid (${self.default_price})" if self.is_paid else "Free"
        return f"{self.gym.name} - {self.amenity.name} ({paid_label})"
