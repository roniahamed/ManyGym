# Phase 9: Automated Background Tasks & Lifecycle Maintenance Documentation

## Overview & Architecture
The Phase 9 module implements the automated asynchronous background processing layer and periodic lifecycle maintenance engine for Many Gym. Using **Celery**, **Redis**, and **Celery Beat**, it offloads resource-heavy operations (such as transactional email dispatching) from the synchronous HTTP request-response cycle and executes periodic maintenance routines (such as subscription status transitions, lead follow-up alerts, and expired auth token purges).

### Architectural Invariants
1. **Separation of Concerns**: Per the project's layered architecture guidelines, all task functions in `tasks.py` act purely as thin, fault-tolerant orchestration wrappers. They catch and log unexpected exceptions, while all database queries, domain validation, and atomic state updates reside strictly within `services.py`.
2. **Atomic Bulk Database Updates**: Status transitions (e.g. expiring past-due memberships or activating scheduled subscriptions) are performed via database-level SQL updates (`.filter(...).update(...)`) rather than in-memory Python iteration loops to prevent race conditions and guarantee high throughput.
3. **Multi-Tenant Safety**: Automated routines operate across all gyms without leaking context or breaking per-gym relational boundaries.
4. **Idempotence & Fault Tolerance**: Periodic tasks are fully idempotent. Re-running a scheduled job multiple times produces deterministic results without duplicate emails or unintended state transitions.

---

## Background Tasks & Periodic Crons Specification

### 1. Reconcile Expired Subscriptions
- **Celery Task**: `apps.members.tasks.reconcile_expired_subscriptions_task`
- **Service Layer**: `apps.members.services.reconcile_expired_subscriptions()`
- **Celery Beat Schedule**: Daily at 00:05 UTC (`crontab(minute=5, hour=0)`)
- **Business Logic**:
  - Automatically transitions active subscriptions with an `end_date` strictly prior to current date to `EXPIRED` status:
    ```sql
    UPDATE members_membersubscription 
    SET status = 'expired' 
    WHERE status = 'active' AND end_date < CURRENT_DATE;
    ```
  - Automatically transitions future scheduled subscriptions that have reached or passed their `start_date` to `ACTIVE` status:
    ```sql
    UPDATE members_membersubscription 
    SET status = 'active' 
    WHERE status = 'scheduled' AND start_date <= CURRENT_DATE;
    ```
- **Return Value**: Dictionary containing count of expired and activated subscriptions:
  ```json
  {
    "expired_count": 5,
    "activated_count": 2
  }
  ```

---

### 2. Subscription Expiry Reminders
- **Celery Task**: `apps.members.tasks.send_subscription_expiry_reminder_task`
- **Service Layer**: `apps.members.services.send_subscription_expiry_reminders()`
- **Celery Beat Schedule**: Daily at 08:00 UTC (`crontab(minute=0, hour=8)`)
- **Business Logic**:
  - Scans for all active subscriptions ending in exactly **7 days** or **1 day**:
    - `target_dates = [today + 7 days, today + 1 day]`
    - `MemberSubscription.objects.filter(status='active', end_date__in=target_dates)`
  - Resolves member contact email (`subscription.member.user.email`).
  - Sends a branded reminder email informing the member of their upcoming plan expiry and encouraging renewal.
- **Return Value**: Count of dispatched reminder emails:
  ```json
  {
    "reminders_sent": 8
  }
  ```

---

### 3. Lead Next Move Follow-up Reminders
- **Celery Task**: `apps.leads.tasks.send_lead_followup_reminder_task`
- **Service Layer**: `apps.leads.services.send_lead_followup_reminders()`
- **Celery Beat Schedule**: Daily at 08:30 UTC (`crontab(minute=30, hour=8)`)
- **Business Logic**:
  - Queries all uncompleted lead next actions scheduled for today or overdue:
    ```python
    LeadNextMove.objects.filter(is_completed=False, scheduled_date__lte=today)
    ```
  - **Recipient Resolution Invariant**:
    - If `lead.assigned_staff` is set with an active user email, reminder is routed to that staff member.
    - Fallback: If no staff is assigned, reminder is routed to `lead.gym.owner_user.email` to ensure zero missed sales opportunities.
  - Formats message containing lead name, phone/email, scheduled action type, and notes.
