"""Geography helpers for tests."""

import math

from app.core.geo import EARTH_RADIUS_KM


def destination(
    latitude: float, longitude: float, bearing_degrees: float, km: float
) -> tuple[float, float]:
    """The point `km` kilometres from the start in the given direction (0 north, 90 east)."""
    angle = km / EARTH_RADIUS_KM
    bearing = math.radians(bearing_degrees)
    lat1, lon1 = math.radians(latitude), math.radians(longitude)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angle)
        + math.cos(lat1) * math.sin(angle) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angle) * math.cos(lat1),
        math.cos(angle) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180
