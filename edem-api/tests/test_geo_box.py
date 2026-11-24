import pytest

from app.core.geo import BoundingBox, bounding_box, haversine_km
from tests.geo_helpers import destination

ADDIS = (9.03, 38.74)
RADIUS = 25.0
BEARINGS = range(0, 360, 10)


def test_a_zero_radius_box_is_a_tiny_square_around_the_point():
    box = bounding_box(*ADDIS, 0)
    assert box.contains(*ADDIS)
    assert box.max_lat - box.min_lat < 0.001
    assert box.max_lon - box.min_lon < 0.001


def test_a_negative_radius_is_refused():
    with pytest.raises(ValueError, match="negative"):
        bounding_box(*ADDIS, -1)


def test_the_box_for_addis_ababa_has_the_expected_size():
    box = bounding_box(*ADDIS, RADIUS)
    assert box.max_lat - box.min_lat == pytest.approx(0.4499, abs=0.002)
    assert box.max_lon - box.min_lon == pytest.approx(0.4555, abs=0.002)


@pytest.mark.parametrize("latitude", [0.0, 9.03, 45.0, 80.0])
def test_every_point_inside_the_radius_is_inside_the_box(latitude):
    box = bounding_box(latitude, 38.74, RADIUS)
    for bearing in BEARINGS:
        for km in (0.0, 12.5, RADIUS * 0.999, RADIUS):
            point = destination(latitude, 38.74, bearing, km)
            assert box.contains(*point), f"bearing {bearing}, {km} km"


@pytest.mark.parametrize(
    "bearing", [0, 90, 180, 270], ids=["north", "east", "south", "west"]
)
def test_a_point_well_outside_the_radius_is_outside_the_box(bearing):
    box = bounding_box(*ADDIS, RADIUS)
    assert not box.contains(*destination(*ADDIS, bearing, RADIUS * 2))


def test_near_the_north_pole_every_longitude_is_included():
    box = bounding_box(89.9, 10.0, 50)
    assert (box.min_lon, box.max_lon) == (-180.0, 180.0)
    assert box.max_lat == 90.0


def test_near_the_south_pole_every_longitude_is_included():
    box = bounding_box(-89.9, 10.0, 50)
    assert (box.min_lon, box.max_lon) == (-180.0, 180.0)
    assert box.min_lat == -90.0


def test_near_the_antimeridian_from_the_east_the_range_is_not_cut():
    box = bounding_box(0.0, 179.95, RADIUS)
    assert (box.min_lon, box.max_lon) == (-180.0, 180.0)
    assert box.contains(0.0, -179.95)  # across the line, about 11 km away


def test_near_the_antimeridian_from_the_west_the_range_is_not_cut():
    box = bounding_box(0.0, -179.95, RADIUS)
    assert (box.min_lon, box.max_lon) == (-180.0, 180.0)
    assert box.contains(0.0, 179.95)


def test_a_huge_radius_covers_the_world():
    assert bounding_box(0.0, 0.0, 20000) == BoundingBox(-90.0, 90.0, -180.0, 180.0)


def test_contains_includes_the_edges():
    box = BoundingBox(0.0, 1.0, 0.0, 1.0)
    assert box.contains(0.0, 0.0)
    assert box.contains(1.0, 1.0)
    assert not box.contains(1.0001, 0.5)
    assert not box.contains(0.5, -0.0001)


def test_the_test_helper_places_points_at_the_requested_distance():
    for bearing in BEARINGS:
        point = destination(*ADDIS, bearing, RADIUS)
        assert haversine_km(*ADDIS, *point) == pytest.approx(RADIUS, abs=0.01)
