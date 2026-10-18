# Phase 5: Leads CRM, Pipeline Tracking & Conversion Funnel System

## Overview & Architecture
The Phase 5 module implements an enterprise sales CRM pipeline for gyms to capture prospective leads, track pipeline stage transitions, schedule action items (next moves), log staff communication notes, define custom gym-level lost reason taxonomies, and atomically convert prospective leads into active gym members with onboarding invitation workflows.

Adheres strictly to the **Layered Architectural Pattern**:
- **Models**: `Lead`, `LeadCustomReasons`, `LeadFitnessGoals`, `LeadNextMove`, `LeadNotes` (`apps/leads/models.py`)
- **Selectors**: High-performance query logic with eager relationship loading, prefetching, and single-aggregation pipeline metrics (`apps/leads/selectors.py`)
- **Services**: Atomic business logic with strict validation, stage transition invariants, and cross-module member conversion (`apps/leads/services.py`)
- **Serializers**: Strict validation, typed representation, and OpenAPI 3.0 annotations (`apps/leads/rest_api/v1/serializers.py`)
- **Views**: Declarative DRF APIViews protected by RBAC permissions (`apps/leads/rest_api/v1/views.py`)

---

## Core Workflows & Business Invariants

### 1. Lead Capture & Contact Validation
- A lead must have a `first_name`.
- **Contact Invariant**: At least one contact method (`phone` or `email`) is strictly required. Leads with only phone, only email, or both are valid.
- Email addresses are normalized and validated for proper syntax.
- Initial fitness goals can be attached on creation (`general_fitness`, `strength`, `muscle_gain`, `weight_loss`, `other`).
- An initial internal staff note can be recorded atomically upon creation.

### 2. Pipeline Stage Transitions & Lost Reason Invariants
- Pipeline Stages: `new` $\rightarrow$ `contacted` $\rightarrow$ `visit_trial_booked` $\rightarrow$ `joined` / `not_joining`.
- **Visit/Trial Booking**: Sets `trial_booked_at` timestamp.
- **Not Joining Invariant**: When moving a lead to the `not_joining` stage, either:
  1. A standard lost reason must be selected (`price`, `location`, `timing`, `chose_another_gym`, `other`), OR
  2. A gym-specific custom reason (`not_joining_custom_reason_id` or dynamically created `custom_reason_name`) must be provided.
- **Joined Protection**: Leads that have joined (`stage = "joined"`) cannot have their stage reverted or be deleted if converted to an active gym member.

### 3. Action Items (Next Moves) & Notes Thread
- **Next Moves**: Gym staff can schedule follow-up actions with dates (`scheduled_date`, `short_description`). Tasks can be marked as completed or rescheduled.
- **Notes Thread**: Staff can log text notes detailing phone calls, gym tours, or special requests, automatically attributed to the active staff user.

### 4. Atomic Lead Conversion Engine
- A lead can be converted into an active member via `POST /api/v1/leads/{id}/convert/`.
- **Atomic Operations**:
  1. Provisions a `Member` record in `apps/members/` populated with lead details (name, email, phone, demographic data).
  2. If the lead originally only provided a phone number, `member_email` must be provided in the conversion payload to initiate digital onboarding.
  3. Automatically binds the requested or interested `MembershipPlan`, optional initial payment, and extra amenities.
  4. Generates a secure invitation token and dispatches the onboarding invitation email asynchronously via Celery.
  5. Updates lead `stage = "joined"`, sets `converted_member_id`, and appends an internal audit note to the lead's history.
  6. Idempotency Guard: Attempting to convert an already-converted lead returns a `409 Conflict`.

---

## Complete API Endpoints List

| Method | Endpoint | Description | Auth & Scope Required |
|---|---|---|---|
| `GET` | `/api/v1/leads/` | List leads directory with filters (`stage`, `source`, `assigned_staff_id`, `interested_plan_id`, `search`, pagination) | Bearer JWT (`leads:read` / Owner) |
| `POST` | `/api/v1/leads/` | Capture new lead with contact info, fitness goals, and initial note | Bearer JWT (`leads:manage` / Owner) |
| `GET` | `/api/v1/leads/metrics/` | Aggregated sales pipeline KPIs (counts per stage, conversion rate, pending tasks) | Bearer JWT (`leads:read` / Owner) |
| `GET` | `/api/v1/leads/reasons/` | List standard system lost reasons and gym custom reasons | Bearer JWT (`leads:read` / Owner) |
| `POST` | `/api/v1/leads/reasons/` | Create a new gym-specific custom lost reason | Bearer JWT (`leads:manage` / Owner) |
| `GET` | `/api/v1/leads/{lead_id}/` | Full lead dossier including next moves, notes thread, and fitness goals | Bearer JWT (`leads:read` / Owner) |
| `PATCH` | `/api/v1/leads/{lead_id}/` | Update lead contact info, interested plan, staff assignment, or pipeline stage | Bearer JWT (`leads:manage` / Owner) |
| `DELETE` | `/api/v1/leads/{lead_id}/` | Delete unjoined lead (prevented if converted to member) | Bearer JWT (`leads:manage` / Owner) |
| `POST` | `/api/v1/leads/{lead_id}/next-moves/` | Schedule follow-up action item for lead | Bearer JWT (`leads:manage` / Owner) |
| `PATCH` | `/api/v1/leads/{lead_id}/next-moves/{move_id}/` | Update schedule or mark next move completed | Bearer JWT (`leads:manage` / Owner) |
| `POST` | `/api/v1/leads/{lead_id}/notes/` | Append staff communication note to lead | Bearer JWT (`leads:manage` / Owner) |
| `POST` | `/api/v1/leads/{lead_id}/convert/` | Atomically convert lead into active gym member with plan and onboarding token | Bearer JWT (`leads:manage` / Owner) |

