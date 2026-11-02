import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from common.enums import MemberJoiningStatus

logger = logging.getLogger(__name__)


@receiver(post_save, sender="members.Member")
def member_auto_follow_gym_signal(sender, instance, created, **kwargs):
    """
    Ensures connected gym members automatically follow their connected gym by default.
    Triggered when a member has an associated User and is in JOINED status.
    Members can unfollow later at any time.
    """
    if instance.user and instance.gym and instance.joining_status == MemberJoiningStatus.JOINED:
        try:
            from apps.gyms.services import auto_follow_gym_for_member
            auto_follow_gym_for_member(user=instance.user, gym=instance.gym)
        except Exception as exc:
            logger.warning(
                f"Failed to auto-follow gym {instance.gym_id} for member {instance.id}: {exc}"
            )
