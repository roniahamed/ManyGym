import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_member_invitation_email(
    self,
    member_id: str,
    email: str,
    first_name: str,
    gym_name: str,
    token: str,
) -> bool:
    """
    Dispatches member onboarding invitation email with acceptance token.
    """
    try:
        subject = f"Welcome to {gym_name}! Activate your membership"
        message = (
            f"Hi {first_name},\n\n"
            f"You have been invited to join {gym_name}.\n"
            f"Please activate your membership and complete your onboarding profile using the invitation token below:\n\n"
            f"Invitation Token: {token}\n\n"
            f"Best regards,\n"
            f"The {gym_name} Team"
        )
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        logger.info(f"Onboarding invitation email sent to {email} for member {member_id}")
        return True
    except Exception as exc:
        logger.error(f"Failed to dispatch member invitation email to {email}: {str(exc)}")
        raise self.retry(exc=exc)


# Task alias for Phase 9 specification
send_member_invitation_email_task = send_member_invitation_email


@shared_task(name="apps.members.tasks.reconcile_expired_subscriptions_task")
def reconcile_expired_subscriptions_task() -> int:
    """
    Daily periodic Celery task:
    Atomically updates active member subscriptions where end_date < today to 'expired'.
    Activates scheduled subscriptions where start_date <= today <= end_date.
    """
    from apps.members.services import reconcile_expired_subscriptions
    count = reconcile_expired_subscriptions()
    logger.info(f"[Cron] reconcile_expired_subscriptions_task completed: {count} subscriptions updated.")
    return count


@shared_task(name="apps.members.tasks.send_subscription_expiry_reminder_task")
def send_subscription_expiry_reminder_task() -> int:
    """
    Daily periodic Celery task:
    Queries subscriptions expiring in exactly 7 days and 1 day, and dispatches reminder notifications.
    """
    from apps.members.services import send_subscription_expiry_reminders
    count = send_subscription_expiry_reminders()
    logger.info(f"[Cron] send_subscription_expiry_reminder_task completed: {count} notifications sent.")
    return count
