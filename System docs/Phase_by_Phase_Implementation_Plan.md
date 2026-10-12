# Many Gym - Comprehensive Phase-by-Phase Backend Implementation Plan

This document establishes the official engineering roadmap for developing the **Many Gym** multi-tenant backend platform. The system is architected as a **Modular Monolith** (`API` → `Service` → `Selector` → `Model`) managed with **Docker** and aligned with `backend coding standard.md`, `implementation standard.md`, `api documentations.md`, and the database schema (`schema.dbml`).

---

## Architectural Layer Discipline

Each application inside `apps/` strictly enforces layer isolation:

1. **`rest_api/v1/` (`views.py`, `serializers.py`, `urls.py`)**:
   - HTTP protocol management, status codes, query parameter parsing, and response serialization.
   - Request body validation and formatting.
   - **Strict Rule:** Zero database writes, zero complex state transitions, zero direct external SDK calls.

2. **`services.py`**:
   - **Write-side only**.
   - Handles all business workflows, state machines, and multi-model coordination.
   - Enforces atomic database transactions (`@transaction.atomic`).
   - Raises domain-specific exceptions on business rule violations.
   - Triggers background tasks (`tasks.py`) after successful transaction commit.

3. **`selectors.py`**:
   - **Read-side only**.
   - Encapsulates database queries, aggregations, and business metrics.
   - Optimizes ORM fetching (`select_related`, `prefetch_related`) to prevent N+1 queries.
   - Applies tenant scoping (`gym_id`) and contextual filtering.

4. **`models.py`**:
   - Data persistence, schema constraints, field validation invariants, and relational integrity.

5. **`tasks.py`**:
   - Asynchronous execution via Celery workers for non-blocking I/O (emails, media processing, heavy calculations).

6. **`permissions.py`**:
   - Contextual RBAC permission classes verifying user token context (`personal` vs `gym`) and topic scopes.

---

## Phase 0: Dockerized Infrastructure, Development Environment & Orchestration

### Goal
Provide a fully containerized, reproducible development and production environment managing the web API, PostgreSQL database, Redis broker/cache, Celery worker fleet, and Nginx reverse proxy.

### 0.1 Container Topology & Service Stack
- **`web`**: Django 5+ / DRF running on Python 3.12-slim.
  - Development: Gunicorn/runserver with hot-reloading mounted via volume (`.:/app`).
  - Production: Gunicorn with multi-worker configuration.
  - Native packages: `gcc`, `libpq-dev`, `ffmpeg` (for video thumbnail processing), `libmagic`.
- **`db`**: PostgreSQL 16 Alpine.
  - Persistent named volume: `postgres_data`.
  - Extension support: `uuid-ossp` for UUID v4 primary keys.
  - Healthcheck: `pg_isready -U postgres`.
- **`redis`**: Redis 7 Alpine.
  - Dual purpose: Celery message broker (DB 0) and application cache (DB 1).
  - Persistence: Append-Only File (AOF) enabled via volume `redis_data`.
- **`celery_worker`**:
  - Executes asynchronous video processing, image optimization, email dispatches.
  - Shares the `web` codebase and has access to `ffmpeg`.
- **`celery_beat`**:
  - Singleton scheduler managing periodic cron operations (daily subscription expiry reconciliation, lead reminders).
- **`nginx`**:
  - Reverse proxy handling static/media file delivery and SSL termination.
  - Configured with `client_max_body_size 250M` to support video uploads up to 200MB.

### 0.2 Environment & Volume Configuration
- **Environment Files**:
  - `.env.example`: Template documenting all required secrets and configurations.
  - `.env.dev`: Local configuration (`DEBUG=True`, local DB credentials, console email backend).
  - `.env.prod`: Production hardening (`DEBUG=False`, secure secret keys, S3 storage keys).
- **Persistent Volumes**:
  - `postgres_data`: Preserves relational database records across container lifecycles.
  - `redis_data`: Preserves cache and broker states.
  - `media_volume`: Shared storage for uploaded photos and videos mounted across `web`, `celery_worker`, and `nginx`.
  - `static_volume`: Pre-collected CSS, JavaScript, and Swagger UI assets.

