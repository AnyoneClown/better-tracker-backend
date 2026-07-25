from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hasher = PasswordHash.recommended()
JWT_ALGORITHM = "HS256"
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$wagCPXjifgvUFBzq4hqe3w$"
    "CYaIb8sB+wtD+Vu/P4uod1+Qof8h+1g7bbDlBID48Rc"
)


def hash_password(password: str) -> str:
    """Hash a password with the recommended Argon2 settings."""
    return password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Return whether a plaintext password matches an encoded hash."""
    return password_hasher.verify(password, hashed_password)


def create_access_token(user_id: UUID) -> tuple[str, int]:
    """Create a signed, time-limited bearer token for a user."""
    now = datetime.now(UTC)
    expires_in = settings.access_token_expire_minutes * 60
    expires_at = now + timedelta(seconds=expires_in)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "iat": now,
            "exp": expires_at,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "jti": str(uuid4()),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    return token, expires_in


def decode_access_token(token: str) -> UUID:
    """Validate an access token and return its user identifier."""
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[JWT_ALGORITHM],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "type", "iat", "exp", "iss", "aud", "jti"]},
    )
    if payload["type"] != "access":
        raise jwt.InvalidTokenError("token is not an access token")
    try:
        return UUID(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise jwt.InvalidTokenError("token subject is invalid") from exc
