from django.db import transaction
from django.utils.text import slugify
from apps.access_control.models import Permission, Role, RolePermission, GymStaffAssignment
from apps.gyms.models import Gym
from apps.users.models import User
from common.exceptions import (
    DomainValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.enums import StaffStatus

# System default permission definitions across the 9 core topics
DEFAULT_PERMISSIONS_DEFINITION = [
    # Topic 1: Studio
    {"topic": "Studio", "scope_code": "studio:read", "name": "View Studio", "description": "Access to view studio classes and schedules."},
    {"topic": "Studio", "scope_code": "studio:manage", "name": "Manage Studio", "description": "Ability to create, edit, or cancel studio classes."},

    # Topic 2: Reports
    {"topic": "Reports", "scope_code": "reports:read", "name": "View Reports", "description": "Access gym financial, membership, and attendance reports."},

    # Topic 3: Gym Profile
    {"topic": "Gym Profile", "scope_code": "gym_profile:read", "name": "View Gym Profile", "description": "View gym details, hours, gallery, and amenities."},
    {"topic": "Gym Profile", "scope_code": "gym_profile:edit", "name": "Edit Gym Profile", "description": "Edit overview, location, gallery, and amenities."},

    # Topic 4: Subscription Plans
    {"topic": "Subscription Plans", "scope_code": "plans:read", "name": "View Plans", "description": "View gym membership plans and pricing packages."},
    {"topic": "Subscription Plans", "scope_code": "plans:manage", "name": "Manage Plans", "description": "Create, archive, or edit membership plans and packages."},

    # Topic 5: Members
    {"topic": "Members", "scope_code": "members:read", "name": "View Members", "description": "Read member directory and member details."},
    {"topic": "Members", "scope_code": "members:edit", "name": "Edit Members", "description": "Edit member profile, status, or subscription."},
    {"topic": "Members", "scope_code": "members:delete", "name": "Delete Members", "description": "Remove or cancel gym members."},

    # Topic 6: Leads
    {"topic": "Leads", "scope_code": "leads:read", "name": "View Leads", "description": "View sales pipeline, inquiries, and prospective members."},
    {"topic": "Leads", "scope_code": "leads:manage", "name": "Manage Leads", "description": "Update lead stages, notes, and trial bookings."},

    # Topic 7: Trainers
    {"topic": "Trainers", "scope_code": "trainers:read", "name": "View Trainers", "description": "View list of trainers and assigned schedules."},
    {"topic": "Trainers", "scope_code": "trainers:manage", "name": "Manage Trainers", "description": "Assign clients and manage trainer allocations."},

    # Topic 8: Routine Templates
    {"topic": "Routine Templates", "scope_code": "routines:read", "name": "View Routines", "description": "View workout routines and exercise templates."},
    {"topic": "Routine Templates", "scope_code": "routines:assign", "name": "Assign Routines", "description": "Assign routines to gym members."},
    {"topic": "Routine Templates", "scope_code": "routines:manage", "name": "Manage Routine Templates", "description": "Create and modify gym routine templates."},

    # Topic 9: People & Roles
    {"topic": "People & Roles", "scope_code": "people_roles:read", "name": "View Staff & Roles", "description": "View staff assignments and role scopes."},
    {"topic": "People & Roles", "scope_code": "people_roles:manage", "name": "Manage Staff & Roles", "description": "Invite staff, manage custom roles, and assign scopes."},

    # Topic 10: Community Posts & Feed
    {"topic": "Community", "scope_code": "posts:read", "name": "View Community Posts", "description": "Access to view gym community feed and posts."},
    {"topic": "Community", "scope_code": "posts:manage", "name": "Manage Community Posts", "description": "Create, edit, or delete gym community posts and media."},

    # Topic 11: Messaging & Direct Communication
    {"topic": "Messaging", "scope_code": "messaging:read", "name": "View Gym Messages", "description": "Access to view gym conversations and messages."},
    {"topic": "Messaging", "scope_code": "messaging:send", "name": "Send Gym Messages", "description": "Ability to send messages on behalf of the gym."},

    # Topic 12: Alerts & Logs
    {"topic": "Alerts & Logs", "scope_code": "admin_logs:read", "name": "View Admin Logs", "description": "Access to view gym administrative activity and audit logs."},
]


@transaction.atomic
def seed_default_permissions_and_roles() -> None:
    """
    Seeds system permissions and standard roles (Administrator, Staff, Trainer).
    Idempotent execution.
    """
    perm_objs = {}
    for p_data in DEFAULT_PERMISSIONS_DEFINITION:
        obj, _ = Permission.objects.update_or_create(
            scope_code=p_data["scope_code"],
            defaults={
                "topic": p_data["topic"],
                "name": p_data["name"],
                "description": p_data["description"],
            },
        )
        perm_objs[p_data["scope_code"]] = obj

    # 1. Administrator: All permissions
    admin_role, _ = Role.objects.get_or_create(
        gym=None,
        slug="administrator",
        defaults={
            "name": "Administrator",
            "is_custom": False,
            "description": "Full administrative control over all gym operations.",
        },
    )
    admin_role.permissions.set(perm_objs.values())

    # 2. Staff: Operational scopes
    staff_scopes = [
        "studio:read", "reports:read", "gym_profile:read",
        "plans:read", "members:read", "members:edit",
        "leads:read", "leads:manage", "trainers:read",
        "routines:read", "people_roles:read",
        "posts:read", "posts:manage", "admin_logs:read",
    ]
    staff_role, _ = Role.objects.get_or_create(
        gym=None,
        slug="staff",
        defaults={
            "name": "Staff",
            "is_custom": False,
            "description": "Standard operational staff member with day-to-day access.",
        },
    )
    staff_role.permissions.set([perm_objs[s] for s in staff_scopes if s in perm_objs])

    # 3. Trainer: Member and routine-related access
    trainer_scopes = [
        "members:read", "trainers:read",
        "routines:read", "routines:assign", "routines:manage",
        "posts:read", "posts:manage",
    ]
    trainer_role, _ = Role.objects.get_or_create(
        gym=None,
        slug="trainer",
        defaults={
            "name": "Trainer",
            "is_custom": False,
            "description": "Fitness trainer with workout routine and assigned member access.",
        },
    )
    trainer_role.permissions.set([perm_objs[s] for s in trainer_scopes if s in perm_objs])


@transaction.atomic
def create_custom_role(gym: Gym, name: str, description: str = None, permission_ids: list = None) -> Role:
    """
    Creates a new custom role scoped to a specific gym with selected permissions.
    """
    slug = slugify(name)
    if Role.objects.filter(gym=gym, slug=slug).exists():
        raise ResourceConflictError(f"A role with the name '{name}' already exists in this gym.")

    role = Role.objects.create(
        gym=gym,
        name=name.strip(),
        slug=slug,
        is_custom=True,
        description=description.strip() if description else None,
    )

    if permission_ids:
        perms = Permission.objects.filter(id__in=permission_ids)
        role.permissions.set(perms)

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Created a custom role",
            action_type=AdminLogActionType.CREATE_ROLE,
            details=f"Created custom role '{role.name}'",
            category=AdminLogCategory.ACCESS_CONTROL,
            target_type="role",
            target_id=str(role.id),
        )
    except Exception:
        pass

    return role