### 0.3 Operational CLI Workflows
- Start environment: `docker compose up -d --build`
- Execute migrations: `docker compose exec web python manage.py migrate`
- Create administrator: `docker compose exec web python manage.py createsuperuser`
- Run test suite: `docker compose exec web pytest`
- Inspect Celery logs: `docker compose logs -f celery_worker`

---

## Phase 1: Shared Core, User Authentication & Context-Driven Dynamic RBAC

### Goal
Build shared framework utilities, custom user authentication with a single login account, context-dependent access tokens (switching between Personal Profile and multiple Gyms), and topic-based dynamic role-permission scoping.

### 1.1 Shared Framework Components (`common/`)
- **`common/enums.py`**: Python `TextChoices` for all database enums:
  - `UserStatus`, `TokenContextType`, `StaffStatus`, `GymGenderRequired`, `GymTypeEnum`, `GalleryCategoryEnum`, `AmenityGroupEnum`, `PlanStatusEnum`, `PlanTypeEnum`, `DurationUnitEnum`, `PaymentScheduleEnum`, `MemberJoiningStatus`, `MembershipStatusEnum`, `PaymentStatusEnum`, `PaymentMethodEnum`, `LeadStageEnum`, `NotJoiningReasonStandard`, `LeadSourceEnum`, `FitnessGoalEnum`, `RoutineFormatEnum`, `RoutineLevelEnum`, `PostPrivacyEnum`, `MediaTypeEnum`.
- **`common/exceptions.py`**: Custom domain exceptions (`DomainValidationError`, `UnauthorizedContextError`, `ResourceConflictError`, `PermissionDeniedError`).
- **`common/handlers.py`**: Custom DRF exception handler providing a unified error envelope:
  ```json
  {
    "code": "VALIDATION_ERROR",
    "message": "Specific error explanation.",
    "details": {}
  }
  ```
- **`common/pagination.py`**: `StandardResultsSetPagination` (default: 20, max: 100).
- **`common/middleware.py`**: `GymContextMiddleware` that intercepts JWT headers, validates the `gym_id` claim, and binds `request.gym` and active scopes to the request context.

### 1.2 User Identity & Multi-Tenant Authentication (`apps/users/`, `apps/authentication/`)
- **Data Models**:
  - `User`: Custom user model (`email`, `password_hash`, `first_name`, `last_name`, `phone`, `status`).
  - `UserProfile`: Personal profile (`avatar_url`, `address`, `city`, `country`, `date_of_birth`, `sex`, `nationality`).
  - `AuthToken`: Context-specific token registry (`user_id`, `gym_id`, `token_hash`, `context_type` [personal, gym], `expires_at`).
- **Services (`services.py`)**:
  - `register_user()`: Validates unique email, creates `User` and empty `UserProfile`.
  - `authenticate_user()`: Validates credentials, issues base login session.
  - `issue_context_token()`: Generates JWT signed with specific context claims (`personal` or `gym_id`).
  - `switch_gym_context()`: Verifies the user has an active ownership or staff assignment for the target gym before issuing a gym access token.
  - `revoke_context_tokens()`: Invalidates active tokens upon logout or role revocation.
- **Selectors (`selectors.py`)**:
  - `get_user_profile()`: Retrieves personal user details.
  - `get_accessible_gyms_for_user()`: Queries all gyms where the user is an owner, staff member, trainer, or active member.
- **REST Endpoints (`/api/v1/auth/`)**:
  - `POST /register/` - Register account.
  - `POST /login/` - Initial credential verification.
  - `POST /switch-context/` - Switch to Personal or specific Gym context and receive contextual access token.
  - `POST /logout/` - Invalidate current session token.
  - `GET /me/` - Retrieve personal profile and list of accessible gym contexts.

### 1.3 Dynamic Roles & Topic-Based Permissions (`apps/access_control/`)
- **Data Models**:
  - `Role`: Standard roles (`Administrator`, `Staff`, `Trainer`) and custom roles (`gym_id` nullable, `name`, `slug`, `is_custom`).
  - `Permission`: Scopes organized by topic (`Studio`, `Reports`, `Gym Profile`, `Subscription Plans`, `Members`, `Leads`, `Trainers`, `Routine Templates`, `People & Roles`) with explicit action codes (`members:read`, `members:edit`, `members:delete`, `routine:assign`, etc.).
  - `RolePermission`: Join table linking permissions to roles.
  - `GymStaffAssignment`: Maps users to gyms with assigned roles (`user_id`, `gym_id`, `role_id`, `status` [invited, active, inactive]).
