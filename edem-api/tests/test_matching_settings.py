import pytest
from pydantic import ValidationError

from app.core.config import Settings

NAMES = [
    "UPPER_AGE_LIMIT_YEARS",
    "MIN_AGE_YEARS",
    "MIN_DAYS_BETWEEN_DONATIONS_MALE",
    "MIN_DAYS_BETWEEN_DONATIONS_FEMALE",
    "DISTANCE_BAND_KM",
]

REQUIRED_DEFAULTS = {
    "DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/edem",
    "TEST_DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/edem_test",
    "JWT_SECRET_KEY": "test-secret-key-at-least-32-characters-long",
}


@pytest.fixture()
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    for key in REQUIRED_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def make(**overrides) -> Settings:
    values = {**REQUIRED_DEFAULTS, **overrides}
    return Settings(_env_file=None, **values)


def test_the_defaults_are_65_90_120_and_a_two_kilometre_band(clean_env):
    settings = make()
    assert settings.UPPER_AGE_LIMIT_YEARS == 65
    assert settings.MIN_DAYS_BETWEEN_DONATIONS_MALE == 90
    assert settings.MIN_DAYS_BETWEEN_DONATIONS_FEMALE == 120
    assert settings.DISTANCE_BAND_KM == 2.0


@pytest.mark.parametrize("limit", [18, 17])
def test_the_upper_age_limit_must_be_above_the_minimum_age(clean_env, limit):
    with pytest.raises(ValidationError):
        make(UPPER_AGE_LIMIT_YEARS=limit, MIN_AGE_YEARS=18)


@pytest.mark.parametrize(
    "name",
    [
        "UPPER_AGE_LIMIT_YEARS",
        "MIN_DAYS_BETWEEN_DONATIONS_MALE",
        "MIN_DAYS_BETWEEN_DONATIONS_FEMALE",
        "DISTANCE_BAND_KM",
    ],
)
def test_zero_is_refused(clean_env, name):
    with pytest.raises(ValidationError):
        make(**{name: 0})


def test_a_value_can_be_overridden_by_the_environment(clean_env):
    clean_env.setenv("DISTANCE_BAND_KM", "5")
    assert make().DISTANCE_BAND_KM == 5.0
