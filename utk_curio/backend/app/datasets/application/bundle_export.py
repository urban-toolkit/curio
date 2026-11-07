"""A dataset of several parts, exported as one zip (#1335).

The Data Catalog's Export of a bundle, of a node's live output of several
parts, or of a layer group gives the zip the sandbox's writer makes
(``sandbox/util/bundle_zip.py``), the one a Data Export node fed the same
parts writes: a file per part named after its label, and ``bundle.json``.

- A saved bundle: its parts as its ``bundle.json`` lists and labels them.
- A live output of several parts (a tuple, or a list or dict that holds
  frames): its parts as the store holds them, labelled as saving the output
  labels them (``install.bundle.resolve_output_bundle_parts``). The caller
  checks first that it may read the output, as for a single live file.
- A layer group: the dict of its layers by name that ``curio_load_data``
  gives for it (``layer_group.named_layers``), each read as its own id is.

Each part is read only when the zip writes it. The zip is written to a folder
of its own, which goes once the download is sent (``cleanup``); a part the
zip cannot hold, or one that is gone, is refused and leaves nothing.
"""

from __future__ import annotations

import functools
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.datasets.application.export import _download_name
from utk_curio.backend.app.datasets.domain.errors import DatasetCatalogError

#: What a zip is served as.
ZIP_MIMETYPE = "application/zip"


def _zip_target(title: str, parts_of: Callable[[], tuple[str, list]]) -> dict[str, Any]:
    """Write the zip of the parts *parts_of* gives, as ``download_target``
    answers: the file, its name ``<title>.zip``, and the folder to remove
    once it is sent."""
    from utk_curio.sandbox.util.bundle_zip import write_zip

    folder = Path(tempfile.mkdtemp(prefix="curio-export-"))
    path = folder / "export.zip"
    try:
        write_zip(str(path), *parts_of())
    except ValueError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise DatasetCatalogError(f"This dataset cannot be exported as a zip: {exc}", 400) from exc
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return {
        "download_name": _download_name(title, ".zip"),
        "mimetype": ZIP_MIMETYPE,
        "path": str(path),
        "cleanup": str(folder),
    }


def saved_bundle_zip(title: str, bundle_path: str) -> dict[str, Any]:
    """The zip of the bundle dataset whose ``bundle.json`` is *bundle_path*."""
    from utk_curio.sandbox.util.bundle_zip import saved_bundle_parts

    return _zip_target(title, lambda: saved_bundle_parts(bundle_path))


def _gone() -> DatasetCatalogError:
    return DatasetCatalogError("A part of this output is gone: run its node again to export it.", 404)


def _read_stored_part(part) -> Any:
    """The value the store holds for *part* (``install.bundle.BundlePart``),
    as a node after it reads it (``parsers.load_from_duckdb``)."""
    from utk_curio.backend.app.datasets.install.bundle import (
        FRAME_KINDS,
        ROW_ONLY_KINDS,
        _artifact_value_row,
        _frame_meta,
        _row_value,
    )

    if part.kind in ROW_ONLY_KINDS:
        row = _artifact_value_row(part.artifact_id)
        if row is None:
            raise _gone()
        return _row_value(part.kind, row)
    source = part.source_path
    if source is None or not source.is_file():
        raise _gone()
    if part.kind in FRAME_KINDS:
        from utk_curio.sandbox.util import codec

        _metadata, encoded = _frame_meta(part.meta_json)
        if part.kind == "geodataframe":
            import geopandas as gpd

            frame = gpd.read_parquet(source)
            return codec._restore_frame_from_parquet(frame, encoded, geometry_col=codec.active_geometry_name(frame))
        import pandas as pd

        return codec._restore_frame_from_parquet(pd.read_parquet(source), encoded)
    if part.kind == "raster":
        import rasterio

        return rasterio.open(source)
    if part.kind in ("list", "dict"):
        raw = source.read_bytes()
        if source.name.endswith(".zlib"):
            import zlib

            raw = zlib.decompress(raw)
        return json.loads(raw.decode("utf-8"))
    raise DatasetCatalogError(f"A part of this output is a {part.kind}, which a zip cannot hold.", 400)


def live_bundle_zip(title: str, art_id: str) -> dict[str, Any] | None:
    """The zip of the live output *art_id* of several parts, or None when it
    is not one. The caller has checked that it may read the output."""
    from utk_curio.backend.app.datasets.infrastructure import sandbox_artifacts
    from utk_curio.backend.app.datasets.install.bundle import (
        BUNDLE_CONTAINERS,
        resolve_output_bundle_parts,
    )
    from utk_curio.sandbox.util.bundle_zip import Part

    row = sandbox_artifacts.artifact_row(art_id)
    container = BUNDLE_CONTAINERS.get(row[0]) if row else None
    if container is None:
        return None
    try:
        children = json.loads(row[4]) if isinstance(row[4], str) else row[4]
    except (TypeError, ValueError):
        children = None
    parts = resolve_output_bundle_parts(art_id)
    if not isinstance(children, (list, dict)) or not parts or len(parts) != len(children):
        raise _gone()

    def parts_of():
        return container, [
            Part(index=index, label=part.label, key=part.key if container == "dict" else None,
                 read=functools.partial(_read_stored_part, part))
            for index, part in enumerate(parts)
        ]

    return _zip_target(title, parts_of)


def layer_group_zip(
    title: str, members: list[dict[str, Any]], resolve: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    """The zip of a layer group whose layers are *members*, in its order: a
    dict of its layers by name, each read as ``curio_load_data`` reads its
    id, from the file *resolve* gives its item."""
    from utk_curio.backend.app.datasets.domain.catalog_item import execution_format
    from utk_curio.backend.app.datasets.domain.layer_group import named_layers
    from utk_curio.sandbox.util.bundle_zip import Part
    from utk_curio.sandbox.util.catalog_helpers import read_dataset

    by_id = {member.get("id"): member for member in members}
    layers = []
    for index, (name, member_id) in enumerate(named_layers(members)):
        member = by_id[member_id]
        path = resolve(member)
        if not path or not Path(path).is_file():
            raise DatasetCatalogError(f"The layer {name} of this group is not available for export.", 404)
        how = execution_format(member)
        layers.append(Part(
            index=index, label=name, key=name,
            read=functools.partial(read_dataset, path, how.get("format"), layer_type=how.get("layerType")),
        ))
    return _zip_target(title, lambda: ("dict", layers))