- **Services (`services.py`)**:
  - `create_custom_role()`: Creates a new custom role within a gym and assigns selected permission scopes.
  - `update_custom_role_permissions()`: Modifies permissions associated with a custom role.
  - `invite_staff_member()`: Invites an existing user to join a gym under a designated role.
  - `update_staff_status()`: Activates or deactivates staff members.
  - `remove_staff_assignment()`: Revokes gym access for a staff member.
- **Selectors (`selectors.py`)**:
  - `list_permissions_by_topic()`: Grouped list of all system permissions for UI scope-selection checkboxes.
  - `list_gym_roles()`: Returns standard roles plus gym-specific custom roles.
  - `list_gym_staff()`: Retrieves all staff members, their roles, and invitation states.
  - `user_has_scope()`: Checks if the user's active gym token contains a specific permission code.
- **REST Endpoints (`/api/v1/access-control/`)**:
  - `GET /permissions/` - List all permission scopes grouped by topic.
  - `GET /roles/` - List available roles for the current gym.
  - `POST /roles/` - Create a custom role with selected scopes.
  - `PATCH /roles/{id}/` - Update a custom role's name and scopes.
  - `DELETE /roles/{id}/` - Delete an unused custom role.
  - `GET /staff/` - List gym staff members and assigned roles.
  - `POST /staff/invite/` - Invite a user to the gym with a role.
  - `DELETE /staff/{id}/` - Revoke staff access.

---

## Phase 2: Gym Profile, Multi-Location, Operating Hours, Gallery & Amenities System

### Goal
Provide complete gym profile management across the 5 core tabs (Overview, Location, Opening Hours, Gallery, Amenities), supporting live map pin placement, weekly operating hours, categorized gallery media, and a mutually exclusive amenities engine.

### 2.1 Gym Profile Overview & Location (`apps/gyms/`)
- **Data Models**:
  - `Gym`: Profile details (`name`, `profile_picture_url`, `cover_photo_url`, `short_description` [min 120 chars], `primary_type`, `secondary_type`, `gender_required` [everyone, women_only, men_only], `min_age` [1-99], `timezone`).
  - `GymLocation`: Map and physical location (`address` [editable], `latitude`, `longitude`, `city`, `country`, `postal_code`, `is_primary`).
- **Services (`services.py`)**:
  - `create_gym()`: Initializes new gym workspace, sets creator as owner, assigns default Administrator role, seeds initial opening hours.
  - `update_gym_overview()`: Validates and updates overview fields (enforces description >= 120 characters, validates primary/secondary types).
  - `update_gym_location()`: Saves map pin coordinates (`latitude`, `longitude`) while allowing custom edits to the address string.
- **Selectors (`selectors.py`)**:
  - `get_gym_overview()`: Retrieves gym overview and profile assets.
  - `get_gym_location()`: Retrieves map coordinates and address data.
- **REST Endpoints (`/api/v1/gyms/profile/`)**:
  - `GET /` - Retrieve full gym profile.
  - `PATCH /overview/` - Update overview tab data.
  - `PATCH /location/` - Update location coordinates and editable address.

### 2.2 Operating Hours & Categorized Gallery (`apps/gyms/`)
- **Data Models**:
  - `GymOpeningHours`: Weekly schedule (`day_of_week` [0=Sunday ... 6=Saturday], `start_time`, `end_time`, `is_closed`).
  - `GymGallery`: Multi-asset gallery (`media_url`, `media_type` [picture, video], `category` [General, Equipment, Workout Areas, Studios & Class Spaces, Changing Rooms & Showers, Wellness Facilities, Reception & Lounge, Interior & Decor, Exterior & Entrance, Other], `caption` [up to 200 chars], `order_index`).
