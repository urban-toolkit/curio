"""The files a node's run writes for its output, and the one a download reads.

Every Python run has a folder of its own for the files it returns, named after
the artifact its output is stored as: ``<shared data>/outputs/<artifact id>/``.
``curio_output_file`` gives paths in it, and ``curio_export`` writes there.

- In process the run writes into that folder directly (``worker.execute_code``).
- An isolated child writes into its scratch directory, which goes when the run
  ends. The parent moves the one file a run's text output names, among those
  ``curio_output_file`` gave the child, into the folder (:func:`keep_named_file`).

A run's output that is text naming such a file (a Data Export node's) is
downloaded by its artifact id (:func:`named_file`, behind the sandbox's
``/output-file``): a plain name is a file in the output's folder, a path must
lie inside it, whatever links it passes through. The store's sweeps remove a
folder with its artifact (``parsers.forget_made_before``,
``parsers.forget_session_artifacts``).
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

#: The folder, in the sandbox's shared data directory, that holds every run's.
OUTPUTS_DIRNAME = "outputs"

#: An artifact id, as ``parsers._make_id`` makes it.
_ARTIFACT_ID_RE = re.compile(r"^[0-9]{1,20}_[0-9a-f]{8}$")


class OutputFileRefused(Exception):
    """A download the store will not serve: *status* is the HTTP answer."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def outputs_root() -> Path:
    from utk_curio.sandbox.util.parsers import _shared_data_dir

    return _shared_data_dir() / OUTPUTS_DIRNAME


def is_artifact_id(value) -> bool:
    return isinstance(value, str) and bool(_ARTIFACT_ID_RE.match(value))


def run_output_dir(art_id: str) -> Path:
    """The folder of the run whose output is stored as *art_id*; not made
    here: ``curio_output_file`` makes it when a run first writes there."""
    if not is_artifact_id(art_id):
        raise ValueError(f"not an artifact id: {art_id!r}")
    return outputs_root() / art_id


def forget_run_output(art_id: str) -> None:
    """Remove the folder of *art_id*'s run, if there is one."""
    if is_artifact_id(art_id):
        folder = run_output_dir(art_id)
        if folder.is_dir() and not folder.is_symlink():
            shutil.rmtree(folder, ignore_errors=True)


def folder_bytes(art_id: str) -> int:
    """How many bytes the files of *art_id*'s run hold."""
    if not is_artifact_id(art_id):
        return 0
    total = 0
    for root, _dirs, files in os.walk(run_output_dir(art_id)):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def folder_of(path_text) -> str | None:
    """The run folder (its artifact id) a file path lies in, else None."""
    if not isinstance(path_text, str) or not os.path.isabs(path_text):
        return None
    root = os.path.realpath(outputs_root())
    try:
        relative = os.path.relpath(os.path.realpath(path_text), root)
    except ValueError:
        return None
    first = relative.split(os.sep, 1)[0]
    if relative.startswith("..") or not is_artifact_id(first):
        return None
    return first


def folders_named_by(rows) -> set:
    """The run folders (their artifact ids) that store rows, ``(kind,
    value_str)``, name a file in: a raster's file, or a text output's path.
    A raster one run returned can be what a later run returns too."""
    named = set()
    for kind, value in rows:
        if kind in ("raster", "str"):
            folder = folder_of(value)
            if folder:
                named.add(folder)
    return named


def _scratch_entry(value, scratch_dir) -> str | None:
    """The flat name in *scratch_dir* a text output names: the text itself
    when it is one plain name, the name of a path directly inside it."""
    if not isinstance(value, str) or not value:
        return None
    if "/" not in value and "\\" not in value:
        return value if value not in (".", "..") else None
    if not os.path.isabs(value):
        return None
    if os.path.realpath(os.path.dirname(value)) != os.path.realpath(scratch_dir):
        return None
    return os.path.basename(value)


def keep_named_file(descriptor, scratch_dir, names, art_id, *, exec_uid=None) -> Path | None:
    """Move the file an isolated run's text output names out of its scratch
    directory into the folder of *art_id*, the id the output is stored as.

    Only a file ``curio_output_file`` gave the child (*names*), and only a
    plain file: not a link, and not a second name of another file. The output
    then names the kept file: a plain name stays as it is, and a path becomes
    the kept file's path. Returns the kept file, or None.
    """
    from utk_curio.sandbox.isolation import protocol

    if not isinstance(descriptor, dict) or descriptor.get("kind") != "str" or not names:
        return None
    value = descriptor.get("value")
    name = _scratch_entry(value, scratch_dir)
    if name is None or name not in names:
        return None
    protocol.validate_scratch_filename(name)
    entry = os.path.join(scratch_dir, name)
    try:
        status = os.lstat(entry)
    except OSError:
        return None
    if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
        return None
    folder = run_output_dir(art_id)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    shutil.move(entry, target)
    if exec_uid is not None:
        from utk_curio.sandbox.util.staging import _take_from_child

        _take_from_child(target)
    if os.path.isabs(value):
        descriptor["value"] = str(target)
    return target


def named_file(art_id, session_id=None) -> Path:
    """The file the output *art_id* names, for a reader under *session_id*.

    The output must be text: a plain name of a file in the folder of the run
    that made it, or a path inside that folder, once every link on the way is
    followed. Anything else is refused (:class:`OutputFileRefused`): an output
    the session may not read is not found, as ``/get`` answers it.
    """
    from utk_curio.sandbox.util.db import get_read_connection
    from utk_curio.sandbox.util.parsers import session_may_read

    if not is_artifact_id(art_id):
        raise OutputFileRefused(404, "not-found", f"no output {art_id}")
    con = get_read_connection()
    try:
        row = con.execute(
            "SELECT kind, value_str, session_id FROM artifacts WHERE id = ?", [art_id],
        ).fetchone()
    finally:
        con.close()
    if row is None or not session_may_read(row[2], session_id):
        raise OutputFileRefused(404, "not-found", f"no output {art_id}")
    kind, value = row[0], row[1]
    if kind != "str" or not value:
        raise OutputFileRefused(404, "no-file", "This node's output names no file.")
    root = os.path.realpath(run_output_dir(art_id))
    candidate = os.path.realpath(value if os.path.isabs(value) else os.path.join(root, value))
    if not candidate.startswith(root + os.sep):
        raise OutputFileRefused(
            403, "outside", "This node's output names a file outside the folder of the run that made it.",
        )
    if not os.path.isfile(candidate):
        raise OutputFileRefused(404, "gone", "The file this node's output names is gone: run the node again.")
    return Path(candidate)
