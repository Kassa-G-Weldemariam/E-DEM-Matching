"""Geographic helpers."""

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088  # mean radius of the Earth


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (great-circle) distance in kilometres between two points.

    A good first approximation of travel distance. Real roads are longer.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


# The box is only a database pre-filter. This margin (about 11 m) makes sure it can never cut
# off a donor who is exactly at the edge of the radius. The exact check is always haversine_km.
BOX_MARGIN_DEGREES = 1e-4


@dataclass(frozen=True)
class BoundingBox:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, latitude: float, longitude: float) -> bool:
        return (
            self.min_lat <= latitude <= self.max_lat
            and self.min_lon <= longitude <= self.max_lon
        )


def bounding_box(latitude: float, longitude: float, radius_km: float) -> BoundingBox:
    """A rectangle that contains every point within `radius_km` of the given point.

    It is slightly larger than the circle, so it is a cheap first filter, never the final one.
    Near the poles, near the antimeridian (longitude 180) or for a huge radius it covers every
    longitude, which is always safe.
    """
    if radius_km < 0:
        raise ValueError("radius_km cannot be negative")

    angle = radius_km / EARTH_RADIUS_KM  # the radius as an angle, in radians
    if angle >= math.pi / 2:
        return BoundingBox(-90.0, 90.0, -180.0, 180.0)

    delta_lat = math.degrees(angle)
    min_lat = max(-90.0, latitude - delta_lat - BOX_MARGIN_DEGREES)
    max_lat = min(90.0, latitude + delta_lat + BOX_MARGIN_DEGREES)
    every_longitude = BoundingBox(min_lat, max_lat, -180.0, 180.0)

    if latitude - delta_lat <= -90.0 or latitude + delta_lat >= 90.0:
        return every_longitude  # the circle reaches a pole

    ratio = math.sin(angle) / math.cos(math.radians(latitude))
    if ratio >= 1.0:
        return every_longitude

    delta_lon = math.degrees(math.asin(ratio)) + BOX_MARGIN_DEGREES
    min_lon, max_lon = longitude - delta_lon, longitude + delta_lon
    if min_lon < -180.0 or max_lon > 180.0:
        return every_longitude  # crosses the antimeridian: do not try to wrap around

    return BoundingBox(min_lat, max_lat, min_lon, max_lon)
