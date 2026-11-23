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
writes from one of a collection's files, of any kind: an image, a video or a
recording, of any extension of the families a collection's own files are
sorted by (``FAMILIES``), such as a video's frame, a video made from a video
(an overlay of it, say), a recording's window, a photo's overlay or a picture
of a raster tile. A table a node finds in a file is the node's output, never
a derived file. A ``tag`` tells apart two files one run derives from one file
at one time. The backend serves the file back
under the same id (``DERIVED_ID_RE``). A dashboard viewer's step writes in a
folder of its own (``KEPT_MEDIA``), which the URLs of the rows it derives name
(``?kept=<name>``), so a row is read from where its run wrote it. Both paths,
in process and isolated, build these from one function, so they cannot
disagree.
"""

from __future__ import annotations

import os
import re
from urllib.parse import parse_qsl

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
#: for a file of any extension but its kind's own, that extension after it:
#: ``<fileId>@<t_ms>-<tag>.mp4``. What ``curio_derived_file`` names and the
#: media route looks up.
DERIVED_ID_RE = re.compile(rf"^({_FILE_ID})@([0-9]{{1,12}})(?:-({_TAG}))?(?:\.({_EXT}))?$")

#: The largest time a derived file's id holds: twelve digits of milliseconds.
_MAX_T_MS = 10**12 - 1

#: The extensions of the three families of file a collection's own files are
#: sorted by, which the backend reads from here (``probe.file_kind``, and the
#: files a resource takes by default, ``DEFAULT_EXTENSIONS`` in
#: ``discovery/domain/manifest.py``): every file a node derives is of one.
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff")
VIDEO_EXTENSIONS = ("mp4", "mov", "m4v", "webm", "mkv", "avi")
AUDIO_EXTENSIONS = ("wav", "flac", "mp3", "ogg", "opus", "m4a", "aiff", "aif")

#: The kind of the row of a file a node derives, by its extension's family:
#: an image a Simple View card shows, a video or a recording it plays.
FAMILIES = {"image": IMAGE_EXTENSIONS, "video": VIDEO_EXTENSIONS, "audio": AUDIO_EXTENSIONS}

#: The kinds of row the media route draws a thumbnail of: a collection's
#: files but those of a ``files`` resource, and the derived ones.
DRAWN = ("image", "frame", "raster", "video", "audio")

#: Every kind of a collection's row (``probe.file_kind``), each a kind of file
#: a node derives from: those the media route draws, and a ``files`` resource's.
ROW_KINDS = DRAWN + ("file",)

#: What a node derives from a file of each kind when it names no extension,
#: and the kind of its row: a video's frame, a recording's clip, a photo's or
#: a frame's overlay. Its id names no extension, whether that one is named or
#: not; any other's id does, so a video's frame and a video made from it at
#: one time and tag are two ids, each naming one file. A raster or a ``files``
#: row has none, and names what it derives.
DERIVED_DEFAULTS = {
    "video": ("jpg", "frame"),
    "audio": ("wav", "audio"),
    "image": ("png", "image"),
    "frame": ("png", "image"),
}

#: The folder in the media directory of the files a node derives, by their
#: row's kind, whatever kind of file they come from: ``forget_media`` empties
#: each of a collection's.
DERIVED_FOLDERS = {"frame": "frames", "image": "overlays", "video": "videos", "audio": "clips"}

#: In an account's media folder, the folder of each dashboard viewer's step's
#: own, ``<media>/kept/<name>/``, which the backend makes the step's media
#: directory (``media_dirs.derived_root``): what a viewer's run derives is
#: written there, never where the owner's runs write theirs under the same
#: ids. The rows such a step derives name the folder in their URLs
#: (``?kept=<name>``), so a row is read from where its run wrote it, whoever
#: reads it and however many steps it passes through.
KEPT_MEDIA = "kept"

#: The name of such a folder: a digest of its step's kept session
#: (``media_dirs.kept_media_name``), never the session itself.
KEPT_NAME_RE = re.compile(r"^k[0-9a-f]{32}$")


def kept_of(media_dir):
    """The name of the folder of a dashboard viewer's step that *media_dir*
    is (``<media>/kept/<name>``, ``KEPT_MEDIA``), or None for any other media
    directory: an account's own, or a hosted guest's folder in it."""
    if not media_dir:
        return None
    parent, name = os.path.split(os.path.normpath(str(media_dir)))
    if os.path.basename(parent) == KEPT_MEDIA and KEPT_NAME_RE.match(name):
        return name
    return None


def media_url(dataset_id, file_id, variant="thumb", kept=None):
    """The media route's URL of one file, ``variant`` its ``thumb``,
    ``poster`` or ``original``; *kept* names the folder of the dashboard
    viewer's step that derived it (``KEPT_MEDIA``)."""
    url = f"/api/datasets/{dataset_id}/media/{file_id}?variant={variant}"
    return f"{url}&kept={kept}" if kept else url


