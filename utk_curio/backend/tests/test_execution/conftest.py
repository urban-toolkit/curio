"""Shared fixtures for execution tests — reuses the common app/DB/auth fixtures."""

from __future__ import annotations

from utk_curio.backend.tests._unit_fixtures import (  # noqa: F401
    app,
    client,
    db,
    tmp_curio,
    user_and_token,
)