@transaction.atomic
def update_custom_role(role: Role, name: str = None, description: str = None, permission_ids: list = None) -> Role:
    """
    Updates custom role details and scope permissions.
    """
    if not role.is_custom:
        raise DomainValidationError("Global standard roles cannot be modified directly.")

    if name:
        role.name = name.strip()
        role.slug = slugify(name)
    if description is not None:
        role.description = description.strip()

    role.save()

    if permission_ids is not None:
        perms = Permission.objects.filter(id__in=permission_ids)
        role.permissions.set(perms)

    if role.gym:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            from common.enums import AdminLogCategory, AdminLogActionType
            log_admin_action(
                gym=role.gym,
                action="Updated a custom role",
                action_type=AdminLogActionType.UPDATE_ROLE,
                details=f"Updated role '{role.name}'",
                category=AdminLogCategory.ACCESS_CONTROL,
                target_type="role",
                target_id=str(role.id),
            )
        except Exception:
            pass

    return role


@transaction.atomic
def delete_custom_role(role: Role) -> None:
    """
    Deletes a custom role if it is not currently assigned to active staff.
    """
    if not role.is_custom:
        raise DomainValidationError("Global system roles cannot be deleted.")

    if GymStaffAssignment.objects.filter(role=role).exists():
        raise DomainValidationError("Cannot delete a role that is currently assigned to gym staff members.")

    if role.gym:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            from common.enums import AdminLogCategory, AdminLogActionType
            log_admin_action(
                gym=role.gym,
                action="Deleted a custom role",
                action_type=AdminLogActionType.DELETE_ROLE,
                details=f"Deleted role '{role.name}'",
                category=AdminLogCategory.ACCESS_CONTROL,
                target_type="role",
                target_id=str(role.id),
            )
        except Exception:
            pass

    role.delete()


