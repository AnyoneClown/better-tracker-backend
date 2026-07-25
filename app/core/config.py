from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-secret-change-before-running-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Better Tracker API"
    environment: str = "development"
    database_url: str = "cockroachdb+asyncpg://root@localhost:26257/tracker"
    database_echo: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    jwt_secret_key: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_JWT_SECRET),
        min_length=32,
    )
    jwt_issuer: str = Field(default="better-tracker-api", min_length=1)
    jwt_audience: str = Field(default="better-tracker-api", min_length=1)
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)

    @model_validator(mode="after")
    def require_production_jwt_secret(self) -> "Settings":
        if (
            self.environment.casefold() not in {"development", "test"}
            and self.jwt_secret_key.get_secret_value() == DEVELOPMENT_JWT_SECRET
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be changed outside development and test"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
