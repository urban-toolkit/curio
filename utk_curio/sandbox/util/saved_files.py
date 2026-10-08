"""Files a node saves into its dataflow's Computed datasets, and reads back.

``curio_save_file("summary.csv")`` gives a path to write one file, and
``curio_save_folder("tiles")`` an empty folder to write many. After the run
the backend installs each as the computed dataset
``computed.<dataflowId>.files.<name>`` of the dataflow the node is in. A node
of the same dataflow reads it back with ``curio_computed_path("summary")``:
the file, or the folder, of that name.

The sandbox never sees a dataflow id. The backend sends, for each run:

- ``names``: ``{name: datasetId}`` for the ``curio_computed_path("<name>")``
  calls in the code that resolved, their files resolved with the other
  dataset paths;
- ``canSave``: whether the run may save (the dataflow has an id), and
  ``reason``, what to say when it may not.

Saved files are written under ``<saved_root>/<name>``: a folder of their own
beside the artifacts in process, ``<scratch>/saved`` in an isolated child,
which the parent copies out (:func:`collect_saved`). Both paths build these
helpers from one function, so they cannot disagree.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

#: A saved name: what follows ``files.`` in the dataset id, so one id segment.
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")

#: The file a ``curio_save_file`` call names, and the format it is stored as.
FILE_FORMATS = {
    "csv": "csv",
    "json": "json",
    "geojson": "geojson",
    "parquet": "parquet",
    "tif": "geotiff",
    "tiff": "geotiff",
    "nc": "netcdf",
}

#: Where a saved folder's files sit, under its dataset's ``data/``.
FOLDER_FILES = "files"

#: The most files one run may save, and the most a saved folder may hold.
MAX_SAVED = 16
MAX_FOLDER_FILES = 10000

SAVED_DIRNAME = "saved"


def _check_name(name, what):
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError(
            f"{what} name {name!r} must start with a letter and hold only lowercase "
            "letters, digits and hyphens, like \"tiles\" or \"daily-means\"."
        )


def split_file_name(file_name):
    """``("summary", "csv")`` for ``"summary.csv"``; refuses any other form."""
    if not isinstance(file_name, str) or "." not in file_name:
        raise ValueError(
            f"curio_save_file takes a name with its extension, like \"summary.csv\"; got {file_name!r}."
        )
    name, ext = file_name.rsplit(".", 1)
    _check_name(name, "A saved file's")
    ext = ext.lower()
    if ext not in FILE_FORMATS:
        known = ", ".join(f".{e}" for e in FILE_FORMATS)
        raise ValueError(
            f"curio_save_file saves {known} files; {file_name!r} is none of them. "
            "Save other files into a folder with curio_save_folder(\"<name>\")."
        )
    return name, ext


def make_saved_helpers(saved_root, data_path, computed=None):
    """``curio_save_file``, ``curio_save_folder`` and ``curio_computed_path``
    for one run, and the list of what it saved.

    *saved_root* is where saved files are written, made on first use.
    *data_path* resolves a dataset id to its file, as ``curio_data_path`` does.
    """
    computed = computed if isinstance(computed, dict) else {}
    names = {str(k): str(v) for k, v in (computed.get("names") or {}).items()}
    can_save = bool(computed.get("canSave", False))
    reason = str(computed.get("reason") or "This run cannot save files.")
    saved = []

    def _target(name):
        if not can_save:
            raise RuntimeError(reason)
        if any(entry["name"] == name for entry in saved):
            raise ValueError(f"This node already saves {name!r}; each name is saved once per run.")
        if len(saved) >= MAX_SAVED:
            raise ValueError(f"A node saves at most {MAX_SAVED} files or folders per run.")
        root = Path(saved_root)
        root.mkdir(parents=True, exist_ok=True)
        return root / name

    def curio_save_file(file_name):
        """A path to write one file this dataflow keeps as a computed dataset."""
        name, ext = split_file_name(file_name)
        folder = _target(name)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.{ext}"
        saved.append({"name": name, "kind": "file", "file": path.name})
        return str(path)

    def curio_save_folder(name):
        """An empty folder whose files this dataflow keeps as one computed dataset."""
        _check_name(name, "A saved folder's")
        folder = _target(name) / FOLDER_FILES
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        saved.append({"name": name, "kind": "folder"})
        return str(folder)

    def curio_computed_path(name):
        """The file, or the folder, this dataflow saved under *name*."""
        _check_name(name, "A saved")
        dataset_id = names.get(name)
        if dataset_id is None:
            raise FileNotFoundError(
                f"This dataflow has saved nothing named {name!r}. A node saves it with "
                f"curio_save_file(\"{name}.<ext>\") or curio_save_folder(\"{name}\"); run that node first."
            )
        path = Path(data_path(dataset_id))
        if path.name == "bundle.json":
            return str(path.parent / FOLDER_FILES)
        return str(path)

    return {
        "curio_save_file": curio_save_file,
        "curio_save_folder": curio_save_folder,
        "curio_computed_path": curio_computed_path,
    }, saved


def in_process_saved_root(data_dir):
    """A fresh folder, beside the artifacts, for one in-process run's saved files."""
    return Path(data_dir) / SAVED_DIRNAME / uuid.uuid4().hex


def describe_saved(saved, saved_root):
    """The ``savedFiles`` entries the backend installs: what each run saved,
    with the absolute path of its file or folder. An entry whose file was
    never written is left out."""
    entries = []
    root = Path(saved_root)
    for entry in saved:
        if entry["kind"] == "file":
            path = root / entry["name"] / entry["file"]
            if not path.is_file():
                continue
        else:
            path = root / entry["name"] / FOLDER_FILES
            if not path.is_dir():
                continue
        entries.append({**entry, "path": str(path)})
    return entries


def collect_saved(scratch_dir, data_dir):
    """Copy what an isolated child saved under ``<scratch>/saved`` out of its
    scratch directory, before the directory is removed, and describe it.

    The child's files are not trusted: only regular files are copied, never a
    link, and only the shapes the helpers make (``<name>/<name>.<ext>`` and
    ``<name>/files/...``).
    """
    source = Path(scratch_dir) / SAVED_DIRNAME
    if not source.is_dir() or source.is_symlink():
        return []
    dest_root = in_process_saved_root(data_dir)
    entries = []
    for folder in sorted(source.iterdir())[:MAX_SAVED]:
        name = folder.name
        if folder.is_symlink() or not folder.is_dir() or not NAME_RE.match(name):
            continue
        files = folder / FOLDER_FILES
        if files.is_dir() and not files.is_symlink():
            copied = 0
            for path in sorted(files.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                if copied >= MAX_FOLDER_FILES:
                    break
                relative = path.relative_to(files)
                target = dest_root / name / FOLDER_FILES / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                copied += 1
            (dest_root / name / FOLDER_FILES).mkdir(parents=True, exist_ok=True)
            entries.append({"name": name, "kind": "folder", "path": str(dest_root / name / FOLDER_FILES)})
            continue
        for path in sorted(folder.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                stem, _ext = split_file_name(path.name)
            except ValueError:
                continue
            if stem != name:
                continue
            target = dest_root / name / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            entries.append({"name": name, "kind": "file", "file": path.name, "path": str(target)})
            break
    return entries


__all__ = [
    "NAME_RE", "FILE_FORMATS", "FOLDER_FILES", "make_saved_helpers", "in_process_saved_root",
    "describe_saved", "collect_saved", "split_file_name", "SAVED_DIRNAME",
]
