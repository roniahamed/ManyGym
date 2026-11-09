import logging
import uuid
from decimal import Decimal
from typing import List, Tuple, Union, Optional
import redis
from django.conf import settings

logger = logging.getLogger(__name__)

REDIS_GEO_KEY = "gyms:geo:locations"


def get_redis_client() -> redis.Redis:
    """Returns an active Redis client using the configured cache URL."""
    return redis.from_url(settings.REDIS_CACHE_URL, decode_responses=True)


def sync_gym_location_to_redis(
    gym_id: Union[str, uuid.UUID],
    latitude: Union[float, Decimal],
    longitude: Union[float, Decimal],
) -> bool:
    """
    Saves or updates a gym's primary map coordinates in the Redis Geospatial index.
    Skips unplaced / default zero coordinates (0.0, 0.0).
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
        gid = str(gym_id)

        # Skip default / unpinned coordinates
        if lat == 0.0 and lon == 0.0:
            remove_gym_location_from_redis(gid)
            return False

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            logger.warning("Coordinates out of range for gym %s: (%s, %s)", gid, lat, lon)
            return False

        client = get_redis_client()
        # Redis geoadd takes: key, (longitude, latitude, member)
        client.geoadd(REDIS_GEO_KEY, (lon, lat, gid))
        logger.debug("Successfully synced gym %s coordinates to Redis GEO (%s, %s)", gid, lon, lat)
        return True
    except Exception as exc:
        logger.warning("Failed to sync gym location to Redis GEO (%s): %s", gym_id, exc)
        return False


def remove_gym_location_from_redis(gym_id: Union[str, uuid.UUID]) -> bool:
    """Removes a gym from the Redis Geospatial index."""
    try:
        gid = str(gym_id)
        client = get_redis_client()
        client.zrem(REDIS_GEO_KEY, gid)
        logger.debug("Removed gym %s from Redis GEO index", gid)
        return True
    except Exception as exc:
        logger.warning("Failed to remove gym %s from Redis GEO: %s", gym_id, exc)
        return False


def sync_gym_primary_location_to_cache(gym_id: Union[str, uuid.UUID]) -> bool:
    """
    Inspects gym lifecycle and primary location; syncs to Redis GEO if active and published,
    or purges from Redis GEO if deactivated, soft-deleted, or unpublished.
    """
    from apps.gyms.models import Gym, GymLocation

    try:
        gid = str(gym_id)
        gym = (
            Gym.objects.filter(id=gid)
            .select_related("settings")
            .prefetch_related("locations")
            .first()
        )
        if not gym:
            remove_gym_location_from_redis(gid)
            return False

        # Check visibility
        settings_obj = getattr(gym, "settings", None)
        if settings_obj and (
            settings_obj.is_deleted
            or settings_obj.is_deactivated
            or not settings_obj.is_published
        ):
            remove_gym_location_from_redis(gid)
            return False

        primary_loc = (
            gym.locations.filter(is_primary=True).first()
            or gym.locations.first()
        )
        if not primary_loc:
            remove_gym_location_from_redis(gid)
            return False

        return sync_gym_location_to_redis(
            gym_id=gid,
            latitude=primary_loc.latitude,
            longitude=primary_loc.longitude,
        )
    except Exception as exc:
        logger.warning("Failed in sync_gym_primary_location_to_cache for %s: %s", gym_id, exc)
        return False


def search_nearby_gym_ids_redis(
    latitude: float,
    longitude: float,
    radius_km: float = 20.0,
) -> List[Tuple[str, float]]:
    """
    Performs ultra-fast (<1ms) geospatial proximity search in Redis.
    Returns ordered list of (gym_id, distance_km).
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
        radius = float(radius_km)

        client = get_redis_client()
        # Redis GEOSEARCH with distance sorted ASC
        results = client.geosearch(
            REDIS_GEO_KEY,
            longitude=lon,
            latitude=lat,
            radius=radius,
            unit="km",
            withdist=True,
            sort="ASC",
        )
        # Format results: list of (str(gym_id), float(distance_km))
        parsed = []
        for item in results:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                member_id = str(item[0])
                dist = float(item[1])
                parsed.append((member_id, dist))
        return parsed
    except Exception as exc:
        logger.warning("Redis GEO search failed or key not found: %s", exc)
        return []


def warm_gym_geo_cache() -> int:
    """
    Warms the Redis Geospatial cache with all active, published, non-deleted gyms.
    Returns the count of indexed gyms.
    """
    from apps.gyms.models import GymLocation
    from django.db.models import Q

    try:
        client = get_redis_client()
        active_locations = (
            GymLocation.objects.filter(is_primary=True)
            .filter(
                Q(gym__settings__isnull=True)
                | (
                    Q(gym__settings__is_published=True)
                    & Q(gym__settings__is_deactivated=False)
                    & Q(gym__settings__is_deleted=False)
                )
            )
            .exclude(latitude=0.0, longitude=0.0)
            .only("gym_id", "latitude", "longitude")
        )

        count = 0
        pipe = client.pipeline()
        for loc in active_locations.iterator(chunk_size=500):
            lat = float(loc.latitude)
            lon = float(loc.longitude)
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                pipe.geoadd(REDIS_GEO_KEY, (lon, lat, str(loc.gym_id)))
                count += 1
                if count % 500 == 0:
                    pipe.execute()

        pipe.execute()
        logger.info("Warmed Redis GEO cache with %d gym locations.", count)
        return count
    except Exception as exc:
        logger.error("Failed to warm gym geo cache: %s", exc)
        return 0

