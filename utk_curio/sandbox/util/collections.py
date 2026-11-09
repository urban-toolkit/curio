"""The helpers node code uses to read a collection and write what it derives.

``curio_load_collection("<id>")`` returns a collection's index, one row per file,
with the columns a node needs to reach each file:

- ``path``: a file this execution can open: the file itself for a folder
  collection and for a bucket the deployment mounts, read in place there,
  else its cached copy for a bucket one (``None`` until cached);
- ``thumbnail`` and ``image_url``: URLs Simple View shows and HF CV
  Inference reads, served by id by the backend;
- ``audio_url``: a recording's URL, for a player.

A row of a ``files`` resource, kind ``file``, has none of those URLs: node
code reads the file from its ``path``.

``curio_derived_file(dataset_id, file_id, t_ms, ext)`` names a file a node
writes from one of a collection's files: a video's frame, a video made from a
video (an overlay of it, say), a table of what a node found in a video, a
recording's window, a photo's overlay. ``DERIVED`` lists what may be derived
from a file of each kind. A ``tag`` tells two derived files of one file and
time apart: an overlay's names the model that drew it. The backend serves the
file back under the same id (``DERIVED_ID_RE``). Both paths, in process and
isolated, build these from one function, so they cannot disagree.
"""

from __future__ import annotations

import os
import re

# A catalog item's id, as ``catalogCode.json`` (the frontend's contracts) has
# it: the sandbox reads no contract file, so this is its copy, which
# ``test_shared_constants.py`` holds equal to the table.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,199}$")
_FILE_ID = r"[0-9a-f]{16}"
_TAG = r"[0-9a-z]{1,32}"
_EXT = r"[0-9a-z]{1,8}"
_FILE_ID_RE = re.compile(rf"^{_FILE_ID}$")
_TAG_RE = re.compile(rf"^{_TAG}$")

#: A derived file's id, ``<fileId>@<t_ms>`` or ``<fileId>@<t_ms>-<tag>``, and
#: for a file of any type but its kind's first, its extension after that:
#: ``<fileId>@<t_ms>-<tag>.mp4``. What ``curio_derived_file`` names and the
#: media route looks up.
DERIVED_ID_RE = re.compile(rf"^({_FILE_ID})@([0-9]{{1,12}})(?:-({_TAG}))?(?:\.({_EXT}))?$")

#: The largest time a derived file's id holds: twelve digits of milliseconds.
_MAX_T_MS = 10**12 - 1

#: What a node may derive from a file of each kind, by the derived file's
#: extension: the folder it goes in, and the kind of its row. The first is
#: what ``ext=None`` derives, and its id names no extension. Any other's id
#: does, so a video's frame and a video made from it at one time and tag are
#: two ids, each naming one file.
DERIVED = {
    # A video's frame, a video made from it (an overlay, say), the overlay of
    # one of its frames, and a table of what a node found in it, which later
    # nodes read by its path and the media route does not serve.
    "video": {
        "jpg": ("frames", "frame"), "mp4": ("videos", "video"), "png": ("overlays", "image"),
        "parquet": ("tables", "table"),
    },
    "audio": {"wav": ("clips", "audio")},
    # A segmentation's overlay of a photo, or of a sequence's frame.
    "image": {"png": ("overlays", "image")},
    "frame": {"png": ("overlays", "image")},
}

#: The kinds of row the media route draws a thumbnail of: a collection's
#: files but those of a ``files`` resource, and the derived ones but a table.
DRAWN = ("image", "frame", "raster", "video", "audio")


def media_url(dataset_id, file_id, variant="thumb"):
    return f"/api/datasets/{dataset_id}/media/{file_id}?variant={variant}"


def media_urls(dataset_id, file_id, kind):
    """A row's ``thumbnail``, ``image_url`` and ``audio_url``, by the row's
    *kind*: what Simple View draws; the image a reader of images reads (the
    file itself, or a video's or a raster's thumbnail); a recording's file,
    for a player. None of them for a kind the media route draws nothing of:
    a table, and a ``file``, which node code reads from its ``path``. A
    collection's rows and a derived file's row get them here."""
    if kind not in DRAWN:
        return {"thumbnail": None, "image_url": None, "audio_url": None}
    thumbnail = media_url(dataset_id, file_id)
    original = media_url(dataset_id, file_id, "original")
    if kind in ("image", "frame"):
        image_url = original
    elif kind in ("raster", "video"):
        image_url = thumbnail
    else:
        image_url = None
    return {"thumbnail": thumbnail, "image_url": image_url, "audio_url": original if kind == "audio" else None}


