from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "E-DEM Matching"
    API_V1_STR: str = "/v1"

    # Databases
    DATABASE_URL: str
    TEST_DATABASE_URL: str

    # Auth
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Matching parameters
    BLOOD_BANK_RESPONSE_TIMEOUT_MINUTES: int = 10
    DONOR_RESPONSE_TIMEOUT_MINUTES: int = 6
    MAX_MATCHING_RADIUS_KM: float = 25.0
    DONORS_PER_BATCH: int = 15
    MAX_BATCHES: int = 3
    MIN_DAYS_BETWEEN_DONATIONS: int = 56

    # Environment switch
    ENVIRONMENT: str = "development"  # development | test | production

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    @model_validator(mode="after")
    def validate_production_secret(self) -> "Settings":
        if self.ENVIRONMENT == "production" and (
            len(self.JWT_SECRET_KEY) < 32
            or self.JWT_SECRET_KEY.lower()
            in {
                "change-this-to-a-long-random-secret-key",
                "replace-with-a-random-secret",
                "replace-with-a-random-secret-of-at-least-32-characters",
            }
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be a random value of at least 32 characters in production"
            )
        return self

    @property
    def active_database_url(self) -> str:
        """Return the correct database URL based on environment."""
        if self.ENVIRONMENT == "test":
            return self.TEST_DATABASE_URL
        return self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
