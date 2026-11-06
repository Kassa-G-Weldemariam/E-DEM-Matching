import pytest

from app.core.config import get_settings
from app.models.enums import ApprovalStatus
from tests.factories import make_blood_bank

URL = "/v1/blood-banks"

ADDIS = {"latitude": 9.03, "longitude": 38.74}
ADAMA = {"latitude": 8.54, "longitude": 39.27}
HAWASSA = {"latitude": 7.06, "longitude": 38.48}


def items(response):
    return response.json()["data"]["items"]


def names(response):
    return [item["name"] for item in items(response)]


@pytest.fixture()
def three_banks(db):
    """Names are chosen so that name order, and each distance order, all differ."""
    make_blood_bank(db, name="Zebra Blood Bank", city="Addis Ababa", **ADDIS)
    make_blood_bank(db, name="Mango Blood Bank", city="Adama", **ADAMA)
    make_blood_bank(db, name="Apple Blood Bank", city="Hawassa", **HAWASSA)


def test_the_list_is_public(client, three_banks):
    assert client.get(URL).status_code == 200


def test_an_empty_list_is_fine(client):
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [],
        "page": 1,
        "page_size": get_settings().DEFAULT_PAGE_SIZE,
        "total": 0,
    }


def test_only_approved_and_active_banks_are_listed(client, db):
    make_blood_bank(db, name="Visible")
    make_blood_bank(db, name="Pending", approval_status=ApprovalStatus.PENDING)
    make_blood_bank(db, name="Suspended", approval_status=ApprovalStatus.SUSPENDED)
    make_blood_bank(db, name="Paused", is_active=False)
    assert names(client.get(URL)) == ["Visible"]


def test_only_public_fields_are_returned(client, db):
    make_blood_bank(db, name="Visible")
    assert set(items(client.get(URL))[0]) == {
        "id",
        "name",
        "address",
        "city",
        "latitude",
        "longitude",
        "distance_km",
    }


def test_banks_are_sorted_by_name_when_no_coordinates_are_sent(client, three_banks):
    response = client.get(URL)
    assert names(response) == [
        "Apple Blood Bank",
        "Mango Blood Bank",
        "Zebra Blood Bank",
    ]
    assert all(item["distance_km"] is None for item in items(response))


def test_banks_are_sorted_nearest_first_from_addis_ababa(client, three_banks):
    response = client.get(URL, params={"lat": 9.03, "lng": 38.74})
    assert names(response) == [
        "Zebra Blood Bank",
        "Mango Blood Bank",
        "Apple Blood Bank",
    ]


def test_the_order_changes_with_the_callers_location(client, three_banks):
    response = client.get(URL, params={"lat": 8.54, "lng": 39.27})  # standing in Adama
    assert names(response) == [
        "Mango Blood Bank",
        "Zebra Blood Bank",
        "Apple Blood Bank",
    ]


def test_distances_are_returned_in_kilometres(client, three_banks):
    distances = {
        item["name"]: item["distance_km"]
        for item in items(client.get(URL, params={"lat": 9.03, "lng": 38.74}))
    }
    assert distances["Zebra Blood Bank"] == 0.0
    assert 70 < distances["Mango Blood Bank"] < 90
    assert 200 < distances["Apple Blood Bank"] < 240


@pytest.mark.parametrize("params", [{"lat": 9.03}, {"lng": 38.74}])
def test_one_coordinate_without_the_other_is_rejected(client, params):
    response = client.get(URL, params=params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


@pytest.mark.parametrize(
    "params", [{"lat": 91, "lng": 38.74}, {"lat": 9.03, "lng": 181}]
)
def test_out_of_range_coordinates_are_rejected(client, params):
    response = client.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_city_filter_ignores_case_and_spaces(client, three_banks):
    assert names(client.get(URL, params={"city": "  adama "})) == ["Mango Blood Bank"]


def test_city_filter_with_no_match_returns_an_empty_list(client, three_banks):
    response = client.get(URL, params={"city": "Nowhere"})
    assert response.status_code == 200
    assert items(response) == []
    assert response.json()["data"]["total"] == 0


def test_pages_split_the_list_and_report_the_total(client, db):
    for number in range(1, 6):
        make_blood_bank(db, name=f"Bank {number}")
    first = client.get(URL, params={"page": 1, "page_size": 2})
    second = client.get(URL, params={"page": 2, "page_size": 2})
    third = client.get(URL, params={"page": 3, "page_size": 2})
    assert names(first) == ["Bank 1", "Bank 2"]
    assert names(second) == ["Bank 3", "Bank 4"]
    assert names(third) == ["Bank 5"]
    assert first.json()["data"]["total"] == 5
    assert first.json()["data"]["page_size"] == 2


def test_a_page_past_the_end_is_empty_but_keeps_the_total(client, db):
    make_blood_bank(db, name="Only one")
    response = client.get(URL, params={"page": 9, "page_size": 2})
    assert items(response) == []
    assert response.json()["data"]["total"] == 1


def test_the_default_page_size_comes_from_settings(client, three_banks):
    assert (
        client.get(URL).json()["data"]["page_size"] == get_settings().DEFAULT_PAGE_SIZE
    )


def test_an_oversized_page_size_is_reduced_to_the_maximum(client, three_banks):
    maximum = get_settings().MAX_PAGE_SIZE
    assert (
        client.get(URL, params={"page_size": maximum + 500}).json()["data"]["page_size"]
        == maximum
    )


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 0}])
def test_invalid_page_values_are_rejected(client, params):
    response = client.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_distance_sorting_works_together_with_pages(client, three_banks):
    response = client.get(
        URL, params={"lat": 9.03, "lng": 38.74, "page": 2, "page_size": 2}
    )
    assert names(response) == ["Apple Blood Bank"]
    assert response.json()["data"]["total"] == 3
