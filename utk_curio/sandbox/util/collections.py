"""The helpers node code uses to read a collection and write what it derives.

``curio_collection("<id>")`` returns a collection's index, one row per file,
with the columns a node needs to reach each file:

- ``path``: a file this execution can open, the file itself for a folder
  collection, its cached copy for a bucket one (``None`` until cached);
- ``thumbnail`` and ``image_url``: URLs Simple View shows and HF CV
  Inference reads, served by id by the backend;
- ``audio_url``: a recording's URL, for a player.

``curio_derived_file(dataset_id, file_id, t_ms, ext)`` names a file a node
writes from one of a collection's files: a video's frame, a recording's
window. The backend serves it back under the same id. Both paths, in process
and isolated, build these from one function, so they cannot disagree.
"""

from __future__ import annotations

import os
import re

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$")
_FILE_ID_RE = re.compile(r"^[0-9a-f]{16}$")

#: What a derived file of each source kind is, and where it goes.
DERIVED = {
    "video": ("frames", "jpg", "frame"),
    "audio": ("clips", "wav", "audio"),
}


def media_url(dataset_id, file_id, variant="thumb"):
    return f"/api/datasets/{dataset_id}/media/{file_id}?variant={variant}"


def derived_relpath(kind_folder, dataset_id, file_id, t_ms, ext):
    """``<folder>/<datasetId>/<fileId>/<t_ms>.<ext>`` under the media directory."""
    return os.path.join(kind_folder, dataset_id, file_id, f"{int(t_ms)}.{ext}")


_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: The columns that say where a file is rather than what it is, last.
LOCATOR_COLUMNS = (
    "file_id", "relpath", "ext", "bytes", "mtime", "dataset_id", "path",
    "thumbnail", "image_url", "audio_url",
)


def make_collection_helpers(resolve_index, collections, media_dir, *, output_dir=None):
    """The helpers for one execution: ``curio_collection``,
    ``curio_derived_file`` and ``curio_output_file``.

    *resolve_index(dataset_id)* returns the local path of a collection's index,
    the same resolver ``curio_dataset_path`` uses. *collections* maps each id
    the backend resolved to ``{root|objects, kind}``. *output_dir* is where a
    node writes a file it returns (a raster, say): the scratch directory when
    isolated, whose files the parent keeps, and the media directory otherwise.
    """
    known = dict(collections or {})

    def curio_collection(dataset_id):
        dataset_id = str(dataset_id)
        entry = known.get(dataset_id)
        if entry is None:
            raise RuntimeError(
                f"Collection '{dataset_id}' is not available in this environment - "
                "add it from the Data Lake Catalog, then run this node again."
            )
        index_path = resolve_index(dataset_id)
        import pandas as pd

        try:
            import geopandas as gpd

            frame = gpd.read_parquet(index_path)
        except Exception:  # noqa: BLE001 - an index without positions
            frame = pd.read_parquet(index_path)
        root, objects = entry.get("root"), entry.get("objects")

        def where(row):
            if root:
                parts = str(row["relpath"]).split("/")
                # An index lists files under its root; a row that says
                # otherwise has no file here.
                if any(part in ("", ".", "..") for part in parts):
                    return None
                return os.path.join(root, *parts)
            if objects:
                name = f"{row['file_id']}.{row['ext']}" if row["ext"] else row["file_id"]
                path = os.path.join(objects, name)
                return path if os.path.isfile(path) else None
            return None

        frame["dataset_id"] = dataset_id
        frame["path"] = [where(row) for _, row in frame.iterrows()]
        frame["thumbnail"] = [media_url(dataset_id, fid) for fid in frame["file_id"]]
        kinds = list(frame["kind"])
        frame["image_url"] = [
            media_url(dataset_id, fid, "original") if kind in ("image", "frame") else
            (media_url(dataset_id, fid) if kind in ("raster", "video") else None)
            for fid, kind in zip(frame["file_id"], kinds)
        ]
        frame["audio_url"] = [
            media_url(dataset_id, fid, "original") if kind == "audio" else None
            for fid, kind in zip(frame["file_id"], kinds)
        ]
        # What a reader looks for first (the name, the path fields, what was
        # read from the file) ahead of the columns that locate the file, which
        # is also the order a Simple View card captions a row in.
        last = [c for c in LOCATOR_COLUMNS if c in frame.columns]
        return frame[[c for c in frame.columns if c not in last] + last]

    def curio_derived_file(dataset_id, file_id, t_ms, ext=None, *, kind="video"):
        """Where to write the frame (or clip) at *t_ms* of one file, and its row.

        Returns ``{"file_id", "path", "thumbnail", "image_url"|"audio_url"}``.
        The directory exists when this returns; write the bytes to ``path``.
        """
        dataset_id, file_id = str(dataset_id), str(file_id)
        if not _ID_RE.match(dataset_id) or not _FILE_ID_RE.match(file_id):
            raise ValueError("not a collection file")
        if not media_dir:
            raise RuntimeError(
                "This node cannot write derived files here - run it on a collection "
                "loaded with curio_collection()."
            )
        folder, default_ext, _row_kind = DERIVED.get(kind, DERIVED["video"])
        path = os.path.join(media_dir, derived_relpath(folder, dataset_id, file_id, t_ms, ext or default_ext))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        derived_id = f"{file_id}@{int(t_ms)}"
        row = {"file_id": derived_id, "path": path, "thumbnail": media_url(dataset_id, derived_id)}
        if kind == "audio":
            row["audio_url"] = media_url(dataset_id, derived_id, "original")
        else:
            row["image_url"] = media_url(dataset_id, derived_id, "original")
        return row

    def curio_output_file(name):
        """A path to write a file this node returns, such as a mosaic's VRT."""
        name = str(name)
        if not _OUTPUT_NAME_RE.match(name):
            raise ValueError("an output file name is one plain name, like mosaic.vrt")
        folder = output_dir or (os.path.join(media_dir, "outputs") if media_dir else None)
        if not folder:
            raise RuntimeError("This node has nowhere to write an output file.")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, name)

    return {
        "curio_collection": curio_collection,
        "curio_derived_file": curio_derived_file,
        "curio_output_file": curio_output_file,
    }
