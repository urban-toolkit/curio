"""Pydantic-style DTOs implemented as plain dataclasses (no extra dep)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


@dataclass
class SignUpIn:
    name: str
    username: str
    password: str
    email: Optional[str] = None

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.name or not self.name.strip():
            errors.append("Name is required.")
        if not USERNAME_RE.match(self.username or ""):
            errors.append(
                "Username must be 3-32 characters: letters, digits, underscore."
            )
        if len(self.password or "") < 8:
            errors.append("Password must be at least 8 characters.")
        if self.email is not None and self.email.strip() == "":
            errors.append("Email must not be blank when provided.")
        return errors


@dataclass
class SignInIn:
    identifier: str
    password: str

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.identifier:
            errors.append("Identifier (username or email) is required.")
        if not self.password:
            errors.append("Password is required.")
        return errors


@dataclass
class UserOut:
    id: int
    username: str
    name: str
    email: Optional[str]
    profile_image: Optional[str]
    type: Optional[str]
    is_guest: bool
    # The Data source keys this account saved, by secret id, each as ``True``;
    # a key itself never leaves the server.
    has_source_keys: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "name": self.name,
            "email": self.email,
            "profile_image": self.profile_image,
            "type": self.type,
            "is_guest": self.is_guest,
            "has_source_keys": dict(self.has_source_keys),
        }


@dataclass
class AuthOut:
    user: UserOut
    token: str

    def to_dict(self) -> dict:
        return {"user": self.user.to_dict(), "token": self.token}


@dataclass
class UserPatchIn:
    name: Optional[str] = None
    email: Optional[str] = None
    type: Optional[str] = None
    # Data source keys by the secret id their sources declare; ``""`` removes
    # one, and a key left out stays as it is.
    source_keys: Optional[object] = None
