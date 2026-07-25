from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class PrivatBankTokenDecryptionError(Exception):
    pass


def _fernet() -> Fernet:
    key = settings.privatbank_token_encryption_key.get_secret_value()
    return Fernet(key.encode("ascii"))


def encrypt_privatbank_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_privatbank_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise PrivatBankTokenDecryptionError from exc