#: A URL :func:`media_url` writes: the collection, the file's id, the query.
_MEDIA_URL_RE = re.compile(r"^/api/datasets/([A-Za-z0-9][A-Za-z0-9._@-]{0,199})/media/([^/?#]+)(?:\?([^#]*))?$")


def media_ref(text):
    """``(dataset_id, file_id, kept)`` of the file *text* names, a URL
    :func:`media_url` writes, *kept* None for a file no dashboard viewer's
    step derived; None for any other text."""
    if not isinstance(text, str) or not text.startswith("/api/datasets/"):
        return None
    found = _MEDIA_URL_RE.match(text)
    if found is None:
        return None
    dataset_id, file_id, query = found.groups()
    if not (_FILE_ID_RE.match(file_id) or DERIVED_ID_RE.match(file_id)):
        return None
    kept = dict(parse_qsl(query or "")).get("kept")
    if kept is not None and not KEPT_NAME_RE.match(kept):
        return None
    return dataset_id, file_id, kept


def media_refs(value):
    """Every file the media URLs anywhere in *value*, an output's envelope as
    ``/get`` sends it, name (:func:`media_ref`): in any column, cell, list,
    property or part, as a set of ``(dataset_id, file_id, kept)``. A
    feature's ``geometry`` holds no URL, and is not read."""
    found = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            ref = media_ref(item)
            if ref is not None:
                found.add(ref)
        elif isinstance(item, dict):
            stack.extend(each for key, each in item.items() if key != "geometry")
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return found


def media_urls(dataset_id, file_id, kind, kept=None):
    """A row's ``thumbnail``, ``image_url`` and ``audio_url``, by the row's
    *kind*: what Simple View draws; the image a reader of images reads (the
    file itself, or a video's or a raster's thumbnail); a recording's file,
    for a player. None of them for a kind the media route draws nothing of:
    a ``file``, which node code reads from its ``path``. A collection's rows
    and a derived file's row get them here; *kept* is the
    folder a dashboard viewer's step derived the file in (``KEPT_MEDIA``)."""
    if kind not in DRAWN:
        return {"thumbnail": None, "image_url": None, "audio_url": None}
    thumbnail = media_url(dataset_id, file_id, kept=kept)
    original = media_url(dataset_id, file_id, "original", kept=kept)
    if kind in ("image", "frame"):
        image_url = original
    elif kind in ("raster", "video"):
        image_url = thumbnail
    else:
        image_url = None
    return {"thumbnail": thumbnail, "image_url": image_url, "audio_url": original if kind == "audio" else None}