- **Services (`services.py`)**:
  - `bulk_update_opening_hours()`: Validates and atomically updates all 7 days of the week.
  - `add_gallery_item()`: Validates file format, sets default category (`General`), stores caption, and assigns sequential `order_index`.
  - `reorder_gallery()`: Bulk updates display positions for gallery items.
  - `delete_gallery_item()`: Removes media item and cleans up physical storage.
- **Selectors (`selectors.py`)**:
  - `get_opening_hours()`: Returns full 7-day operating schedule.
  - `list_gallery_items()`: Retrieves gallery items filtered by category and ordered by `order_index`.
- **REST Endpoints (`/api/v1/gyms/`)**:
  - `GET /opening-hours/` - Get weekly schedule.
  - `PUT /opening-hours/` - Bulk update 7-day opening hours.
  - `GET /gallery/` - List gallery media items (with category filter).
  - `POST /gallery/` - Upload gallery photo or video with caption and category.
  - `PATCH /gallery/reorder/` - Reorder gallery media items.
  - `DELETE /gallery/{id}/` - Delete gallery asset.

### 2.3 Master Catalog & Mutual-Exclusion Amenities Engine (`apps/amenities/`)
- **Data Models**:
  - `AmenityCatalog`: System-wide master catalog categorized into 7 groups (`Changing & Storage`, `Wellness & Recovery`, `Comfort & Convenience`, `Food & Drink`, `Parking & Transport`, `Accessibility`, `Family Facilities`).
  - `GymAmenity`: Gym-level amenities mapping (`gym_id`, `amenity_id`, `is_paid` [boolean], `default_price`). Unique constraint on `(gym_id, amenity_id)`.
- **Services (`services.py`)**:
  - `sync_gym_amenities()`: Synchronizes free vs. paid amenity selections.
    - **Business Invariant:** An amenity cannot be both free and paid simultaneously. If an amenity is marked paid, it is automatically removed/deactivated from free selections.
- **Selectors (`selectors.py`)**:
  - `get_master_catalog()`: Returns all catalog amenities grouped by domain.
  - `get_gym_configured_amenities()`: Returns gym's configured free amenities and paid amenities.
- **REST Endpoints (`/api/v1/amenities/`)**:
  - `GET /catalog/` - List master catalog amenities by group.
  - `GET /gym-amenities/` - List current gym's configured free and paid amenities.
  - `PUT /gym-amenities/sync/` - Bulk synchronize free and paid selections with mutual-exclusion checks.

---

## Phase 3: Membership Plans & Dynamic Pricing Engine

### Goal
Implement the 5-step membership plan creation lifecycle, supporting time-based vs session-based billing, payment schedules (full payment vs installments), included amenity bundles, and status transitions.

### 3.1 Membership Plans & Inclusions (`apps/memberships/`)
- **Data Models**:
  - `MembershipPlan`: Plan definition entity:
    - Step 1 (Basic Info): `name`, `description` (min 50 chars, optional), `plan_status` (`draft`, `active`, `archived`).
    - Step 2 (Plan Type): `plan_type` (`time_based`, `session_based`), `price`, `duration_value`, `duration_unit` (`day`, `week`, `month`, `session`).
    - Step 3 (Payments): `joining_fee`, `payment_schedule` (`full_payment`, `instalments`), `installment_schedule_config` (JSONB).
    - Step 4 (Inclusions): Linked via `PlanIncludedAmenities`.
    - Step 5 (Terms): `cancellation_policy`, `refund_policy`.
  - `PlanIncludedAmenities`: Join table mapping plan to included free and paid `GymAmenity` records.
- **Services (`services.py`)**:
  - `create_membership_plan()`: Validates multi-step configuration, enforces min 50 characters on description if provided, links included amenities.
  - `update_membership_plan()`: Updates plan parameters.
    - **Business Invariant:** If active member subscriptions are attached to the plan, pricing and duration fields are locked against breaking changes.
  - `set_plan_status()`: Manages state machine transitions (`draft` → `active` ↔ `archived`).
  - `sync_plan_amenities()`: Updates the list of included free and paid amenities for a plan.
- **Selectors (`selectors.py`)**:
  - `list_gym_plans()`: Lists plans filtered by status (`draft`, `active`, `archived`) and type (`time_based`, `session_based`).
  - `get_plan_details()`: Retrieves complete 5-step plan details with bundled amenities and subscriber metrics.
