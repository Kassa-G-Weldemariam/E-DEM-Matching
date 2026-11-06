import pytest

from app.core.geo import haversine_km


def test_the_same_point_is_zero_kilometres_away():
    assert haversine_km(9.03, 38.74, 9.03, 38.74) == 0


def test_one_degree_of_latitude_is_about_111_km():
    assert haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.1)


def test_one_degree_of_longitude_at_the_equator_is_about_111_km():
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19, abs=0.1)


def test_distance_is_the_same_in_both_directions():
    assert haversine_km(9.03, 38.74, 8.54, 39.27) == pytest.approx(
        haversine_km(8.54, 39.27, 9.03, 38.74)
    )


def test_london_to_paris_is_about_344_km():
    assert haversine_km(51.5074, -0.1278, 48.8566, 2.3522) == pytest.approx(
        343.6, abs=1.5
    )


def test_opposite_sides_of_the_earth_do_not_crash():
    assert haversine_km(0, 0, 0, 180) == pytest.approx(20015, abs=5)
