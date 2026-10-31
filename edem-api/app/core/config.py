from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "E-DEM Matching"
    API_V1_STR: str = "/v1"

    # Databases
    DATABASE_URL: str
    TEST_DATABASE_URL: str

    # Auth
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

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

    @property
    def active_database_url(self) -> str:
        """Return the correct database URL based on environment."""
        if self.ENVIRONMENT == "test":
            return self.TEST_DATABASE_URL
        return self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()
