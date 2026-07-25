from uuid import uuid4

import jwt
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import DEVELOPMENT_JWT_SECRET, Settings, settings
from app.core.security import create_access_token, decode_access_token


def test_access_token_round_trip_and_rejects_tampering() -> None:
    user_id = uuid4()
    token, expires_in = create_access_token(user_id)

    assert expires_in == 1800
    assert decode_access_token(token) == user_id

    tampered_token = f"{token[:-1]}{'a' if token[-1] != 'a' else 'b'}"
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(tampered_token)


def test_access_token_rejects_wrong_token_type() -> None:
    token, _ = create_access_token(uuid4())
    payload = jwt.decode(
        token,
        options={"verify_signature": False},
        algorithms=["HS256"],
    )
    payload["type"] = "refresh"
    wrong_type_token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )

    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(wrong_type_token)


def test_settings_require_a_strong_non_default_production_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret_key="too-short")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, monobank_token_encryption_key="not-a-fernet-key")

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret_key=DEVELOPMENT_JWT_SECRET,
        )

    production_settings = Settings(
        _env_file=None,
        environment="production",
        jwt_secret_key="a-production-secret-with-at-least-32-characters",
        monobank_token_encryption_key=Fernet.generate_key().decode("ascii"),
    )
    assert production_settings.environment == "production"
