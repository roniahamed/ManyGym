import uuid
from typing import Optional, Dict, Any, Generator
from django.db.models import QuerySet, Q, Count, Avg, Min, Max, Prefetch
from apps.gyms.models import Gym
from apps.memberships.models import MembershipPlan, PlanIncludedAmenities
from common.enums import PlanStatusEnum, PlanTypeEnum
from common.exceptions import ResourceNotFoundError


def list_gym_plans(
    gym: Gym,
    plan_status: Optional[str] = None,
    plan_type: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet[MembershipPlan]:
    """
    Retrieves membership plans for a gym with:
    - Eager prefetching with field projection on included amenities
    - SQL database annotation for included_amenities_count
    - Field projection (.only()) excluding heavy unused policy blobs
    - Composite index-aligned ordering
    """
    amenity_prefetch = Prefetch(
        "included_amenities",
        queryset=PlanIncludedAmenities.objects.select_related("gym_amenity__amenity").only(
            "id",
            "plan_id",
            "gym_amenity_id",
            "gym_amenity__id",
            "gym_amenity__gym_id",
            "gym_amenity__is_paid",
            "gym_amenity__default_price",
            "gym_amenity__amenity__id",
            "gym_amenity__amenity__group_name",
            "gym_amenity__amenity__name",
        ),
    )

    qs = (
        MembershipPlan.objects.filter(gym=gym)
        .only(
            "id",
            "gym_id",
            "name",
            "description",
            "plan_status",
            "plan_type",
            "price",
            "duration_value",
            "duration_unit",
            "joining_fee",
            "payment_schedule",
            "created_at",
            "updated_at",
        )
        .annotate(annotated_amenities_count=Count("included_amenities", distinct=True))
        .prefetch_related(amenity_prefetch)
        .order_by("-created_at")
    )

    if plan_status is not None:
        status_val = str(plan_status).lower().strip()
        if status_val:
            qs = qs.filter(plan_status=status_val)

    if plan_type is not None:
        type_val = str(plan_type).lower().strip()
        if type_val:
            qs = qs.filter(plan_type=type_val)

    if search is not None:
        search_term = str(search).strip()
        if search_term:
            qs = qs.filter(
                Q(name__icontains=search_term) | Q(description__icontains=search_term)
            )

    return qs


def get_plan_details(
    plan_id: uuid.UUID,
    gym: Gym,
) -> MembershipPlan:
    """
    Retrieves full 5-step details of a single membership plan with optimized eager joins.
    """
    amenity_prefetch = Prefetch(
        "included_amenities",
        queryset=PlanIncludedAmenities.objects.select_related("gym_amenity__amenity"),
    )
    try:
        return (
            MembershipPlan.objects.filter(id=plan_id, gym=gym)
            .prefetch_related(amenity_prefetch)
            .get()
        )
    except MembershipPlan.DoesNotExist:
        raise ResourceNotFoundError(f"Membership plan '{plan_id}' not found for this gym.")


def get_gym_plan_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Calculates aggregated pricing and plan metrics at the database level
    in a single SQL query without loading entire datasets into memory.
    """
    return MembershipPlan.objects.filter(gym=gym).aggregate(
        total_plans=Count("id"),
        active_plans=Count("id", filter=Q(plan_status=PlanStatusEnum.ACTIVE)),
        draft_plans=Count("id", filter=Q(plan_status=PlanStatusEnum.DRAFT)),
        archived_plans=Count("id", filter=Q(plan_status=PlanStatusEnum.ARCHIVED)),
        time_based_plans=Count("id", filter=Q(plan_type=PlanTypeEnum.TIME_BASED)),
        session_based_plans=Count("id", filter=Q(plan_type=PlanTypeEnum.SESSION_BASED)),
        avg_price=Avg("price"),
        min_price=Min("price"),
        max_price=Max("price"),
        avg_time_based_price=Avg("price", filter=Q(plan_type=PlanTypeEnum.TIME_BASED)),
        avg_session_based_price=Avg("price", filter=Q(plan_type=PlanTypeEnum.SESSION_BASED)),
    )


def stream_gym_plans(gym: Gym, chunk_size: int = 500) -> Generator[MembershipPlan, None, None]:
    """
    Yields membership plans using QuerySet.iterator() to stream large catalogs
    without materializing full querysets in RAM.
    """
    qs = (
        MembershipPlan.objects.filter(gym=gym)
        .only("id", "name", "plan_status", "plan_type", "price", "duration_value", "duration_unit")
        .order_by("-created_at")
    )
    for plan in qs.iterator(chunk_size=chunk_size):
        yield plan
