"""Business logic for authentication and user management."""

from __future__ import annotations

from utk_curio.backend.extensions import db
from utk_curio.backend.app.users.models import User
from utk_curio.backend.app.users.schemas import (
    AuthOut,
    SignInIn,
    SignUpIn,
    UserOut,
    UserPatchIn,
)
from utk_curio.backend.app.users import repositories as repo
from utk_curio.backend.app.users import security
from utk_curio.backend.config import (
    CURIO_SHARED_GUEST_NAME,
    CURIO_SHARED_GUEST_USERNAME,
)


class AuthError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        name=u.name,
        email=u.email,
        profile_image=u.profile_image,
        type=u.type,
        is_guest=u.is_guest,
        has_llm_api_key=bool(u.llm_api_key),
        llm_api_type=u.llm_api_type,
        llm_base_url=u.llm_base_url,
        llm_model=u.llm_model,
    )


def _auth_out(u: User) -> AuthOut:
    session = repo.create_session(u.id)
    return AuthOut(user=_user_out(u), token=session.token)


def _auth_out_with_token(u: User, token: str) -> AuthOut:
    return AuthOut(user=_user_out(u), token=token)


def _shared_guest_user() -> User:
    user = repo.user_by_username(CURIO_SHARED_GUEST_USERNAME)
    if user and not user.is_guest:
        raise AuthError(
            f"Shared guest username {CURIO_SHARED_GUEST_USERNAME!r} is already in use.",
            500,
        )
    if user:
        if user.type != "guest" or user.name != CURIO_SHARED_GUEST_NAME:
            user.type = "guest"
            user.name = CURIO_SHARED_GUEST_NAME
            user.is_guest = True
            db.session.commit()
        return user
    return repo.create_user(
        username=CURIO_SHARED_GUEST_USERNAME,
        name=CURIO_SHARED_GUEST_NAME,
        is_guest=True,
        type="guest",
    )


def signup(data: SignUpIn) -> AuthOut:
    errors = data.validate()
    if errors:
        raise AuthError("; ".join(errors))

    if repo.user_by_identifier(data.username):
        raise AuthError("Username already taken.", 409)

    if data.email and repo.user_by_identifier(data.email):
        raise AuthError("Email already registered.", 409)

    user = repo.create_user(
        username=data.username,
        name=data.name,
        email=data.email or None,
        password_hash=security.hash_password(data.password),
        type="programmer",
    )
    return _auth_out(user)


def signin_password(data: SignInIn) -> AuthOut:
    errors = data.validate()
    if errors:
        raise AuthError("; ".join(errors))

    user = repo.user_by_identifier(data.identifier)
    if not user or not user.password_hash:
        raise AuthError("Invalid credentials.", 401)

    if not security.verify_password(user.password_hash, data.password):
        raise AuthError("Invalid credentials.", 401)

    return _auth_out(user)


def signin_shared_guest(existing_token: str | None = None) -> AuthOut:
    user = _shared_guest_user()
    if existing_token:
        session = repo.session_by_token(existing_token)
        if session and not session.is_expired and session.user_id == user.id:
            repo.touch_session(session)
            return _auth_out_with_token(user, session.token)
    return _auth_out(user)


def signin_guest(allowed: bool, existing_token: str | None = None) -> AuthOut:
    if not allowed:
        raise AuthError("Guest login is not available.", 403)
    return signin_shared_guest(existing_token=existing_token)


def signout(token: str) -> None:
    repo.invalidate_session(token)


def get_me(user: User) -> UserOut:
    return _user_out(user)


def patch_me(user: User, data: UserPatchIn) -> UserOut:
    if data.name is not None:
        user.name = data.name
    if data.email is not None:
        user.email = data.email if data.email else None
    if data.type is not None:
        user.type = data.type
    if data.llm_api_key is not None:
        if user.is_guest:
            raise AuthError("Guest users cannot set an API key.", 403)
        user.llm_api_key = data.llm_api_key if data.llm_api_key else None
    if not user.is_guest:
        if data.llm_api_type is not None:
            user.llm_api_type = data.llm_api_type if data.llm_api_type else None
        if data.llm_base_url is not None:
            user.llm_base_url = data.llm_base_url if data.llm_base_url else None
        if data.llm_model is not None:
            user.llm_model = data.llm_model if data.llm_model else None
    db.session.commit()
    return _user_out(user)
