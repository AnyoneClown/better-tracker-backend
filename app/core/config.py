from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-secret-change-before-running-in-production"
DEVELOPMENT_MONOBANK_ENCRYPTION_KEY = "YmV0dGVyLXRyYWNrZXItbW9ub2JhbmstZGV2LWtleSE="
DEVELOPMENT_PRIVATBANK_ENCRYPTION_KEY = "FU0XZuwTkrhstlI0PJ2amnWd1azqg50-mdooWQogWYI="


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
    monobank_token_encryption_key: SecretStr = SecretStr(
        DEVELOPMENT_MONOBANK_ENCRYPTION_KEY
    )
    privatbank_token_encryption_key: SecretStr = SecretStr(
        DEVELOPMENT_PRIVATBANK_ENCRYPTION_KEY
    )

    @model_validator(mode="after")
    def require_production_secrets(self) -> "Settings":
        production_like = self.environment.casefold() not in {"development", "test"}
        if production_like:
            if self.jwt_secret_key.get_secret_value() == DEVELOPMENT_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET_KEY must be changed outside development and test"
                )
            if (
                self.monobank_token_encryption_key.get_secret_value()
                == DEVELOPMENT_MONOBANK_ENCRYPTION_KEY
            ):
                raise ValueError(
                    "MONOBANK_TOKEN_ENCRYPTION_KEY must be changed outside "
                    "development and test"
                )
            if (
                self.privatbank_token_encryption_key.get_secret_value()
                == DEVELOPMENT_PRIVATBANK_ENCRYPTION_KEY
            ):
                raise ValueError(
                    "PRIVATBANK_TOKEN_ENCRYPTION_KEY must be changed outside "
                    "development and test"
                )

        encryption_keys = {
            "MONOBANK_TOKEN_ENCRYPTION_KEY": (
                self.monobank_token_encryption_key.get_secret_value()
            ),
            "PRIVATBANK_TOKEN_ENCRYPTION_KEY": (
                self.privatbank_token_encryption_key.get_secret_value()
            ),
        }
        for setting_name, key in encryption_keys.items():
            try:
                Fernet(key.encode("ascii"))
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError(f"{setting_name} must be a Fernet key") from exc
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
