"""Workspace and sample-data dataset repository."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from utk_curio.backend.app.datasets.catalog_items import format_for_path, item_from_file
from utk_curio.backend.app.datasets.catalog_utils import iso_from_timestamp
from utk_curio.backend.app.datasets.constants import SUPPORTED_SUFFIXES
from utk_curio.backend.app.datasets.errors import DatasetCatalogError
from utk_curio.backend.app.datasets.file_meta import count_file, meta_path, write_file_meta

class LocalDatasetRepository:
    def _roots(self) -> list[tuple[str, Path]]:
        launch_dir = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd()))
        package_data = Path(__file__).resolve().parents[3] / "data"
        return [
            ("Curio sample data", package_data),
            ("Workspace data", launch_dir / "data"),
        ]

    def list_items(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for source_label, root in self._roots():
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.iterdir()):
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
