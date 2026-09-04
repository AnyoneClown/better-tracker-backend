import re
from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-secret-change-before-running-in-production"
DEVELOPMENT_MONOBANK_ENCRYPTION_KEY = "YmV0dGVyLXRyYWNrZXItbW9ub2JhbmstZGV2LWtleSE="


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "Better Tracker API"
    environment: str = "development"
    database_url: str = "cockroachdb+asyncpg://root@localhost:26257/tracker"
    database_echo: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:43127"])
    jwt_secret_key: SecretStr = Field(
        default=SecretStr(DEVELOPMENT_JWT_SECRET),
        min_length=32,
    )
    jwt_issuer: str = Field(default="better-tracker-api", min_length=1)
    jwt_audience: str = Field(default="better-tracker-api", min_length=1)
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    google_oauth_client_id: str | None = Field(default=None, min_length=1)
    google_oauth_client_secret: SecretStr | None = None
    monobank_token_encryption_key: SecretStr = SecretStr(
        DEVELOPMENT_MONOBANK_ENCRYPTION_KEY
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_cockroach_database_url(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = re.sub(
            r"^postgres(?:ql)?://",
            "cockroachdb+asyncpg://",
            value,
            count=1,
            flags=re.IGNORECASE,
        )
        # Cockroach Cloud emits libpq's `sslmode` parameter. SQLAlchemy passes
        # query options directly to asyncpg, whose equivalent option is `ssl`.
        return re.sub(r"([?&])sslmode=", r"\1ssl=", normalized)

    @model_validator(mode="after")
    def require_production_secrets(self) -> "Settings":
        if bool(self.google_oauth_client_id) != bool(self.google_oauth_client_secret):
            raise ValueError(
                "GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
                "must be set together"
            )
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
        try:
            Fernet(self.monobank_token_encryption_key.get_secret_value().encode("ascii"))
        except (UnicodeEncodeError, ValueError) as exc:
            raise ValueError(
                "MONOBANK_TOKEN_ENCRYPTION_KEY must be a Fernet key"
            ) from exc
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
