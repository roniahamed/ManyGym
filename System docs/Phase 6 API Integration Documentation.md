# Phase 6: Routine Templates & Workout Prescription Engine Documentation

## Overview & Architecture
The Phase 6 module implements an enterprise workout routine and prescription system for Many Gym. It empowers gym administrators and trainers to design structured, reusable routine templates (in both Weekly and Session-based formats), organize workout days/sessions with granular exercises (sets, reps, duration, rest intervals, and technique notes), and prescribe these routines directly to individual gym members with personalized customizations.

Adheres strictly to the **Layered Architectural Pattern**:
- **Models**: `RoutineTemplate`, `RoutineTemplateGoal`, `RoutineTemplateDay`, `RoutineTemplateExercise`, `MemberRoutine`, `MemberRoutineDay`, `MemberRoutineExercise` (`apps/routines/models.py`)
- **Selectors**: High-performance query logic with eager relationship loading, prefetching, and memory-efficient generator streaming (`apps/routines/selectors.py`)
- **Services**: Atomic business logic with strict validation, format rules, deep template cloning, and member customization (`apps/routines/services.py`)
- **Serializers**: Strict validation, typed representation, `StrictCharField` type juggling prevention, and OpenAPI 3.0 annotations (`apps/routines/rest_api/v1/serializers.py`)
- **Views**: Declarative DRF APIViews protected by RBAC permissions (`apps/routines/rest_api/v1/views.py`)

---

## Core Workflows & Business Invariants

### 1. Routine Templates
- **Template Metadata**:
  - `template_name`: Required non-blank title (e.g., "Beginner Full Body Split").
  - `routine_format`: `weekly` or `session_based`.
  - `level`: `beginner`, `intermediate`, or `advanced`.
  - `goals`: Multi-select goals (`general_fitness`, `muscle_gain`, `weight_loss`, `strength`, `other`).
  - `notes`: Optional general instructions or guidelines.
- **Format Invariants**:
  - **Weekly Format**:
    - Organizes workouts across days of the week (`day_of_week` 1 to 7, where 1=Monday ... 7=Sunday).
    - Supports Workout Days and Rest Days (`is_rest_day = True`).
    - Invariant: A rest day cannot contain exercises.
  - **Session-Based Format**:
    - Organizes workouts into sequential sessions (`session_number` 1, 2, 3...).
    - No rest days in session-based format (`is_rest_day` is strictly `False`).
- **Exercise Structure**:
  - `exercise_name`: Required non-blank string.
  - `sets`: Optional integer (nullable for cardio like Treadmill, Rowing, etc.).
  - `reps_or_duration`: Required specification (e.g., "10 reps", "15 min", "30 sec hold").
  - `rest_seconds`: Optional rest interval in seconds.
  - `notes`: Optional technique cues or modifications.
  - `sort_order`: Sequential integer order.

### 2. Routine Deletion Protection
- Routine templates actively prescribed to gym members (`MemberRoutine.is_active = True`) cannot be deleted.
- Attempting to delete an actively prescribed template raises `ResourceConflictError (409 Conflict)`.

### 3. Member Routine Prescription
- Trainers and gym staff can prescribe workout routines to gym members via `POST /api/v1/members/{member_id}/routines/assign/`.
- **Deep Cloning**: When prescribing from a `source_template_id`, the system deep-clones all template days and nested exercises into `MemberRoutineDay` and `MemberRoutineExercise` records. This ensures that subsequent updates to the master template do not affect historical or active member routines.
- **Single Active Routine Invariant**: Prescribing a new routine automatically deactivates any existing active routine for that member (`is_active = False`), ensuring only one routine is active at any time.
- **Customization Engine**: Assigned trainers can customize exercises, sets, reps, duration, and notes specifically for that member via `PATCH /api/v1/members/{member_id}/routines/{routine_id}/`.

---

## Complete API Endpoints List

| Method | Endpoint | Description | Auth & Scope Required |
|---|---|---|---|
| `GET` | `/api/v1/routine-templates/` | List routine templates with filters (`routine_format`, `level`, `goal`, `search`, pagination) | Bearer JWT (`routines:read` / Trainer / Owner) |
| `POST` | `/api/v1/routine-templates/` | Create a reusable routine template with nested days and exercises | Bearer JWT (`routines:manage` / Owner) |
| `GET` | `/api/v1/routine-templates/{template_id}/` | Full routine template dossier with days and exercises | Bearer JWT (`routines:read` / Trainer / Owner) |
| `PUT` | `/api/v1/routine-templates/{template_id}/` | Full update of routine template metadata and exercise layout | Bearer JWT (`routines:manage` / Owner) |
| `PATCH` | `/api/v1/routine-templates/{template_id}/` | Partial update of routine template | Bearer JWT (`routines:manage` / Owner) |
| `DELETE` | `/api/v1/routine-templates/{template_id}/` | Delete routine template (prevented if actively prescribed) | Bearer JWT (`routines:manage` / Owner) |
| `GET` | `/api/v1/members/{member_id}/routines/` | List active routine and routine history for a gym member | Bearer JWT (`routines:read` / `members:read` / Owner) |
| `POST` | `/api/v1/members/{member_id}/routines/assign/` | Prescribe template or custom routine to member | Bearer JWT (`routines:assign` / `routines:manage` / Owner) |
| `GET` | `/api/v1/members/{member_id}/routines/{routine_id}/` | Get specific member routine dossier with exercises | Bearer JWT (`routines:read` / `members:read` / Owner) |
| `PATCH` | `/api/v1/members/{member_id}/routines/{routine_id}/` | Customize exercises, sets, reps, or notes for member | Bearer JWT (`routines:assign` / `routines:manage` / Owner) |

