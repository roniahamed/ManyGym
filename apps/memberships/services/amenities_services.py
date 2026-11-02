import uuid
from typing import List
from django.db import transaction

from apps.gyms.models import Gym
from apps.amenities.models import GymAmenity
from apps.memberships.models import MembershipPlan, PlanIncludedAmenities
from common.exceptions import DomainValidationError


@transaction.atomic
def sync_plan_amenities(
    plan: MembershipPlan,
    gym: Gym,
    amenity_ids: List[uuid.UUID],
) -> List[PlanIncludedAmenities]:
    """
    Synchronizes included gym amenities for a plan. Validates that all amenity IDs
    belong to the gym.
    """
    if not amenity_ids:
        plan.included_amenities.all().delete()
        return []

    # Verify all amenity IDs belong to this gym
    valid_amenities = GymAmenity.objects.filter(id__in=amenity_ids, gym=gym)
    valid_amenity_map = {amenity.id: amenity for amenity in valid_amenities}

    invalid_ids = [aid for aid in amenity_ids if aid not in valid_amenity_map]
    if invalid_ids:
        raise DomainValidationError(
            f"The following amenity IDs do not belong to this gym or do not exist: {invalid_ids}"
        )

    # Current links
    current_links = {link.gym_amenity_id: link for link in plan.included_amenities.all()}
    target_ids = set(amenity_ids)

    # Remove links not in target
    to_delete = [link.id for aid, link in current_links.items() if aid not in target_ids]
    if to_delete:
        PlanIncludedAmenities.objects.filter(id__in=to_delete).delete()

    # Add missing links
    to_create = []
    seen = set()
    for aid in amenity_ids:
        if aid not in current_links and aid not in seen:
            seen.add(aid)
            to_create.append(
                PlanIncludedAmenities(
                    plan=plan,
                    gym_amenity=valid_amenity_map[aid],
                )
            )

    if to_create:
        PlanIncludedAmenities.objects.bulk_create(to_create)

    return list(plan.included_amenities.select_related("gym_amenity__amenity").all())