- **REST Endpoints (`/api/v1/plans/`)**:
  - `GET /` - List gym membership plans with filters.
  - `POST /` - Create membership plan (multi-step payload).
  - `GET /{id}/` - Detailed plan view including amenity inclusions.
  - `PATCH /{id}/` - Update plan details.
  - `POST /{id}/status/` - Transition plan status (Draft / Active / Archived).

---

## Phase 4: Member Lifecycle, Subscriptions & Payment Transactions

### Goal
Build the member directory, member invitation and onboarding workflows, subscription calculation engine (time-based automated expiration vs session packs), extra paid amenities, and payment logging.

### 4.1 Member Directory & Profile Management (`apps/members/`)
- **Data Models**:
  - `Member`: Core member record (`gym_id`, `user_id` [nullable until account link], `assigned_trainer_id`, `first_name`, `last_name`, `email`, `phone`, `profile_photo_url`, `address`, `city`, `country`, `date_of_birth`, `sex`, `nationality`, `emergency_contact_name`, `emergency_contact_phone`, `emergency_contact_relationship`, `joining_status` [`sent_invitation`, `joined`], `internal_notes`).
- **Services (`services.py`)**:
  - `create_member()`: Creates member record with default `joining_status = 'sent_invitation'`. Generates onboarding verification token and triggers invitation email via Celery.
  - `accept_member_invitation()`: Links a registered `User` account to the `Member` record, transitioning status to `joined`.
  - `update_member_profile()`: Updates demographic, emergency contact, or trainer assignment details.
- **Selectors (`selectors.py`)**:
  - `list_members()`: Returns member directory with computed columns: Full Name, Current Plan, Membership Status, Payment Status, Expiry Date, Assigned Trainer, Joining Status.
  - `get_member_detail()`: Full member dossier including subscription history, assigned routine, payments, and notes.
- **REST Endpoints (`/api/v1/members/`)**:
  - `GET /` - List members with search, filters (status, payment, trainer), and pagination.
  - `POST /` - Create new member and initialize subscription and onboarding invitation.
  - `GET /{id}/` - Retrieve single member dossier.
  - `PATCH /{id}/` - Update member information or trainer assignment.
  - `POST /{id}/resend-invitation/` - Re-dispatch onboarding invitation email.

### 4.2 Subscriptions, Extra Amenities & Payment Transactions (`apps/subscriptions/`, `apps/payments/`)
- **Data Models**:
  - `MemberSubscription`: Active/past membership contract (`member_id`, `plan_id`, `membership_status` [`scheduled`, `active`, `paused`, `expired`, `cancelled`], `payment_status` [`fully_paid`, `partially_paid`, `unpaid`], `start_date`, `end_date`, `total_sessions`, `remaining_sessions`).
  - `MemberExtraAmenities`: Subscriptions to extra paid amenities not included in base plan (`member_subscription_id`, `gym_amenity_id`, `extra_fee`, `is_active`).
  - `MemberPayment`: Payment transaction record (`member_subscription_id`, `amount`, `payment_method` [`cash`, `credit_card`, `debit_card`, `bank_transfer`, `mobile_pay`, `other`], `payment_date`, `is_initial_payment`, `notes`).
- **Services (`services.py`)**:
  - `create_member_subscription()`:
    - **Time-Based Plans:** Computes `end_date` automatically from `start_date` + `duration_value` * `duration_unit` within the gym's timezone.
    - **Session-Based Plans:** Applies admin-selected expiration date and initializes `total_sessions` and `remaining_sessions`.
  - `record_member_payment()`: Records received amount and automatically calculates `payment_status` (`fully_paid`, `partially_paid`, `unpaid`).
  - `attach_extra_amenity()`: Subscribes member to additional paid amenities (e.g. personal locker, sauna).
  - `transition_membership_status()`: Handles pausing, resuming, or cancelling subscriptions.
- **Selectors (`selectors.py`)**:
  - `get_active_subscription()`: Retrieves member's current active plan, session balance, and payment standing.
  - `list_member_payments()`: Retrieves payment transaction ledger for a subscription.
