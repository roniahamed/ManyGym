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

## Performance Optimizations & Measurable Benchmarks

### 1. Measurable Optimization Targets & Actual Results

| Performance Metric | Baseline Target | Before Optimization | After Optimization | Improvement |
|---|---|---|---|---|
| **`get_gym_member_metrics` (Selector Queries)** | 30–50% reduction | 3 queries | **1 query** | **-66.7% queries** (Exceeded) |
| **`GET /api/v1/members/metrics/` (API Queries)** | 30–50% reduction | 5 queries | **3 queries** | **-40.0% queries** |
| **`POST /api/v1/members/subscriptions/{id}/payments/`** | Reduce redundant updates | 9 queries | **7 queries** | **-22.2% queries** |
| **`GET /api/v1/members/` (Unpaginated 50 items)** | p95 < 200 ms | p95: 55.61 ms | **p95: 50.13 ms** (p50: 11.75 ms) | Well under target |
| **`GET /api/v1/members/` (Paginated 20 items)** | p95 < 200 ms | p95: 12.01 ms | **p95: 9.64 ms** (p50: 8.67 ms) | Well under target |
| **`GET /api/v1/members/{id}/` (Full Dossier)** | p95 < 200 ms | p95: 13.54 ms | **p95: 12.52 ms** (p50: 10.00 ms) | Well under target |
| **`POST .../payments/` (Complex Write)** | p95 < 500 ms | p95: 8.41 ms | **p95: 7.39 ms** (p50: 6.70 ms) | Well under target |

### 2. Applied Engineering Optimizations

- **N+1 Query Elimination & Strict Relation Loading**:
  - `list_gym_members` uses `select_related("assigned_trainer__user")` and `Prefetch("subscriptions", queryset=MemberSubscription.objects.select_related("plan"))`.
  - Constant **4 queries** unpaginated / **5 queries** paginated, completely flat scaling regardless of member count.
- **Data Retrieval & Column Projection (`.only(...)`)**:
  - `Member` list projection selects only essential identity and demographic columns, preventing retrieval of internal sensitive user fields (`password`, `last_login`, `is_superuser`).
  - `MemberSubscription` prefetch selects only 8 specific columns (`id`, `member_id`, `membership_status`, `payment_status`, `end_date`, `created_at`, `plan__id`, `plan__name`), preventing transfer of large text and JSON policies.
  - In-memory memoization on model instances (`_cached_curr_sub`, `_cached_assigned_trainer_dict`) eliminates redundant list slices during serialization.
- **Database Aggregation & Unified Single Query**:
  - `get_gym_member_metrics` uses a unified scalar subquery architecture in PostgreSQL via `connection.cursor()`. All 7 business KPIs (total members, joined, invited, active subscriptions, unpaid, fully paid, total revenue) compute in **1 single query**.
  - `recalculate_subscription_payment_status` combines `extra_amenities` and `payments` sum lookups into a single SQL statement, and conditionally writes with `update_fields=["payment_status", "updated_at"]` only when standing changes.
- **Database Composite Indexes**:
  - `idx_member_gym_created`: `("gym", "-created_at")`
  - `idx_member_gym_joining`: `("gym", "joining_status")`
  - `idx_member_gym_email`: `("gym", "email")`
  - `idx_member_gym_names`: `("gym", "first_name", "last_name")`
  - `idx_member_gym_trainer`: `("gym", "assigned_trainer")`
  - `idx_sub_member_created`: `("member", "-created_at")`
  - `idx_sub_status_end`: `("membership_status", "end_date")`
  - `idx_sub_payment_status`: `("payment_status")`
  - `idx_payment_sub_date`: `("member_subscription", "-payment_date")`
- **Memory-Safe Streaming**:
  - `stream_gym_members` streams large directories using `QuerySet.iterator(chunk_size=500)` without materializing whole tables in memory.
- **Performance Regression Guard**:
  - Automated tests in `tests/test_query_optimizations.py` enforce strict query limits:
    - `test_phase4_member_metrics_single_query_reduction`: asserts 1 query for selector, 3 queries for endpoint.
    - `test_phase4_member_directory_query_efficiency`: asserts 4 queries unpaginated, 5 queries paginated.
    - `test_phase4_member_detail_dossier_query_efficiency`: asserts 6 queries for complete dossier.
