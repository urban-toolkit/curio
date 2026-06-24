"""Workspace and sample-data dataset repository."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from utk_curio.backend.app.datasets.catalog_items import format_for_path, item_from_file
from utk_curio.backend.app.datasets.constants import SIDECAR_SUFFIXES, SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.file_meta import count_file, meta_path, write_file_meta


def data_root_dirs() -> list[Path]:
    """Browsable file-data roots: bundled sample data and workspace data.

    Single source of truth shared by catalog listing (``LocalDatasetRepository``)
    and the path-containment check in ``catalog_paths`` — both must agree on
    exactly which directories hold legitimately readable data files.
    """
    launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))
    package_data = Path(__file__).resolve().parents[3] / "data"
    return [package_data, launch_dir / "data"]


class LocalDatasetRepository:
    def _roots(self) -> list[tuple[str, Path]]:
        package_data, workspace_data = data_root_dirs()
        return [
            ("Curio sample data", package_data),
            ("Workspace data", workspace_data),
        ]

    def list_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_label, root in self._roots():
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.iterdir()):
                # Skip our own sidecars (<file>.meta.json, <file>.decode.json):
                # they end in .json so they'd otherwise be cataloged as JSON
                # datasets, and meta_path() would append another .meta.json each
                # refresh, growing <file>.meta.json.meta.json... without bound.
                if path.name.endswith(SIDECAR_SUFFIXES):
                    continue
                fmt = format_for_path(path)
                if fmt is None:
                    continue
                # Lazily generate the sidecar for pre-existing files that have
                # never been imported through save_import.
                if not meta_path(path).exists():
                    row_count, feature_count = count_file(path, fmt)
                    write_file_meta(path, row_count, feature_count)
                item = item_from_file(path, source_label=source_label)
                if item is None or item["id"] in seen:
                    continue
                items.append(item)
                seen.add(item["id"])

        return items

    def save_import(self, file: FileStorage) -> dict[str, Any]:
        filename = secure_filename(file.filename or "")
        if not filename:
            raise DatasetCatalogError("No file selected")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise DatasetCatalogError(f"Unsupported dataset format: {suffix or filename}")
        launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))
        data_dir = launch_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        target = data_dir / filename
        file.save(target)
        # Compute counts once at import time and persist to sidecar so that
        # every subsequent catalog listing reads cheaply from the cache.
        fmt = SUPPORTED_SUFFIXES[suffix]
        row_count, feature_count = count_file(target, fmt)
        write_file_meta(target, row_count, feature_count)
        item = item_from_file(target, source_label="Workspace data")
        if item is None:
            raise DatasetCatalogError("Imported file could not be cataloged")
        return item
