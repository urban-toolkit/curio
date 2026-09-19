"""Tests for auth services — signup, signin, guest, etc."""

import pytest

from utk_curio.backend.app.users import services
from utk_curio.backend.app.users.schemas import SignInIn, SignUpIn
from utk_curio.backend.app.users.services import (
    AuthError,
    signin_guest,
    signin_password,
    signin_shared_guest,
    signup,
    signin_google,
)


class TestSignup:
    def test_happy_path(self, app):
        with app.app_context():
            result = signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                    email="alice@example.com",
                )
            )
            assert result.user.username == "alice"
            assert result.token

    def test_duplicate_username(self, app):
        with app.app_context():
            signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                )
            )
            with pytest.raises(AuthError, match="Username already taken"):
                signup(
                    SignUpIn(
                        name="Alice2",
                        username="alice",
                        password="password456",
                    )
                )

    def test_duplicate_email(self, app):
        with app.app_context():
            signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                    email="a@b.com",
                )
            )
            with pytest.raises(AuthError, match="Email already registered"):
                signup(
                    SignUpIn(
                        name="Bob",
                        username="bob",
                        password="password456",
                        email="a@b.com",
                    )
                )

    def test_short_password(self, app):
        with app.app_context():
            with pytest.raises(AuthError, match="at least 8"):
                signup(
                    SignUpIn(
                        name="Alice",
                        username="alice",
                        password="short",
                    )
                )

    def test_email_optional(self, app):
        with app.app_context():
            result = signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                )
            )
            assert result.user.email is None


class TestSigninPassword:
    def test_signin_by_username(self, app):
        with app.app_context():
            signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                )
            )
            result = signin_password(
                SignInIn(identifier="alice", password="password123")
            )
            assert result.user.username == "alice"

    def test_signin_by_email(self, app):
        with app.app_context():
            signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                    email="alice@example.com",
                )
            )
            result = signin_password(
                SignInIn(identifier="alice@example.com", password="password123")
            )
            assert result.user.username == "alice"

    def test_wrong_password(self, app):
        with app.app_context():
            signup(
                SignUpIn(
                    name="Alice",
                    username="alice",
                    password="password123",
                )
            )
            with pytest.raises(AuthError, match="Invalid credentials"):
                signin_password(
                    SignInIn(identifier="alice", password="wrong")
                )


class TestGuestLogin:
    def test_guest_allowed(self, app):
        with app.app_context():
            result = signin_guest(allowed=True)
            assert result.user.is_guest is True
            assert result.user.type == "guest"
            assert result.user.username == services.CURIO_SHARED_GUEST_USERNAME

    def test_guest_is_shared_across_signins(self, app):
        with app.app_context():
            first = signin_guest(allowed=True)
            second = signin_guest(allowed=True)
            assert first.user.id == second.user.id
            assert first.user.username == second.user.username

    def test_shared_guest_reuses_existing_token(self, app):
        with app.app_context():
            first = signin_shared_guest()
            second = signin_shared_guest(existing_token=first.token)
            assert first.user.id == second.user.id
            assert first.token == second.token

    def test_guest_forbidden(self, app):
        with app.app_context():
            with pytest.raises(AuthError, match="not available"):
                signin_guest(allowed=False)


class TestGoogleSignIn:
    def test_invalid_google_token_raises(self, app, monkeypatch):
        """Tests if signin_google gaurds against invalid tokens"""
        with app.app_context():
            # The verify_token function of services.GoogleOAuth will return None within this context
            monkeypatch.setattr(services.GoogleOAuth, "verify_token", lambda self, auth_code: None)
            with pytest.raises(AuthError, match="Invalid Google token."):
                signin_google("Invalid Auth Code")
    
    def test_google_user_signin(self, app, monkeypatch):
        with app.app_context():
            monkeypatch.setattr(
                services.GoogleOAuth, 
                "verify_token", 
                lambda self, code :{
                    "uid": "google-uid-123",
                    "email":"alice@example.com",
                    "name": "Alice"
                },
            )
            result = signin_google("New Auth Token")
            assert result.user.username == "alice"
            assert result.token          