@transaction.atomic
def invite_staff_member(gym: Gym, user_email: str, role_id: str) -> GymStaffAssignment:
    """
    Invites an existing user to join a gym under a designated role.
    """
    email_clean = user_email.lower().strip()
    try:
        user = User.objects.get(email=email_clean)
    except User.DoesNotExist:
        raise ResourceNotFoundError("No registered user found with this email. Staff must register first.")

    try:
        role = Role.objects.get(id=role_id)
    except Role.DoesNotExist:
        raise ResourceNotFoundError("Selected role does not exist.")

    if role.gym and role.gym != gym:
        raise DomainValidationError("The selected role does not belong to this gym.")

    assignment, created = GymStaffAssignment.objects.get_or_create(
        user=user,
        gym=gym,
        role=role,
        defaults={"status": StaffStatus.ACTIVE},
    )

    if not created and assignment.status == StaffStatus.INACTIVE:
        assignment.status = StaffStatus.ACTIVE
        assignment.save(update_fields=["status"])

    if created:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            from common.enums import AdminLogCategory, AdminLogActionType
            user_display = f"{user.first_name} {user.last_name}".strip() or user.email
            log_admin_action(
                gym=gym,
                action="Added an admin",
                action_type=AdminLogActionType.ADD_ADMIN,
                details=f"Added {user_display} as {role.name}",
                category=AdminLogCategory.ACCESS_CONTROL,
                target_type="staff",
                target_id=str(assignment.id),
            )
        except Exception:
            pass

    return assignment


@transaction.atomic
def update_staff_status(
    assignment: GymStaffAssignment,
    status_value: Optional[str] = None,
    role_id: Optional[uuid.UUID] = None,
) -> GymStaffAssignment:
    """
    Updates the status (active/inactive) and/or assigned role of a staff assignment.
    """
    update_fields = []
    log_details = []

    if status_value is not None:
        if status_value not in [StaffStatus.ACTIVE, StaffStatus.INACTIVE]:
            raise DomainValidationError(f"Invalid staff status: '{status_value}'.")
        assignment.status = status_value
        update_fields.append("status")
        log_details.append(f"status to {status_value}")

    if role_id is not None:
        try:
            role = Role.objects.get(id=role_id)
        except (Role.DoesNotExist, ValueError):
            raise ResourceNotFoundError(f"Role '{role_id}' not found.")
        if role.gym_id is not None and role.gym_id != assignment.gym_id:
            raise DomainValidationError("Role does not belong to this gym.")
        assignment.role = role
        update_fields.append("role")
        log_details.append(f"role to {role.name}")

    if update_fields:
        assignment.save(update_fields=update_fields)

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        user_name = f"{assignment.user.first_name} {assignment.user.last_name}".strip() or assignment.user.email
        log_admin_action(
            gym=assignment.gym,
            action="Updated staff assignment",
            action_type=AdminLogActionType.UPDATE_STAFF_ROLE,
            details=f"Updated {', '.join(log_details)} for {user_name}",
            category=AdminLogCategory.ACCESS_CONTROL,
            target_type="staff",
            target_id=str(assignment.id),
        )
    except Exception:
        pass

    return assignment


@transaction.atomic
def remove_staff_assignment(assignment: GymStaffAssignment) -> None:
    """
    Revokes gym staff access.
    """
    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        user_display = f"{assignment.user.first_name} {assignment.user.last_name}".strip() or assignment.user.email
        log_admin_action(
            gym=assignment.gym,
            action="Removed staff member",
            action_type=AdminLogActionType.REMOVE_STAFF,
            details=f"Removed {user_display} from {assignment.role.name}",
            category=AdminLogCategory.ACCESS_CONTROL,
            target_type="staff",
            target_id=str(assignment.id),
        )
    except Exception:
        pass
    assignment.delete()