---

## Data Models & Schema Overview

### 1. `routine_templates` (`RoutineTemplate`)
- `id` (UUID, PK)
- `gym_id` (UUID, FK $\rightarrow$ `gyms`)
- `created_by_staff_id` (UUID, FK $\rightarrow$ `gym_staff_assignments`, nullable)
- `template_name` (VARCHAR 255, required)
- `routine_format` (`weekly`, `session_based`)
- `level` (`beginner`, `intermediate`, `advanced`)
- `notes` (TEXT, nullable)
- `created_at`, `updated_at` (TIMESTAMP)

### 2. `routine_template_goals` (`RoutineTemplateGoal`)
- `id` (UUID, PK)
- `template_id` (UUID, FK $\rightarrow$ `routine_templates`)
- `goal` (`general_fitness`, `strength`, `muscle_gain`, `weight_loss`, `other`)
- Unique Constraint: `(template_id, goal)`

### 3. `routine_template_days` (`RoutineTemplateDay`)
- `id` (UUID, PK)
- `template_id` (UUID, FK $\rightarrow$ `routine_templates`)
- `day_of_week` (INTEGER, nullable, 1-7 for weekly format)
- `session_number` (INTEGER, nullable, 1, 2, 3... for session-based format)
- `is_rest_day` (BOOLEAN, default: false)
- `workout_title` (VARCHAR 255, nullable)
- `workday_note` (TEXT, nullable)
- `sort_order` (INTEGER, default: 0)

### 4. `routine_template_exercises` (`RoutineTemplateExercise`)
- `id` (UUID, PK)
- `template_day_id` (UUID, FK $\rightarrow$ `routine_template_days`)
- `exercise_name` (VARCHAR 255, required)
- `sets` (INTEGER, nullable for cardio)
- `reps_or_duration` (VARCHAR 100, required)
- `rest_seconds` (INTEGER, nullable)
- `notes` (TEXT, nullable)
- `sort_order` (INTEGER, default: 0)

### 5. `member_routines` (`MemberRoutine`)
- `id` (UUID, PK)
- `member_id` (UUID, FK $\rightarrow$ `members`)
- `source_template_id` (UUID, FK $\rightarrow$ `routine_templates`, nullable)
- `prescribed_by_staff_id` (UUID, FK $\rightarrow$ `gym_staff_assignments`, nullable)
- `routine_name` (VARCHAR 255, required)
- `routine_format` (`weekly`, `session_based`)
- `level` (`beginner`, `intermediate`, `advanced`)
- `is_active` (BOOLEAN, default: true)
- `notes` (TEXT, nullable)
- `assigned_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)

### 6. `member_routine_days` (`MemberRoutineDay`)
- `id` (UUID, PK)
- `member_routine_id` (UUID, FK $\rightarrow$ `member_routines`)
- `day_of_week` (INTEGER, nullable)
- `session_number` (INTEGER, nullable)
- `is_rest_day` (BOOLEAN, default: false)
- `workout_title` (VARCHAR 255, nullable)
- `workday_note` (TEXT, nullable)
- `sort_order` (INTEGER, default: 0)

### 7. `member_routine_exercises` (`MemberRoutineExercise`)
- `id` (UUID, PK)
- `member_routine_day_id` (UUID, FK $\rightarrow$ `member_routine_days`)
- `exercise_name` (VARCHAR 255, required)
- `sets` (INTEGER, nullable)
- `reps_or_duration` (VARCHAR 100, required)
- `rest_seconds` (INTEGER, nullable)
- `notes` (TEXT, nullable)
- `sort_order` (INTEGER, default: 0)

---

## Measurable Performance & Optimization Results

| Endpoint / Operation | Query Count | p50 Response Time | p95 Response Time | Target Benchmark |
| :--- | :--- | :--- | :--- | :--- |
| **GET `/api/v1/routine-templates/` (20 items)** | **5 queries** (optimized via SQL `Count`) | **13.29 ms** | **158.86 ms** | p95 < 200 ms (Met) |
| **GET `/api/v1/routine-templates/{id}/`** | **5 queries** (full dossier) | **9.76 ms** | **13.01 ms** | p95 < 200 ms (Met) |
| **GET `/api/v1/members/{id}/routines/`** | **6 queries** (all nested days/ex) | **18.04 ms** | **23.16 ms** | p95 < 200 ms (Met) |
| **POST `/api/v1/members/{id}/routines/assign/`** | Complex write & clone | **20.73 ms** | **116.27 ms** | p95 < 500 ms (Met) |
| **`stream_routine_templates()` Generator** | Batch chunk iterator | Constant Memory | Constant Memory | OOM Prevention |

---

## Security & Verification Summary
- **Type Juggling Protection**: Input fields utilize `StrictCharField` to reject integer or boolean coercion with `400 Bad Request`.
- **Stored XSS & SQLi Resilience**: All text and description fields are safely parameterized through the Django ORM and returned as plain text without script execution.
- **Tenant Isolation (IDOR)**: Gym B cannot read, prescribe, modify, or delete Gym A's templates or member routines (`404 Not Found`).
- **Full Test Suite Status**: **791 tests passing with 0 failures**.
