"""Geographic helpers."""

import math

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