- **REST Endpoints (`/api/v1/members/{member_id}/subscriptions/`, `/api/v1/payments/`)**:
  - `POST /` - Attach new subscription to member.
  - `PATCH /{id}/status/` - Pause, cancel, or resume subscription.
  - `POST /{id}/payments/` - Log a payment transaction.
  - `POST /{id}/extra-amenities/` - Attach extra paid amenities.

---

## Phase 5: Leads CRM, Pipeline Tracking & Conversion Funnel

### Goal
Provide sales pipeline management, capturing prospective leads, tracking stage transitions, recording lost reasons with custom gym-level taxonomies, scheduling next moves, and enabling atomic conversion of leads to active gym members.

### 5.1 Lead Lifecycle & Interactions (`apps/leads/`)
- **Data Models**:
  - `Lead`: Lead entity (`first_name`, `last_name`, `phone`, `email` [at least one required], `interested_plan_id`, `stage` [`new`, `contacted`, `visit_trial_booked`, `joined`, `not_joining`], `not_joining_reason_standard` [`price`, `location`, `timing`, `chose_another_gym`, `other`], `not_joining_custom_reason_id`, `expected_start_date`, `source` [`walk_in`, `phone`, `social_media`, `referral`, `website`, `other`], `assigned_staff_id`, `trial_booked_at`, `converted_member_id`).
  - `LeadCustomReasons`: Gym-specific custom reasons when `not_joining_reason` is set to `Other`.
  - `LeadFitnessGoals`: Multi-select goals (`general_fitness`, `strength`, `muscle_gain`, `weight_loss`, `other`).
  - `LeadNextMove`: Action items (`lead_id`, `scheduled_date`, `short_description`, `is_completed`).
  - `LeadNotes`: Internal staff notes thread.
- **Services (`services.py`)**:
  - `create_lead()`: Validates contact details (ensures phone or email is provided), attaches fitness goals, assigns staff member.
  - `update_lead_stage()`: Transitions lead across pipeline stages.
    - **Business Invariant:** If stage is changed to `not_joining`, a standard reason or a custom gym reason must be provided.
  - `create_custom_reason()`: Allows gym admin to define custom lost reasons for future reuse.
  - `schedule_next_move()`: Adds action item with scheduled date and short description.
  - `complete_next_move()`: Marks action item as resolved.
  - `add_lead_note()`: Appends internal text note to the lead's history.
  - `convert_lead_to_member()`:
    - Atomically creates a `Member` record populated with the lead's details.
    - Associates the selected membership plan and starts the onboarding invitation workflow.
    - Updates lead `stage = 'joined'` and records `converted_member_id`.
- **Selectors (`selectors.py`)**:
  - `list_leads()`: Retrieves leads filtered by stage, source, assigned staff, and text search.
  - `get_lead_details()`: Retrieves lead dossier including next move history, fitness goals, and notes.
  - `list_custom_reasons()`: Returns gym's configured custom lost reasons.
- **REST Endpoints (`/api/v1/leads/`)**:
  - `GET /` - List leads with filters, search, and pagination.
  - `POST /` - Create a new lead.
  - `GET /{id}/` - Retrieve full lead details.
  - `PATCH /{id}/` - Update lead fields or stage.
  - `POST /{id}/next-moves/` - Add scheduled next move.
  - `PATCH /{id}/next-moves/{move_id}/` - Mark next move completed.
  - `POST /{id}/notes/` - Add internal note.
  - `POST /{id}/convert/` - Convert lead to active gym member.
  - `GET /reasons/` - List standard and gym-specific custom lost reasons.
  - `POST /reasons/` - Create a custom lost reason.

---

## Phase 6: Routine Templates & Workout Prescription Engine

### Goal
Implement reusable routine templates in both Weekly and Session-based formats, exercise structures, trainer-to-member routine prescription, and individual member routine customizations.

### 6.1 Routine Templates (`apps/routines/`)
- **Data Models**:
  - `RoutineTemplate`: Template header (`template_name`, `routine_format` [`weekly`, `session_based`], `level` [`beginner`, `intermediate`, `advanced`], `notes`).
  - `RoutineTemplateGoal`: Multi-select template fitness goals (`general_fitness`, `muscle_gain`, `weight_loss`, `strength`, `other`).
  - `RoutineTemplateDay`: Day container.
    - Weekly: `day_of_week` (1-7), `is_rest_day`, `workout_title`, `workday_note`.
    - Session-based: `session_number` (1, 2, 3...), workout title, workday note.
  - `RoutineTemplateExercise`: Exercise item (`exercise_name`, `sets` [optional for cardio], `reps_or_duration`, `rest_seconds`, `notes`, `sort_order`).