def derived_type(kind, ext=None):
    """``(folder, ext, row kind, suffix)`` of what a node derives as *ext*
    from a *kind* file (``DERIVED``), the kind's first when *ext* is None.
    *suffix* is what the derived file's id holds after its stem: nothing for
    the kind's first type, ``.<ext>`` for any other.

    Raises ValueError for a kind nothing is derived from, and an ext its kind
    does not list: the media route would serve that file under no id."""
    types = DERIVED.get(kind)
    if types is None:
        raise ValueError(f"kind is the kind of the file it is derived from: {_one_of(DERIVED)}, not {kind!r}")
    first = next(iter(types))
    ext = first if ext is None else ext
    if ext not in types:
        raise ValueError(f"a node derives {_one_of(types)} from a file of kind {kind!r}, not {ext!r}")
    folder, row_kind = types[ext]
    return folder, ext, row_kind, "" if ext == first else f".{ext}"


def _one_of(values):
    """``'a', 'b' or 'c'``."""
    said = [repr(value) for value in values]
    return said[0] if len(said) == 1 else f"{', '.join(said[:-1])} or {said[-1]}"


def derived_stem(t_ms, tag=None):
    """``<t_ms>`` or ``<t_ms>-<tag>``: a derived file's name, and its id after the ``@``."""
    return f"{int(t_ms)}-{tag}" if tag is not None else f"{int(t_ms)}"


def derived_id(file_id, t_ms, tag=None, suffix=""):
    """The id a derived file is served under: ``<fileId>@<stem><suffix>``."""
    return f"{file_id}@{derived_stem(t_ms, tag)}{suffix}"


def derived_relpath(kind_folder, dataset_id, file_id, t_ms, ext, tag=None):
    """``<folder>/<datasetId>/<fileId>/<stem>.<ext>`` under the media directory."""
    return os.path.join(kind_folder, dataset_id, file_id, f"{derived_stem(t_ms, tag)}.{ext}")


_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: The columns that say where a file is rather than what it is, last.
LOCATOR_COLUMNS = (
    "file_id", "relpath", "ext", "bytes", "mtime", "dataset_id", "path",
    "thumbnail", "image_url", "audio_url",
)