---

## Data Models & Schema Overview

### 1. `leads` (`Lead`)
- `id` (UUID, PK)
- `gym_id` (UUID, FK $\rightarrow$ `gyms`)
- `interested_plan_id` (UUID, FK $\rightarrow$ `membership_plans`, nullable)
- `assigned_staff_id` (UUID, FK $\rightarrow$ `gym_staff_assignments`, nullable)
- `converted_member_id` (UUID, FK $\rightarrow$ `members`, nullable)
- `first_name` (VARCHAR 100, required)
- `last_name` (VARCHAR 100, nullable)
- `phone` (VARCHAR 50, nullable)
- `email` (VARCHAR 255, nullable)
- `stage` (`new`, `contacted`, `visit_trial_booked`, `joined`, `not_joining`)
- `not_joining_reason_standard` (`price`, `location`, `timing`, `chose_another_gym`, `other`, nullable)
- `not_joining_custom_reason_id` (UUID, FK $\rightarrow$ `lead_custom_reasons`, nullable)
- `expected_start_date` (DATE, nullable)
- `source` (`walk_in`, `phone`, `social_media`, `referral`, `website`, `other`)
- `trial_booked_at` (TIMESTAMP, nullable)
- `created_at`, `updated_at` (TIMESTAMP)

### 2. `lead_custom_reasons` (`LeadCustomReasons`)
- `id` (UUID, PK)
- `gym_id` (UUID, FK $\rightarrow$ `gyms`)
- `reason_name` (VARCHAR 255)
- `created_at` (TIMESTAMP)
- Unique Constraint: `(gym_id, reason_name)`

### 3. `lead_fitness_goals` (`LeadFitnessGoals`)
- `id` (UUID, PK)
- `lead_id` (UUID, FK $\rightarrow$ `leads`)
- `goal` (`general_fitness`, `strength`, `muscle_gain`, `weight_loss`, `other`)
- Unique Constraint: `(lead_id, goal)`

### 4. `lead_next_moves` (`LeadNextMove`)
- `id` (UUID, PK)
- `lead_id` (UUID, FK $\rightarrow$ `leads`)
- `scheduled_date` (DATE)
- `short_description` (VARCHAR 255)
- `is_completed` (BOOLEAN, default `false`)
- `created_at` (TIMESTAMP)

### 5. `lead_notes` (`LeadNotes`)
- `id` (UUID, PK)
- `lead_id` (UUID, FK $\rightarrow$ `leads`)
- `author_staff_id` (UUID, FK $\rightarrow$ `gym_staff_assignments`, nullable)
- `note_text` (TEXT)
- `created_at` (TIMESTAMP)

---

## Query Optimization & Database Performance

1. **N+1 Elimination & Prefetching**:
   - `list_leads`: Combines `select_related("assigned_staff__user", "interested_plan", "converted_member", "not_joining_custom_reason")` with `prefetch_related("fitness_goals", "next_moves")`.
   - `get_lead_details`: Performs eager prefetching of `fitness_goals`, `next_moves`, and `notes__author_staff__user` in a single coordinated query set.
2. **Column Projection**:
   - Explicit `.only(...)` projections avoid loading unused or heavy internal fields.
3. **Database Composite Indexes**:
   - `idx_lead_gym_created`: `("gym", "-created_at")`
   - `idx_lead_gym_stage`: `("gym", "stage")`
   - `idx_lead_gym_source`: `("gym", "source")`
   - `idx_lead_gym_staff`: `("gym", "assigned_staff")`
   - `idx_lead_gym_email`: `("gym", "email")`
   - `idx_lead_gym_phone`: `("gym", "phone")`
   - `idx_lead_custom_reason_gym`: `("gym", "reason_name")`
   - `idx_lead_next_move_sched`: `("lead", "is_completed", "scheduled_date")`
4. **Single-Query KPI Aggregation**:
   - `get_lead_metrics` uses conditional aggregation (`Count(Case(When(...)))`) to compute all pipeline funnel metrics across stages in **1 single query**.
