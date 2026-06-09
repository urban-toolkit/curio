"""Tabular and bundle preview for catalog datasets."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

class DatasetPreviewService:
    def preview(self, item: dict[str, Any], *, row_limit: int = 50, offset: int = 0) -> dict[str, Any]:
        path_value = item.get("path")
        if not path_value or str(path_value).startswith("curio://"):
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
                "truncated": False,
                "unsupported": True,
                "message": "Preview is available after the dataset is installed or computed locally.",
            }

        path = Path(path_value)
        if not path.exists() or not path.is_file():
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
                "truncated": False,
                "unsupported": True,
                "message": "Dataset file is not available on disk.",
            }

        fmt = item.get("format")
        if fmt == "bundle":
            return self._preview_bundle(path, row_limit, offset, item)
        if fmt == "csv":
            return self._preview_csv(path, row_limit, offset, item)
        if fmt == "json":
            return self._preview_json(path, row_limit, offset, item)
        if fmt == "geojson":
            return self._preview_geojson(path, row_limit, offset, item)
        if fmt == "parquet":
            return self._preview_parquet(path, row_limit, offset, item)
        if fmt == "geotiff":
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": 0,
                "truncated": False,
                "unsupported": True,
                "message": "Raster preview is not available in the catalog yet. Use the map canvas.",
            }
        return {
            "schema": {"fields": []},
            "rows": [],
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
            "truncated": False,
            "unsupported": True,
            "message": f"Preview is not supported for {fmt} datasets yet.",
        }

    def _total_rows(self, item: dict[str, Any], computed: int | None) -> int:
        if computed is not None:
            return computed
        return int(item.get("featureCount") or item.get("rowCount") or 0)

    def _count_csv_rows(self, path: Path) -> int:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return sum(1 for _ in reader)

    def _infer_fields(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []
        names: list[str] = []
        for row in rows:
            for key in row.keys():
                if key not in names:
                    names.append(key)
        fields = []
        for name in names:
            sample = next((row.get(name) for row in rows if row.get(name) not in (None, "")), None)
            field_type = "string"
            if isinstance(sample, bool):
                field_type = "boolean"
            elif isinstance(sample, int):
                field_type = "integer"
            elif isinstance(sample, float):
                field_type = "number"
            fields.append({"name": name, "type": field_type, "nullable": True, "sample": sample})
        return fields

    def _preview_bundle(self, bundle_path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        try:
            spec = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": 0,
                "truncated": False,
                "bundle": True,
                "parts": [],
                "unsupported": True,
                "message": f"Could not read bundle manifest: {exc}",
            }

        root = bundle_path.parent
        parts_payload: list[dict[str, Any]] = []
        for part in spec.get("parts") or []:
            if not isinstance(part, dict):
                continue
            label = str(part.get("label") or f"Part {part.get('index', 0)}")
            fmt = str(part.get("format") or "json")
            rel = part.get("file")
            part_path = (root / rel).resolve() if rel else None
            sub_item = {**item, "format": fmt}
            if part_path is not None and part_path.is_file():
                if fmt == "csv":
                    part_preview = self._preview_csv(part_path, row_limit, 0, sub_item)
                elif fmt == "parquet":
                    part_preview = self._preview_parquet(part_path, row_limit, 0, sub_item)
                elif fmt == "geojson":
                    part_preview = self._preview_geojson(part_path, row_limit, 0, sub_item)
                elif fmt == "geotiff":
                    part_preview = {
                        "schema": {"fields": []},
                        "rows": [],
                        "rowLimit": row_limit,
                        "offset": 0,
                        "totalRows": 0,
                        "truncated": False,
                        "unsupported": True,
                        "message": "Raster preview is not available in the catalog yet.",
                    }
                else:
                    part_preview = self._preview_json(part_path, row_limit, 0, sub_item)
            else:
                part_preview = {
                    "schema": {"fields": []},
                    "rows": [],
                    "rowLimit": row_limit,
                    "offset": 0,
                    "totalRows": 0,
                    "truncated": False,
                    "unsupported": True,
                    "message": "Part file is not available on disk.",
                }
            parts_payload.append({
                "label": label,
                "format": fmt,
                "kind": part.get("kind"),
                **part_preview,
            })

        part_count = len(parts_payload)
        schema = item.get("schema") or {
            "fields": [{"name": "parts", "type": "integer", "nullable": False, "sample": part_count}],
            "bundleParts": [
                {"label": p.get("label"), "format": p.get("format")}
                for p in parts_payload
            ],
        }
        return {
            "schema": schema,
            "rows": [],
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": part_count,
            "truncated": False,
            "bundle": True,
            "parts": parts_payload,
        }

    def _preview_csv(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        total_rows = self._count_csv_rows(path)
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                if index < offset:
                    continue
                if len(rows) >= row_limit:
                    break
                rows.append(dict(row))
        end = offset + len(rows)
        return {
            "schema": {"fields": self._infer_fields(rows) if rows else (item.get("schema") or {}).get("fields", [])},
            "rows": rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }

    def _preview_json(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else [{"value": data}]
        total_rows = len(rows)
        page = rows[offset : offset + row_limit]
        display_rows = [row if isinstance(row, dict) else {"value": row} for row in page]
        end = offset + len(display_rows)
        return {
            "schema": {"fields": self._infer_fields(display_rows) if display_rows else (item.get("schema") or {}).get("fields", [])},
            "rows": display_rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }

    def _preview_parquet(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        from utk_curio.sandbox.util.tabular_preview import preview_parquet_file

        try:
            rows, total_rows, _parsed = preview_parquet_file(
                path,
                row_limit=row_limit,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "schema": item.get("schema") or {"fields": []},
                "rows": [],
                "rowLimit": row_limit,
                "offset": offset,
                "totalRows": item.get("featureCount") or item.get("rowCount") or 0,
                "truncated": False,
                "unsupported": True,
                "message": f"Could not read parquet preview: {exc}",
            }

        end = offset + len(rows)
        schema_fields = (item.get("schema") or {}).get("fields", [])
        return {
            "schema": {
                "fields": schema_fields if schema_fields else self._infer_fields(rows),
            },
            "rows": rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }

    def _preview_geojson(self, path: Path, row_limit: int, offset: int, item: dict[str, Any]) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        features = data.get("features", []) if isinstance(data, dict) else []
        total_rows = len(features)
        rows = []
        geometry_type = None
        for feature in features[offset : offset + row_limit]:
            props = feature.get("properties") or {}
            geom = feature.get("geometry") or {}
            geometry_type = geometry_type or geom.get("type")
            rows.append({**props, "geometry": geom.get("type")})
        end = offset + len(rows)
        schema_fields = self._infer_fields(rows) if rows else (item.get("schema") or {}).get("fields", [])
        return {
            "schema": {
                "fields": schema_fields,
                "geometryType": geometry_type or (item.get("schema") or {}).get("geometryType"),
                "crs": data.get("crs", {}).get("properties", {}).get("name") if isinstance(data, dict) else None,
            },
            "rows": rows,
            "rowLimit": row_limit,
            "offset": offset,
            "totalRows": self._total_rows(item, total_rows),
            "truncated": end < self._total_rows(item, total_rows),
        }
