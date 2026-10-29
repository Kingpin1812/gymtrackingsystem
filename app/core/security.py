"""Password hashing (stdlib scrypt) and opaque token helpers."""

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    salt_b64 = base64.b64encode(salt).decode()
    digest_b64 = base64.b64encode(digest).decode()
    return f"scrypt${_N}${_R}${_P}${salt_b64}${digest_b64}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# A real hash checked when the email is unknown, so login timing does not reveal which emails exist.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
