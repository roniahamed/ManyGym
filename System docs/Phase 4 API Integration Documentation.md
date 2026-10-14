# Phase 4: Member Lifecycle, Subscriptions & Payment Transactions System

## Overview & Architecture
This module implements complete end-to-end management for Gym Members, Onboarding Invitations, Subscriptions (time-based vs session-based), Paid Extra Amenities, and Payment Transaction Ledgers.

Adheres strictly to the **Layered Architectural Pattern**:
- **Models**: `Member`, `MemberSubscription`, `MemberExtraAmenities`, `MemberPayment` (`apps/members/models.py`)
- **Selectors**: High-performance, prefetching read operations with projection and streaming (`apps/members/selectors.py`)
- **Services**: Atomic business logic with strict invariants and Celery tasks (`apps/members/services.py`)
- **Tasks**: Celery asynchronous email dispatch for member invitations (`apps/members/tasks.py`)
- **Serializers**: Strict typing, data sanitization, and OpenAPI documentation (`apps/members/rest_api/v1/serializers.py`)
- **Views**: Declarative DRF APIViews with OpenAPI 3.0 / Swagger schema decorators (`apps/members/rest_api/v1/views.py`)

---

## Member Lifecycle & Onboarding

### 1. Member Creation & Invitation Flow
1. **Creation**: A gym manager or trainer creates a member record specifying personal information (`first_name`, `last_name`, `email`, `phone`, demographic details, and optional `assigned_trainer_id`).
2. **Initial Subscription & Payment**: The creation payload can atomically include an initial membership plan (`plan_id`, `start_date`, `extra_amenity_ids`) and an initial payment transaction (`initial_payment_amount`, `initial_payment_method`).
3. **Invitation Token & Email**: A secure URL-safe invitation token is automatically generated, stored on the member record, and an asynchronous invitation email is queued via Celery (`send_member_invitation_email`).
4. **Member Acceptance**: The user receives the token and submits it to `/api/v1/members/accept-invitation/`. The system links the authenticated `User` account to the `Member` record and marks `joining_status = "joined"`.

### 2. Subscription Engine & Calendar Calculation
- **Time-Based Plans**:
  - Automatically calculates `end_date` using calendar math (`dateutil.relativedelta` for calendar months, `timedelta` for days/weeks).
  - Status defaults to `active` if `start_date <= today`, or `scheduled` if `start_date > today`.
- **Session-Based Plans**:
  - Tracks `total_sessions` and `remaining_sessions`.
  - Requires an explicit expiration `end_date`.

### 3. Payment Standing Ledger
- Total subscription cost is dynamically calculated:
  $$\text{Total Cost} = \text{Plan Price} + \text{Joining Fee} + \sum(\text{Active Extra Amenities})$$
- On each payment recorded via `/api/v1/members/subscriptions/{id}/payments/`:
  - If $\sum(\text{Payments}) \ge \text{Total Cost} \implies \text{Payment Status} = \text{"fully\_paid"}$.
  - If $0 < \sum(\text{Payments}) < \text{Total Cost} \implies \text{Payment Status} = \text{"partially\_paid"}$.
  - If $\sum(\text{Payments}) = 0 \implies \text{Payment Status} = \text{"unpaid"}$.

---

## Complete API Endpoints List

| Method | Endpoint | Description | Auth & Permission Required |
|---|---|---|---|
| `GET` | `/api/v1/members/` | List members with filters (`joining_status`, `membership_status`, `payment_status`, `search`, pagination) | Bearer JWT (`members:read` / Owner) |
| `POST` | `/api/v1/members/` | Create member dossier with optional initial subscription & payment | Bearer JWT (`members:edit` / Owner) |
| `GET` | `/api/v1/members/metrics/` | Aggregated dashboard KPI metrics (total, active, invitations, overdue, payments) | Bearer JWT (`members:read` / Owner) |
| `POST` | `/api/v1/members/accept-invitation/` | Link user account via invitation token | Authenticated User |
| `GET` | `/api/v1/members/{member_id}/` | Full member dossier, active subscription, past subscriptions, and payment history | Bearer JWT (`members:read` / Owner) |
| `PATCH` | `/api/v1/members/{member_id}/` | Update profile, demographics, emergency contact, or trainer assignment | Bearer JWT (`members:edit` / Owner) |
| `DELETE` | `/api/v1/members/{member_id}/` | Delete member (or conflict error if active payment history exists) | Bearer JWT (`members:delete` / Owner) |
| `POST` | `/api/v1/members/{member_id}/resend-invitation/` | Regenerate invitation token and re-dispatch onboarding email | Bearer JWT (`members:edit` / Owner) |
| `POST` | `/api/v1/members/{member_id}/subscriptions/` | Attach a new subscription with optional extra amenities and initial payment | Bearer JWT (`members:edit` / Owner) |
| `PATCH` | `/api/v1/members/subscriptions/{subscription_id}/status/` | Transition subscription status (`active`, `paused`, `cancelled`) | Bearer JWT (`members:edit` / Owner) |
| `POST` | `/api/v1/members/subscriptions/{subscription_id}/payments/` | Record payment transaction and recompute payment standing | Bearer JWT (`members:edit` / Owner) |
| `POST` | `/api/v1/members/subscriptions/{subscription_id}/extra-amenities/` | Attach extra paid amenities and update total subscription cost | Bearer JWT (`members:edit` / Owner) |

---

## Performance Optimizations & Benchmarks
- **Zero N+1 Queries**: List selector uses `.only(...)` column projections, `select_related("assigned_trainer__user")`, and `prefetch_related("subscriptions__plan")`. Constant **4 queries** regardless of 10 or 1,000 members.
- **Composite Indexes**:
  - `idx_member_gym_created`: `("gym", "-created_at")`
  - `idx_member_gym_joining`: `("gym", "joining_status")`
  - `idx_member_gym_email`: `("gym", "email")`
  - `idx_member_gym_names`: `("gym", "first_name", "last_name")`
  - `idx_sub_member_created`: `("member", "-created_at")`
  - `idx_sub_status_end`: `("membership_status", "end_date")`
  - `idx_sub_pay_status`: `("payment_status")`
- **Streaming Export**: `stream_gym_members` leverages `QuerySet.iterator(chunk_size=500)` for memory-safe large-scale exports.
- **Aggregation Metric Pipeline**: `get_gym_member_metrics` uses a single aggregated SQL query (`Count`, `Sum`) to compute total active members, revenue collected, and invitation counts.
