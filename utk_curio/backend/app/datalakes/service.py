"""Public facade for the Data Lake Catalog.

The one stable import point for the rest of the app, mirroring
``datasets/service.py``. Everything outside this package imports from here,
so the internal layering can move without a sweep.
"""

from __future__ import annotations

from typing import Any

from utk_curio.backend.app.datalakes.application.catalog import LakeCatalog
from utk_curio.backend.app.datalakes.domain.manifest import LakeSourceManifest


class DataLakeService:
    """Per-request entry point.

    ``user_key`` is carried now though only the credential and acquire phases
    use it, so the constructor does not change shape underneath callers later.
    """

    def __init__(self, user_key: str | None = None, *, icon_url_for=None) -> None:
        self.user_key = user_key
        self._catalog = LakeCatalog(
            credential_present=self._credential_present,
            icon_url_for=icon_url_for,
        )

    def _credential_present(self, secret_id: str | None) -> bool:
        # Credentials arrive in their own phase. Reporting "absent" until then
        # is honest: no account has one stored, so no source has its token.
        return False

    def list_catalog(self, **kwargs: Any) -> dict[str, Any]:
        return self._catalog.list_catalog(**kwargs)

    def get_source(self, dir_name: str) -> dict[str, Any]:
        return self._catalog.row(self._catalog.get_manifest(dir_name))

    def get_manifest(self, dir_name: str) -> LakeSourceManifest:
        return self._catalog.get_manifest(dir_name)
