import logging
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_email_task(self, subject, recipient_list, message, html_message=None):
    """
    Asynchronously dispatches emails via Django email backend / SMTP.
    """
    try:
        logger.info(f"Dispatching email to {recipient_list} with subject '{subject}'")
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Email successfully sent to {recipient_list}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send email to {recipient_list}: {str(exc)}")
        raise self.retry(exc=exc)
