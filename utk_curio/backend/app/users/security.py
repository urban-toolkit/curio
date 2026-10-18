"""Password hashing, token generation, and constant-time helpers."""

from __future__ import annotations

import hmac
from uuid import uuid4

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _ph = PasswordHasher()
    _HAS_ARGON2 = True
except ImportError:
    _HAS_ARGON2 = False

from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(plain: str) -> str:
    if _HAS_ARGON2:
        return _ph.hash(plain)
    return generate_password_hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    if _HAS_ARGON2 and hashed.startswith("$argon2"):
        try:
            return _ph.verify(hashed, plain)
        except VerifyMismatchError:
            return False
    return check_password_hash(hashed, plain)


def new_session_token() -> str:
    return str(uuid4())


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