- **Return Value**: Total count of alerts dispatched:
  ```json
  {
    "reminders_sent": 4
  }
  ```

---

### 4. Purge Expired Auth Tokens
- **Celery Task**: `apps.authentication.tasks.cleanup_expired_tokens_task`
- **Service Layer**: `apps.authentication.services.cleanup_expired_tokens()`
- **Celery Beat Schedule**: Nightly at 02:00 UTC (`crontab(minute=0, hour=2)`)
- **Business Logic**:
  - Cleans up stale, expired contextual session tokens and one-time verification tokens from PostgreSQL:
    ```python
    AuthToken.objects.filter(expires_at__lt=timezone.now()).delete()
    ```
- **Return Value**: Total number of deleted database rows:
  ```json
  {
    "deleted_tokens": 142
  }
  ```

---

### 5. Member Invitation Email
- **Celery Task**: `apps.members.tasks.send_member_invitation_email_task`
- **Execution Mode**: Asynchronous event-driven task invoked upon member registration.
- **Payload Signature**:
  ```python
  send_member_invitation_email_task.delay(
      member_id=str(member.id),
      recipient_email=email,
      invite_token=raw_token,
      gym_name=gym.name
  )
  ```
- **Business Logic**:
  - Generates secure invitation onboarding link containing the verification token.
  - Sends invitation email via Django email backend / SMTP with instructions to complete account setup and profile password creation.

---

## Celery Beat Schedule Configuration

Configured in `config/settings/base.py`:

```python
CELERY_BEAT_SCHEDULE = {
    "reconcile_expired_subscriptions_daily": {
        "task": "apps.members.tasks.reconcile_expired_subscriptions_task",
        "schedule": crontab(minute=5, hour=0),  # Daily at 00:05 UTC
    },
    "send_subscription_expiry_reminders_daily": {
        "task": "apps.members.tasks.send_subscription_expiry_reminder_task",
        "schedule": crontab(minute=0, hour=8),  # Daily at 08:00 UTC
    },
    "send_lead_followup_reminders_daily": {
        "task": "apps.leads.tasks.send_lead_followup_reminder_task",
        "schedule": crontab(minute=30, hour=8),  # Daily at 08:30 UTC
    },
    "cleanup_expired_tokens_nightly": {
        "task": "apps.authentication.tasks.cleanup_expired_tokens_task",
        "schedule": crontab(minute=0, hour=2),  # Nightly at 02:00 UTC
    },
}
```

---

## Verification & Test Results
Comprehensive test suite implemented in `tests/test_phase9_security_and_edge_cases.py`:
- `test_reconcile_expired_subscriptions_logic`: Verifies active subscriptions expiring transition to `EXPIRED` and future scheduled subscriptions transition to `ACTIVE`.
- `test_reconcile_expired_subscriptions_task_execution`: Tests Celery task orchestration wrapper for reconcile.
- `test_send_subscription_expiry_reminders_7_and_1_days`: Validates email dispatching for exact 7-day and 1-day threshold boundaries while skipping subscriptions outside the window.
- `test_send_subscription_expiry_reminders_no_member_email`: Tests graceful boundary handling when member user has no email address.
- `test_send_lead_followup_reminders_assigned_staff`: Verifies next move alerts reach assigned staff member.
- `test_send_lead_followup_reminders_fallback_gym_owner`: Verifies next move alerts fallback to gym owner when unassigned.
- `test_cleanup_expired_tokens_service_and_task`: Verifies deletion of expired tokens while preserving active tokens.
- `test_send_member_invitation_email_task`: Verifies invitation email dispatching with invitation links.
- `test_celery_beat_schedule_configuration`: Asserts all 4 periodic tasks are registered in Celery Beat with valid crontab configurations.

**Test Run Output**: `9 passed in 5.43s (100% pass rate, 0 errors, 0 regressions)`.
