from rest_framework.permissions import BasePermission


class IsNotificationRecipient(BasePermission):
    """
    Ensures that only the recipient user or associated gym staff can access/mutate the notification.
    """

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if obj.recipient_id == user.id:
            return True

        if obj.gym_id and getattr(request, "gym_id", None) == str(obj.gym_id):
            return True

        return False