- **Services (`services.py`)**:
  - `create_routine_template()`: Validates format rules (weekly vs. session-based) and atomically creates nested days/sessions and exercises.
  - `update_routine_template()`: Updates template metadata, days, or exercises.
  - `delete_routine_template()`: Removes template if not actively linked to member routines.
- **Selectors (`selectors.py`)**:
  - `list_routine_templates()`: Filters templates by level, format, and fitness goals.
  - `get_routine_template_detail()`: Retrieves full template breakdown with days/sessions and exercises.
- **REST Endpoints (`/api/v1/routine-templates/`)**:
  - `GET /` - List routine templates.
  - `POST /` - Create routine template with nested days and exercises.
  - `GET /{id}/` - Routine template details.
  - `PUT /{id}/` - Full update of template and exercise layout.
  - `DELETE /{id}/` - Delete routine template.

### 6.2 Member Routine Prescription (`apps/routines/`)
- **Data Models**:
  - `MemberRoutine`: Assigned member routine (`member_id`, `source_template_id` [nullable], `prescribed_by_staff_id`, `routine_name`, `routine_format`, `level`, `is_active`, `assigned_at`).
  - `MemberRoutineDay`: Member routine day layout.
  - `MemberRoutineExercise`: Member exercise layout allowing trainer customization per member.
- **Services (`services.py`)**:
  - `assign_routine_to_member()`: Clones template structure into member-specific routine tables or initializes empty custom structure.
  - `customize_member_routine()`: Allows assigned trainer to adjust exercises, sets, reps, or notes specifically for that member.
- **Selectors (`selectors.py`)**:
  - `get_member_active_routine()`: Retrieves member's current active routine with exercises.
  - `list_member_routine_history()`: Lists previously completed routines for a member.
- **REST Endpoints (`/api/v1/members/{member_id}/routines/`)**:
  - `GET /` - List active routine and history for member.
  - `POST /assign/` - Assign template or create custom routine for member.
  - `PATCH /{routine_id}/` - Update/customize member routine specifications.

---

## Phase 7: Community Feed, Social Posts & Asynchronous Media Pipeline

### Goal
Provide gym community social updates, multi-media uploads with format and size validation, background video thumbnailing, and member visibility privacy controls.

### 7.1 Posts & Media Handling (`apps/posts/`)
- **Data Models**:
  - `GymPost`: Post entity (`gym_id`, `author_user_id`, `content_text` [optional if media exists], `privacy` [`public`, `members_only`], `published_at`).
  - `GymPostMedia`: Media attachments (`media_url`, `media_type` [`picture`, `video`], `thumbnail_url`, `file_size_bytes`, `order_index`).
- **Services (`services.py`)**:
  - `create_post()`: Enforces business rule: text is required unless media is attached. Validates uploaded files, assigns display order, triggers asynchronous media tasks.
  - `validate_media_file()`: Enforces file constraints:
    - Pictures: Max 10MB; formats: JPG, JPEG, PNG, WEBP.
    - Videos: Max 200MB; formats: MP4, MOV.
  - `update_video_thumbnail()`: Allows admin to replace the auto-generated video thumbnail with a custom image.
  - `delete_post()`: Removes post and triggers storage cleanup for media attachments.
- **Celery Tasks (`tasks.py`)**:
  - `generate_video_thumbnail_task`: Asynchronously extracts a representative frame from the video using `ffmpeg` and stores the thumbnail image.
  - `optimize_post_image_task`: Compresses uploaded images for web delivery.
- **Selectors (`selectors.py`)**:
  - `list_gym_feed()`: Retrieves posts ordered by `published_at DESC`. Filters by visibility (`public` for anonymous/guest users; `public` + `members_only` for verified members and staff).