def make_collection_helpers(resolve_index, collections, media_dir, *, output_dir=None, output_names=None):
    """The helpers for one execution: ``curio_load_collection``,
    ``curio_derived_file``, ``curio_output_file`` and ``curio_export``.

    *resolve_index(dataset_id)* returns the local path of a collection's index,
    the same resolver ``curio_data_path`` uses. *collections* maps each id
    the backend resolved to ``{root|objects, kind}``: a mounted bucket's
    ``root`` is its mount's folder, where a file's path is ``tail`` and its
    relpath, and ``unavailable`` says why its mount cannot be read now. *output_dir* is where a
    node writes a file it returns (a raster, say): the scratch directory when
    isolated, whose files the parent keeps, and the run's own folder in
    process (``util/output_files.py``); without one, the media directory's
    ``outputs``. *output_names*, a list, gets each name ``curio_output_file``
    gives, which an isolated child reports to its parent.
    """
    known = dict(collections or {})

    def curio_load_collection(dataset_id):
        dataset_id = str(dataset_id)
        entry = known.get(dataset_id)
        if entry is None:
            raise RuntimeError(
                f"Collection '{dataset_id}' is not available in this environment - "
                "add it from the Discovery Catalog, then run this node again."
            )
        if entry.get("unavailable"):
            raise RuntimeError(
                f"Collection '{dataset_id}' is read in place from its bucket, which cannot be read now: "
                f"{entry['unavailable']}"
            )
        index_path = resolve_index(dataset_id)
        import pandas as pd

        try:
            import geopandas as gpd

            frame = gpd.read_parquet(index_path)
        except Exception:  # noqa: BLE001 - an index without positions
            frame = pd.read_parquet(index_path)
        root, objects = entry.get("root"), entry.get("objects")
        # A mounted bucket's prefix may end partway through a name, which
        # every file's path in the mount then starts with.
        tail = str(entry.get("tail") or "")

        def where(row):
            if root:
                relpath = str(row["relpath"])
                # An index lists files under its root; a row that says
                # otherwise has no file here.
                if any(part in ("", ".", "..") for part in relpath.split("/")):
                    return None
                return os.path.join(root, *(tail + relpath).split("/"))
            if objects:
                name = f"{row['file_id']}.{row['ext']}" if row["ext"] else row["file_id"]
                path = os.path.join(objects, name)
                return path if os.path.isfile(path) else None
            return None

        frame["dataset_id"] = dataset_id
        # Kept as objects, so a file not here reads None: pandas would store a
        # column of strings with NaN for it, which is truthy.
        frame["path"] = pd.Series([where(row) for _, row in frame.iterrows()], index=frame.index, dtype=object)
        urls = [media_urls(dataset_id, fid, kind) for fid, kind in zip(frame["file_id"], frame["kind"])]
        for column in ("thumbnail", "image_url", "audio_url"):
            frame[column] = [row_urls[column] for row_urls in urls]
        # What a reader looks for first (the name, the path fields, what was
        # read from the file) ahead of the columns that locate the file, which
        # is also the order a Simple View card captions a row in.
        last = [c for c in LOCATOR_COLUMNS if c in frame.columns]
        return frame[[c for c in frame.columns if c not in last] + last]

    def curio_derived_file(dataset_id, file_id, t_ms, ext=None, *, kind="video", tag=None):
        """Where to write a file derived from one file of a collection, and its row.

        *kind* is that file's kind and *ext* what is derived from it
        (``DERIVED``): from a video, its frame at *t_ms* (``jpg``, the
        default), a video made from it that starts at *t_ms* (``mp4``), the
        overlay of its frame at *t_ms* (``png``), or a table of what a node
        found in it (``parquet``); a recording's clip (``wav``); an image's
        or a frame's overlay (``png``). *tag*, up to 32 lowercase letters and
        digits, tells two derived files of one file and time apart, as the
        model that drew an overlay does.

        Returns the row the media route serves it under, with the columns a
        collection's row of its kind has: ``file_id``, ``dataset_id``,
        ``kind``, ``path``, ``thumbnail``, ``image_url`` and ``audio_url``,
        the last three None for a table, which later nodes read by its
        ``path``. The directory exists when this returns; the node writes the
        bytes to ``path``.
        """
        dataset_id, file_id = str(dataset_id), str(file_id)
        if not _ID_RE.match(dataset_id) or not _FILE_ID_RE.match(file_id):
            raise ValueError("not a collection file")
        if tag is not None and not _TAG_RE.match(str(tag)):
            raise ValueError("a derived file's tag is 1 to 32 lowercase letters and digits")
        if not 0 <= int(t_ms) <= _MAX_T_MS:
            raise ValueError("t_ms is a time in the file, in milliseconds from its start")
        folder, ext, row_kind, suffix = derived_type(kind, ext)
        if not media_dir:
            raise RuntimeError(
                "This node cannot write derived files here - run it on a collection "
                "loaded with curio_load_collection()."
            )
        path = os.path.join(media_dir, derived_relpath(folder, dataset_id, file_id, t_ms, ext, tag))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        served_as = derived_id(file_id, t_ms, tag, suffix)
        return {
            "file_id": served_as, "dataset_id": dataset_id, "kind": row_kind, "path": path,
            **media_urls(dataset_id, served_as, row_kind),
        }

    def curio_output_file(name):
        """A path to write a file this node returns, such as a mosaic's VRT."""
        name = str(name)
        if not _OUTPUT_NAME_RE.match(name):
            raise ValueError("an output file name is one plain name, like mosaic.vrt")
        folder = output_dir or (os.path.join(media_dir, "outputs") if media_dir else None)
        if not folder:
            raise RuntimeError("This node has nowhere to write an output file.")
        os.makedirs(folder, exist_ok=True)
        if output_names is not None and name not in output_names:
            output_names.append(name)
        return os.path.join(folder, name)

    def curio_export(data, name="", part=None):
        """Write *data* to a file of this node's (``curio_output_file``) and
        return the file's name: a table as CSV, a GeoDataFrame as GeoJSON, a
        raster as GeoTIFF, a tuple, list or dict that holds a table or a
        raster as one zip of its parts, anything else as JSON. *part* writes
        the one part its label, key or position names (``util/exports.py``)."""
        from utk_curio.sandbox.util.exports import export

        return export(data, name, curio_output_file, part)

    return {
        "curio_load_collection": curio_load_collection,
        "curio_derived_file": curio_derived_file,
        "curio_output_file": curio_output_file,
        "curio_export": curio_export,
    }
