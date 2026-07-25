from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class MonobankTokenDecryptionError(Exception):
    """Raised when stored connection credentials cannot be decrypted."""


def _fernet() -> Fernet:
    key = settings.monobank_token_encryption_key.get_secret_value()
    return Fernet(key.encode("ascii"))


def encrypt_monobank_token(token: str) -> str:
    normalized = token.strip()
    if not normalized:
        raise ValueError("Monobank token cannot be empty")
    return _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")


def decrypt_monobank_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise MonobankTokenDecryptionError from exc