- **REST Endpoints (`/api/v1/posts/`)**:
  - `GET /` - List posts for gym community feed.
  - `POST /` - Create post with text and media references.
  - `PATCH /{id}/` - Update post text or privacy.
  - `DELETE /{id}/` - Delete post and associated media.
  - `PATCH /{id}/media/{media_id}/thumbnail/` - Upload custom video thumbnail.

---

## Phase 8: Gym Studio Reports, Analytics & Executive Dashboard

### Goal
Deliver high-performance aggregation selectors and management dashboard metrics for gym owners, staff, and trainers.

### 8.1 Analytics Selectors (`apps/reports/`, `apps/dashboard/`)
- **Selectors (`selectors.py`)**:
  - `get_dashboard_summary()`: Computes headline metrics:
    - Total Active Members
    - Expiring Memberships (next 7 and 30 days)
    - New Leads this week
    - Pending Next Moves due today
    - Today's Scheduled Visits / Trials
  - `get_revenue_report()`: Aggregates total payments, breakdown by payment method, and subscription plan distribution over specified date ranges.
  - `get_lead_funnel_report()`: Computes conversion rates from New → Trial → Joined, drop-off percentages, and lost-reason distributions.
  - `get_trainer_workload_report()`: Active member counts and assigned routine counts per trainer.
- **REST Endpoints (`/api/v1/dashboard/`, `/api/v1/reports/`)**:
  - `GET /dashboard/summary/` - Management overview summary cards.
  - `GET /reports/revenue/` - Revenue and payment collections report.
  - `GET /reports/membership-growth/` - Member acquisition and churn metrics.
  - `GET /reports/leads-funnel/` - Lead conversion performance report.
  - `GET /reports/trainer-workload/` - Trainer assignments and workload report.

---

## Phase 9: Automated Background Tasks & Lifecycle Maintenance

### Goal
Implement asynchronous background workers, email dispatches, and periodic Celery Beat crons for automated membership status reconciliation and lead follow-up alerts.

### 9.1 Background Jobs & Crons (`tasks.py`)
- **Celery Workers & Tasks**:
  - `send_member_invitation_email_task`: Sends verification link upon member creation.
  - `send_subscription_expiry_reminder_task` (Daily Cron): Queries subscriptions expiring in 7 days and 1 day; dispatches reminder notifications.
  - `reconcile_expired_subscriptions_task` (Daily Cron): Atomically updates active subscriptions where `end_date < today()` to `expired`.
  - `send_lead_followup_reminder_task` (Daily Cron): Notifies staff members of uncompleted `Next Move` items scheduled for today.
  - `cleanup_expired_tokens_task` (Nightly Cron): Purges expired contextual `AuthToken` records.

---

## Complete Phase Dependency & Execution Order

```text
Phase 0: Docker Infrastructure & Service Orchestration
  │
Phase 1: Shared Core, User Auth & Dynamic RBAC
  │
Phase 2: Gym Profile, Location, Gallery & Amenities
  │
Phase 3: Membership Plans & Dynamic Pricing Engine
  │
Phase 4: Member Lifecycle, Subscriptions & Payments
  │
  ├──► Phase 5: Leads CRM & Funnel Conversion
  │
  ├──► Phase 6: Routine Templates & Workout Prescription
  │
Phase 7: Community Feed & Media Processing Pipeline
  │
Phase 8: Studio Reports, Analytics & Dashboard
  │
Phase 9: Automated Background Workers & Scheduled Crons
```

---

## Phase Completion Verification Checklist

Each phase must satisfy all seven criteria before being marked complete:
1. **Database Schema & Migrations**: Schema migrations verified and applied cleanly in the `db` container.
2. **Layer Separation**: Zero business logic in views; all writes in `services.py`; all reads in `selectors.py`.
3. **Multi-Tenant Isolation**: Queries strictly scoped by active `gym_id` from contextual tokens.
4. **Standardized Responses & Errors**: All API responses use the standard envelope and custom error handler.
5. **Role & Permission Enforcement**: Action codes and topic scopes enforced via DRF permission classes.
6. **Automated Test Coverage**: Unit tests for services and integration tests for API endpoints executed via `pytest`.
7. **API Documentation**: OpenAPI / Swagger documentation updated with real request/response payloads and error examples.
