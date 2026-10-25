import logging
from celery import shared_task
from apps.authentication.services import cleanup_expired_tokens

logger = logging.getLogger(__name__)


@shared_task(name="apps.authentication.tasks.cleanup_expired_tokens_task")
def cleanup_expired_tokens_task() -> int:
    """
    Nightly periodic Celery task:
    Purges expired contextual AuthToken records from the database.
    """
    count = cleanup_expired_tokens()
    logger.info(f"[Cron] cleanup_expired_tokens_task completed: {count} expired tokens purged.")
    return count
