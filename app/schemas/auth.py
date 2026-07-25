from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

from app.schemas.common import EntityResponse

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
MAX_EMAIL_LENGTH = 254


def normalize_email(value: object) -> object:
    if isinstance(value, str):
        return value.strip().casefold()
    return value


NormalizedEmail = Annotated[
    EmailStr,
    BeforeValidator(normalize_email),
    Field(max_length=MAX_EMAIL_LENGTH),
]


class UserRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=(
            "Must include lowercase, uppercase, numeric, and special characters."
        ),
    )

    @field_validator("password")
    @classmethod
    def password_must_be_strong(cls, value: str) -> str:
        requirements = (
            (any(character.islower() for character in value), "a lowercase letter"),
            (any(character.isupper() for character in value), "an uppercase letter"),
            (any(character.isdigit() for character in value), "a number"),
            (
                any(
                    not character.isalnum() and not character.isspace()
                    for character in value
                ),
                "a special character",
            ),
        )
        missing = [message for is_present, message in requirements if not is_present]
        if missing:
            raise ValueError(f"password must contain {', '.join(missing)}")
        return value


class UserResponse(EntityResponse):
    model_config = ConfigDict(from_attributes=True)

    email: NormalizedEmail
    is_active: bool


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