def derived_type(kind, ext=None):
    """``(folder, ext, row kind, suffix)`` of what a node derives as *ext* from
    a file of *kind*, any kind of a collection's row (``ROW_KINDS``): an image,
    a video or a recording, by the family of its extension (``FAMILIES``), and
    with no *ext* the kind's own file (``DERIVED_DEFAULTS``), the one whose row
    may be a ``frame``. *suffix* is what the derived file's id holds after its
    stem: nothing for the kind's own file, ``.<ext>`` for any other.

    Raises ValueError for a kind no row has, for no *ext* from a raster or a
    ``files`` row, and for an *ext* of no family, a table's among them: the
    media route would serve that file under no id, and a table is the node's
    output, which it returns, as it writes any other file it returns with
    ``curio_output_file``."""
    if kind not in ROW_KINDS:
        raise ValueError(f"kind is the kind of the file it is derived from: {_one_of(ROW_KINDS)}, not {kind!r}")
    own, own_kind = DERIVED_DEFAULTS.get(kind, (None, None))
    if ext is None:
        if own is None:
            raise ValueError(
                f"a file of kind {kind!r} derives no file of its own: ext names the extension of the image, "
                "the video or the recording derived from it"
            )
        ext = own
    if ext == own:
        return DERIVED_FOLDERS[own_kind], ext, own_kind, ""
    row_kind = next((family for family, extensions in FAMILIES.items() if ext in extensions), None)
    if row_kind is None:
        raise ValueError(
            f"a node derives an image ({_one_of(IMAGE_EXTENSIONS)}), a video ({_one_of(VIDEO_EXTENSIONS)}) "
            f"or a recording ({_one_of(AUDIO_EXTENSIONS)}) from a collection's file, not {ext!r}: "
            "return a table from the node as its output, or write any other file it returns with curio_output_file"
        )
    return DERIVED_FOLDERS[row_kind], ext, row_kind, f".{ext}"


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


def collection_rows(frame, dataset_id, entry):
    """Rows of collection *dataset_id*'s index, *frame*, as
    ``curio_load_collection`` gives them to node code: with ``dataset_id``,
    ``path``, ``thumbnail``, ``image_url`` and ``audio_url``, and the columns
    that locate a file last. *entry* is where its files are for this
    execution, one of ``make_collection_helpers``'s *collections*. The Data
    Catalog's preview of the index shows its rows through this too."""
    import pandas as pd

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
    gives, which an isolated child reports to its parent. A *media_dir* that
    is a dashboard viewer's step's own folder (``KEPT_MEDIA``) is named in
    the URLs of every row ``curio_derived_file`` gives.
    """
    known = dict(collections or {})
    kept = kept_of(media_dir)

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
        return collection_rows(frame, dataset_id, entry)

    def curio_derived_file(dataset_id, file_id, t_ms, ext=None, *, kind="video", tag=None):
        """Where to write a file derived from one file of a collection, and its row.

        *kind* is that file's kind, any a collection's row has (``ROW_KINDS``),
        and *ext* the extension of what is derived from it: an image, a video
        or a recording, of any extension of the families a collection's files
        are sorted by (``FAMILIES``), such as a video made from a video that
        starts at *t_ms* (``mp4``) or the overlay of its frame at *t_ms*
        (``png``). With no *ext*, a video derives its frame at *t_ms*
        (``jpg``), a recording its clip (``wav``), and an image or a frame its
        overlay (``png``); a raster or a ``files`` row names *ext*. A table is
        no derived file but the node's output, which it returns, and any other
        file it returns is written with ``curio_output_file``. *tag*, up to 32
        lowercase letters and digits, tells apart two files the run derives
        from one file at one time, such as two pictures of one frame.

        Returns the row the media route serves it under, with the columns a
        collection's row of its kind has: ``file_id``, ``dataset_id``,
        ``kind``, ``path``, ``thumbnail``, ``image_url`` and ``audio_url``. A
        dashboard viewer's step's URLs name its own folder (``kept``), where
        it writes. The directory exists when this returns; the node writes the
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
            **media_urls(dataset_id, served_as, row_kind, kept),
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
