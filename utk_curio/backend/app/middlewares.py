"""Legacy middleware - delegates to the new users.dependencies module."""

from utk_curio.backend.app.users.dependencies import require_auth  # noqa: F401
