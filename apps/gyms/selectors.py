from typing import List, Dict, Any
from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment


def get_accessible_gyms_for_user(user) -> List[Dict[str, Any]]:
    """
    Returns all gyms accessible to the user, identifying their role/relation.
    """
    owned_gyms = Gym.objects.filter(owner_user=user).distinct()
    staff_assignments = GymStaffAssignment.objects.filter(
        user=user,
        status="active",
    ).select_related("gym", "role")

    gyms_dict = {}

    for g in owned_gyms:
        gyms_dict[str(g.id)] = {
            "gym_id": str(g.id),
            "name": g.name,
            "role": "Owner",
            "is_owner": True,
            "primary_type": g.primary_type,
            "profile_picture_url": g.profile_picture_url,
        }

    for assignment in staff_assignments:
        gid = str(assignment.gym.id)
        if gid not in gyms_dict:
            gyms_dict[gid] = {
                "gym_id": gid,
                "name": assignment.gym.name,
                "role": assignment.role.name,
                "is_owner": False,
                "primary_type": assignment.gym.primary_type,
                "profile_picture_url": assignment.gym.profile_picture_url,
            }

    return list(gyms_dict.values())


def get_gym_by_id(gym_id: str) -> Gym:
    """Retrieve gym by UUID or None."""
    return Gym.objects.filter(id=gym_id).first()
