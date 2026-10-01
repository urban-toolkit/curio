"""The caller-facing package service error: a message and the HTTP status a route answers with. Domain-level (memo dev/143 B5) so every layer — the parsers in ``schemas/``, the use cases, the routes — raises the same class.

Memo dev/143, B2.
"""

from __future__ import annotations


class PackageServiceError(Exception):
    """Raised for caller-facing package-service errors (bad input, not-found)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
