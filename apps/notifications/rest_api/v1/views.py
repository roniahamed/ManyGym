import uuid
from typing import Optional

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.models import Gym
from apps.notifications.permissions import IsNotificationRecipient
from apps.notifications.rest_api.v1.serializers import (
    DeviceTokenDetailSerializer,
    DeviceTokenRegisterSerializer,
    DeviceTokenUnregisterSerializer,
    MarkAllReadResponseSerializer,
    NotificationDetailSerializer,
    NotificationFilterSerializer,
    UnreadCountResponseSerializer,
)
from apps.notifications.selectors import (
    get_notification_by_id,
    get_unread_notification_count,
    get_user_device_tokens,
    list_notifications,
)
from apps.notifications.services import (
    delete_notification,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    register_device_token,
    unregister_device_token,
)
from common.exceptions import ResourceNotFoundError
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer


def _resolve_request_gym(request) -> Optional[Gym]:
    """Helper to resolve active gym context if present on request."""
    gym_id = getattr(request, "gym_id", None)
    if not gym_id:
        return None
    try:
        gym_uuid = uuid.UUID(str(gym_id))
        return Gym.objects.filter(id=gym_uuid).first()
    except (ValueError, TypeError, AttributeError):
        return None


class NotificationListView(APIView):
    """
    Retrieves a paginated list of in-app notifications for the authenticated user.
    Supports filtering by read/unread status and notification event type.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    @extend_schema(
        tags=["Notifications"],
        summary="List User Notifications",
        description="Retrieves a paginated list of notifications for the authenticated user or active gym workspace.",
        parameters=[
            OpenApiParameter(
                name="is_read",
                type=bool,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by read (true) or unread (false) status.",
            ),
            OpenApiParameter(
                name="notification_type",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by notification type (e.g. 'reaction', 'comment', 'member_request').",
            ),
            OpenApiParameter(
                name="page",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page number.",
            ),
            OpenApiParameter(
                name="page_size",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Items per page (max 100).",
            ),
        ],
        responses={
            200: NotificationDetailSerializer(many=True),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation Error"),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
        },
    )
    def get(self, request):
        active_gym = _resolve_request_gym(request)

        # 1. Parse and validate query filters using Serializer
        filter_serializer = NotificationFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        # 2. Retrieve optimized QuerySet via Selector
        queryset = list_notifications(
            user=request.user,
            gym=active_gym,
            is_read=filters.get("is_read"),
            notification_type=filters.get("notification_type"),
        )

        # 3. Paginate and return response
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = NotificationDetailSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class NotificationUnreadCountView(APIView):
    """
    Retrieves total unread notification badge count for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Notifications"],
        summary="Get Unread Notification Count",
        description="Returns total number of unread in-app notifications for badge calculation.",
        responses={
            200: UnreadCountResponseSerializer,
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
        },
    )
    def get(self, request):
        active_gym = _resolve_request_gym(request)
        count = get_unread_notification_count(user=request.user, gym=active_gym)
        serializer = UnreadCountResponseSerializer({"unread_count": count})
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationMarkAllReadView(APIView):
    """
    Atomically marks all unread notifications for the user as read.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Notifications"],
        summary="Mark All Notifications as Read",
        description="Atomically marks all unread notifications for the user as read.",
        responses={
            200: MarkAllReadResponseSerializer,
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
        },
    )
    def post(self, request):
        active_gym = _resolve_request_gym(request)
        count = mark_all_notifications_as_read(user=request.user, gym=active_gym)
        serializer = MarkAllReadResponseSerializer({"marked_read_count": count})
        return Response(serializer.data, status=status.HTTP_200_OK)


class NotificationDetailView(APIView):
    """
    Retrieves or permanently deletes a single notification.
    """
    permission_classes = [IsAuthenticated, IsNotificationRecipient]

    @extend_schema(
        tags=["Notifications"],
        summary="Get Notification Detail",
        description="Retrieves a single notification by UUID.",
        responses={
            200: NotificationDetailSerializer,
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Notification Not Found"),
        },
    )
    def get(self, request, notification_id):
        active_gym = _resolve_request_gym(request)
        notification = get_notification_by_id(notification_id=notification_id, user=request.user, gym=active_gym)
        if not notification:
            raise ResourceNotFoundError("Notification not found.")
        self.check_object_permissions(request, notification)
        serializer = NotificationDetailSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Notifications"],
        summary="Delete Notification",
        description="Permanently deletes a notification by UUID.",
        responses={
            204: OpenApiResponse(description="Notification successfully deleted"),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Notification Not Found"),
        },
    )
    def delete(self, request, notification_id):
        active_gym = _resolve_request_gym(request)
        notification = get_notification_by_id(notification_id=notification_id, user=request.user, gym=active_gym)
        if not notification:
            raise ResourceNotFoundError("Notification not found.")
        self.check_object_permissions(request, notification)
        delete_notification(notification_id=notification_id, user=request.user, gym=active_gym)
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotificationMarkReadView(APIView):
    """
    Marks a single notification as read.
    """
    permission_classes = [IsAuthenticated, IsNotificationRecipient]

    @extend_schema(
        tags=["Notifications"],
        summary="Mark Notification as Read",
        description="Marks a specific notification as read and records read timestamp.",
        responses={
            200: NotificationDetailSerializer,
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Notification Not Found"),
        },
    )
    def patch(self, request, notification_id):
        active_gym = _resolve_request_gym(request)
        notification = mark_notification_as_read(notification_id=notification_id, user=request.user, gym=active_gym)
        serializer = NotificationDetailSerializer(notification)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, notification_id):
        return self.patch(request, notification_id)


class DeviceTokenListView(APIView):
    """
    Manages client device tokens for push notification delivery.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Notifications"],
        summary="List Registered Devices",
        description="Lists all active and registered device tokens for the authenticated user.",
        responses={
            200: DeviceTokenDetailSerializer(many=True),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
        },
    )
    def get(self, request):
        devices = get_user_device_tokens(user=request.user)
        serializer = DeviceTokenDetailSerializer(devices, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Notifications"],
        summary="Register Device Token",
        description="Registers or updates an FCM registration token for push notifications.",
        request=DeviceTokenRegisterSerializer,
        responses={
            201: DeviceTokenDetailSerializer,
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation Error"),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
        },
    )
    def post(self, request):
        serializer = DeviceTokenRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = register_device_token(
            user=request.user,
            token=serializer.validated_data["token"],
            device_id=serializer.validated_data.get("device_id", ""),
            device_name=serializer.validated_data.get("device_name", ""),
            platform=serializer.validated_data.get("platform", "android"),
        )
        detail_serializer = DeviceTokenDetailSerializer(device)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)


class DeviceTokenUnregisterView(APIView):
    """
    Unregisters / deactivates an FCM device token upon logout.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Notifications"],
        summary="Unregister Device Token",
        description="Deactivates an active device token for the user upon sign out.",
        request=DeviceTokenUnregisterSerializer,
        responses={
            200: OpenApiResponse(description="Token deactivated successfully"),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation Error"),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Unauthenticated"),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Device Token Not Found"),
        },
    )
    def post(self, request):
        serializer = DeviceTokenUnregisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        unregistered = unregister_device_token(
            user=request.user,
            token=serializer.validated_data["token"],
        )
        if not unregistered:
            raise ResourceNotFoundError("Device token not found.")
        return Response(
            {"unregistered": True, "message": "Device token unregistered successfully."},
            status=status.HTTP_200_OK,
        )

    def delete(self, request):
        data = request.data if request.data else {"token": request.query_params.get("token")}
        serializer = DeviceTokenUnregisterSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        unregistered = unregister_device_token(
            user=request.user,
            token=serializer.validated_data["token"],
        )
        if not unregistered:
            raise ResourceNotFoundError("Device token not found.")
        return Response(
            {"unregistered": True, "message": "Device token unregistered successfully."},
            status=status.HTTP_200_OK,
        )
