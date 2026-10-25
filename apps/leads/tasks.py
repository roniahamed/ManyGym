import logging
from celery import shared_task
from apps.leads.services import send_lead_followup_reminders

logger = logging.getLogger(__name__)


@shared_task(name="apps.leads.tasks.send_lead_followup_reminder_task")
def send_lead_followup_reminder_task() -> int:
    """
    Daily periodic Celery task:
    Notifies staff members or gym owners of uncompleted LeadNextMove items scheduled for today.
    """
    count = send_lead_followup_reminders()
    logger.info(f"[Cron] send_lead_followup_reminder_task completed: {count} notifications dispatched.")
    return count
