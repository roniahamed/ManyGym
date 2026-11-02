import uuid
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema

from apps.memberships.models import MembershipPlan
from apps.members.models import MemberSubscription
from apps.members.selectors import get_member_detail
from apps.members.services import (
    create_member_subscription,
    record_member_payment,
    attach_extra_amenities,
    transition_membership_status,
)
from apps.members.rest_api.v1.serializers import (
    MemberSubscriptionCreateSerializer,
    MemberSubscriptionDetailSerializer,
    MemberSubscriptionStatusTransitionSerializer,
    MemberPaymentCreateSerializer,
    MemberPaymentSerializer,
    MemberExtraAmenitiesCreateSerializer,
    MemberExtraAmenitySerializer,
)
from apps.members.rest_api.v1.views.base_views import (
    resolve_member_gym,
    check_member_permission,
)
from common.exceptions import ResourceNotFoundError
from common.serializers import ErrorDetailSerializer


class MemberSubscriptionCreateView(APIView):
    """
    Attach a new membership subscription to an existing member.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Attach Subscription to Member",
        description="Attaches a new membership plan subscription, optional extra amenities, and initial payment.",
        request=MemberSubscriptionCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberSubscriptionDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, member_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        member = get_member_detail(member_id, gym)
        serializer = MemberSubscriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            plan = MembershipPlan.objects.get(id=data["plan_id"], gym=gym)
        except MembershipPlan.DoesNotExist:
            raise ResourceNotFoundError("Membership plan not found.")

        start_date = data.get("start_date") or timezone.now().date()
        sub = create_member_subscription(
            member=member,
            plan=plan,
            start_date=start_date,
            end_date=data.get("end_date"),
            extra_amenity_ids=data.get("extra_amenity_ids"),
            initial_payment_amount=data.get("initial_payment_amount"),
            initial_payment_method=data.get("initial_payment_method"),
            initial_payment_date=data.get("initial_payment_date"),
            initial_payment_notes=data.get("initial_payment_notes"),
        )
        return Response(MemberSubscriptionDetailSerializer(sub).data, status=status.HTTP_201_CREATED)


class MemberSubscriptionStatusView(APIView):
    """
    Pause, cancel, or resume a subscription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Transition Subscription Status",
        description="Transitions subscription state (active <-> paused, active/paused -> cancelled).",
        request=MemberSubscriptionStatusTransitionSerializer,
        responses={
            status.HTTP_200_OK: MemberSubscriptionDetailSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def patch(self, request, subscription_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        serializer = MemberSubscriptionStatusTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_status = serializer.validated_data["membership_status"]
        sub = transition_membership_status(subscription_id=subscription_id, gym=gym, new_status=new_status)
        return Response(MemberSubscriptionDetailSerializer(sub).data, status=status.HTTP_200_OK)


class MemberSubscriptionPaymentCreateView(APIView):
    """
    Log a payment transaction against a subscription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Log Subscription Payment",
        description="Records a payment transaction against the subscription and recalculates payment standing.",
        request=MemberPaymentCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberPaymentSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, subscription_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        try:
            sub = MemberSubscription.objects.select_related("plan", "member").get(
                id=subscription_id,
                member__gym=gym,
            )
        except MemberSubscription.DoesNotExist:
            raise ResourceNotFoundError(f"Member subscription '{subscription_id}' not found.")

        serializer = MemberPaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = record_member_payment(
            subscription=sub,
            amount=data["amount"],
            payment_method=data["payment_method"],
            payment_date=data.get("payment_date") or timezone.now().date(),
            notes=data.get("notes"),
        )
        return Response(MemberPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class MemberSubscriptionExtraAmenitiesView(APIView):
    """
    Attach extra paid amenities to a subscription.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Members & Subscriptions"],
        summary="Attach Extra Amenities",
        description="Subscribes member to additional paid amenities (e.g. personal locker, sauna).",
        request=MemberExtraAmenitiesCreateSerializer,
        responses={
            status.HTTP_201_CREATED: MemberExtraAmenitySerializer(many=True),
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def post(self, request, subscription_id: uuid.UUID):
        gym = resolve_member_gym(request)
        check_member_permission(request, gym, required_scope="members:edit")

        try:
            sub = MemberSubscription.objects.select_related("plan", "member__gym").get(
                id=subscription_id,
                member__gym=gym,
            )
        except MemberSubscription.DoesNotExist:
            raise ResourceNotFoundError(f"Member subscription '{subscription_id}' not found.")

        serializer = MemberExtraAmenitiesCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        amenity_ids = serializer.validated_data["amenity_ids"]

        extras = attach_extra_amenities(subscription=sub, amenity_ids=amenity_ids)
        return Response(MemberExtraAmenitySerializer(extras, many=True).data, status=status.HTTP_201_CREATED)
