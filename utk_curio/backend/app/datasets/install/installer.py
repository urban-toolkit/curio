"""Install datasets from the shared catalog into a user's dataset store."""

from __future__ import annotations

import dataclasses
import filecmp
import hashlib
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from utk_curio.backend.app.common.file_locks import exclusive_lock
from utk_curio.backend.app.datasets.domain.manifest import (
    DatasetManifest,
    ManifestError,
    load_dataset_manifest,
    manifest_text,
    replace_manifest,
    write_manifest,
)
from utk_curio.backend.app.common.record_clock import utc_now
from utk_curio.backend.app.common.safe_paths import PathTraversalError, validate_component
from utk_curio.backend.app.datasets.domain.constants import NETCDF_SIGNATURES, TIFF_SIGNATURES
from utk_curio.backend.app.datasets.domain.onnx_model import is_onnx_model
from utk_curio.backend.app.datasets.infrastructure.catalog_utils import title_from_filename
from utk_curio.backend.app.datasets.infrastructure.storage import catalog_root, dataset_dir


def _validate_store_filename(safe_filename: str) -> str:
    """Reject an output/store filename that isn't a single safe path segment.

    The data file is written to ``<dataset dir>/data/<safe_filename>``; an
    untrusted node-output ref (e.g. ``../../../../etc/foo``) must never escape
    the user's datasets dir. Maps a traversal attempt to ``InstallerError`` so
    callers surface a clean 4xx / skip the bad output rather than 500.
    """
    try:
        return validate_component(safe_filename, field="output filename")
    except PathTraversalError as exc:
        raise InstallerError(str(exc)) from exc

logger = logging.getLogger(__name__)


class InstallerError(Exception):
    """Raised when a dataset install fails."""


@dataclass(frozen=True)
class InstallResult:
    manifest: DatasetManifest
    dest: Path
    replaced: bool


def _index(user_key: str, result: InstallResult) -> InstallResult:
    """Mirror a freshly written store dir into the dataset index.

    Wrapped around every installer's return so a new dataset is queryable
    immediately instead of waiting for the next listing's reconcile. Purely an
    accelerator: it never raises (the files are already written and the install
    has succeeded by this point), and ``index.reconcile`` repairs anything that
    fails here.
    """
    from utk_curio.backend.app.datasets.repositories import index as index_repo

    index_repo.safe_upsert_from_dir(user_key, result.dest)
    return result


def _is_installed(user_key: str, dir_name: str) -> bool:
    return (dataset_dir(user_key, dir_name) / "manifest.json").is_file()


def _left_out_data_file(dir_name: str, manifest: DatasetManifest, src: Path) -> Path | None:
    """The data file of a shipped dataset whose catalog folder *src* lacks it
    because the pip package leaves it out: downloaded from GitHub on the first
    install (``infrastructure/left_out_files.py``). ``None`` when *src* holds
    the file, or lacks one the package does not leave out."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    shipped = src / manifest.data_file
    repo_path = f"datasets/{dir_name}/{manifest.data_file}"
    if shipped.is_file() or not left_out_files.is_left_out(repo_path):
        return None
    try:
        return left_out_files.fetch(repo_path, shipped)
    except left_out_files.LeftOutFileUnavailable as exc:
        raise InstallerError(str(exc)) from exc


def _place_copy(source: Path, target: Path) -> None:
    """Copy *source* to *target* whole or not at all: the install counts as
    complete once its data file is there."""
    write_whole(target, lambda partial: shutil.copyfile(source, partial))


def write_whole(target: Path, write: Callable[[Path], object]) -> None:
    """Have *write* make the file at *target* under a temporary name in the
    same folder, then move it into place, so a reader that finds *target*
    finds all of it, and a write that fails leaves *target* as it was."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
    try:
        write(partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def install_dataset_from_catalog(
    user_key: str,
    dir_name: str,
    *,
    replace: bool = False,
) -> InstallResult:
    """Copy ``<repo_root>/datasets/<dirName>/`` into the user's dataset store."""
    src = catalog_root() / dir_name
    if not src.is_dir():
        raise InstallerError(f"catalog has no dataset {dir_name}")

    try:
        manifest = load_dataset_manifest(src)
    except ManifestError as exc:
        raise InstallerError(str(exc)) from exc

    dest = dataset_dir(user_key, dir_name)
    if dest.exists():
        # Check whether the existing install is complete (data file is present).
        # A previous failed copy can leave a partial directory behind, so we
        # treat any incomplete destination the same as a missing one.
        data_file = dest / manifest.data_file
        install_is_complete = data_file.is_file()
        if install_is_complete and not replace:
            return _index(
                user_key, InstallResult(manifest=manifest, dest=dest, replaced=False)
            )

    # Before the destination is touched, so a failed download leaves it as it was.
    fetched = _left_out_data_file(dir_name, manifest, src)

    replaced = False
    if dest.exists():
        # Either replace was requested or the previous install was incomplete –
        # remove the stale/partial directory and start fresh.
        shutil.rmtree(dest)
        replaced = True

    try:
        shutil.copytree(src, dest)
    except shutil.Error as exc:
        # copytree() raises shutil.Error (collecting per-file errors) even when
        # individual files fail to copy.  Clean up the partial destination so
        # that the next install attempt can start from scratch.
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to copy dataset files: {exc}") from exc
    if fetched is not None:
        try:
            _place_copy(fetched, dest / manifest.data_file)
        except OSError as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise InstallerError(f"Failed to copy dataset files: {exc}") from exc

    return _index(
        user_key,
        InstallResult(manifest=load_dataset_manifest(dest), dest=dest, replaced=replaced),
    )


def resolve_installed_data_path(user_key: str, manifest: DatasetManifest) -> Path:
    root = dataset_dir(user_key, manifest.dir_name)
    data_path = (root / manifest.data_file).resolve()
    if not data_path.is_file():
        raise InstallerError(f"installed dataset is missing data file {manifest.data_file!r}")
    return data_path


def _sanitize_node_id_segment(node_id: str) -> str:
    """Convert an arbitrary node ID to a valid single-segment string for a dataset dir name.

    Rules (matching ``DATASET_DIR_RE`` segment constraints):
    - Lowercase, replace any non-``[a-z0-9-]`` character with ``-``.
    - Collapse consecutive hyphens and strip leading/trailing hyphens.
    - Truncate to 62 characters (leaving room for mandatory leading letter).
    - Prefix with ``n`` if the result does not start with a letter.
    """
    import re as _re
    seg = _re.sub(r"[^a-z0-9-]", "-", node_id.lower())
    seg = _re.sub(r"-+", "-", seg).strip("-")[:62]
    if not seg or not seg[0].isalpha():
        seg = ("n" + seg)[:63]
    return seg or "node"


# Public alias for use outside this module (e.g. service.py).
sanitize_node_id_segment = _sanitize_node_id_segment


def computed_dataset_id(node_id: str, dataflow_id: str | None = None) -> str:
    """Build the stable computed-dataset id for a node output.

    Namespaced by the producing dataflow so the same node id reused in two
    dataflows yields two *distinct* account-level datasets
    (``computed.<dataflowSeg>.<nodeSeg>``). When *dataflow_id* is absent the
    un-namespaced ``computed.<nodeSeg>`` form is returned — that form is for
    DISPLAY/LOOKUP ONLY (transient live rows, legacy-dir matching); the
    persistence installers refuse it so no new legacy dir is ever minted.
    """
    node_seg = _sanitize_node_id_segment(node_id)
    if dataflow_id:
        return f"computed.{_sanitize_node_id_segment(dataflow_id)}.{node_seg}"
    return f"computed.{node_seg}"


def node_segment_from_computed_id(source: str | None) -> str | None:
    """Return the sanitized *node* segment of a computed id or dir name.

    The node segment is always the last dotted segment, so this tolerates both
    the namespaced (``computed.<df>.<node>``) and legacy (``computed.<node>``)
    forms and an optional ``@<major>`` suffix. Returns ``None`` for non-computed
    inputs.
    """
    import re as _re
    if not source or not source.startswith("computed."):
        return None
    seg = _re.sub(r"@\d+$", "", source[len("computed.") :])
    if not seg:
        return None
    return seg.split(".")[-1] or None


def display_folder_name(source: str | None) -> str | None:
    """Node-scoped display form of a computed id or dir name.

    Computed datasets are stored dataflow-namespaced
    (``computed.<dataflowId>.<nodeId>[@N]``) so the same node id in two dataflows
    stays distinct on disk, but the dataflow segment is an opaque project id that
    must never surface in a title/subtitle. This drops it, keeping
    ``computed.<nodeId>[@N]`` — the readable folder the catalog showed before
    namespacing. Legacy (un-namespaced) and non-computed inputs are returned
    unchanged.
    """
    import re as _re
    if not source or not source.startswith("computed."):
        return source
    m = _re.match(r"^computed\.(.+?)(@\d+)?$", source)
    if not m:
        return source
    segments = m.group(1).split(".")
    if len(segments) < 2:
        return source  # legacy ``computed.<node>``
    return f"computed.{segments[-1]}{m.group(2) or ''}"


def dataflow_segment_from_computed_id(source: str | None) -> str | None:
    """Return the sanitized *dataflow* segment of a namespaced computed id, or
    ``None`` for the legacy (un-namespaced) form or a non-computed input.

    Namespaced ids are ``computed.<dataflowSeg>.<nodeSeg>`` (two dotted segments
    after the prefix); the legacy ``computed.<nodeSeg>`` has one.
    """
    import re as _re
    if not source or not source.startswith("computed."):
        return None
    seg = _re.sub(r"@\d+$", "", source[len("computed.") :])
    parts = seg.split(".")
    if len(parts) >= 2:
        return parts[0] or None
    return None


def _link_or_copy(src: Path, dest: Path) -> None:
    """Materialize *dest* from *src* cheaply.

    Hard-links when ``src`` and ``dest`` share a filesystem — avoiding a
    full-file byte copy on the synchronous install path. Computed outputs are
    write-once, so a shared inode is safe and actually keeps the dataset alive
    if the shared-data source is later garbage-collected. Falls back to a copy
    across filesystems or when linking is unsupported (e.g. some Windows setups).
    """
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def copy_decode_sidecar(source: Path, dest: Path, *, copy=shutil.copy2) -> None:
    """Put *source*'s parquet decode sidecar, if it has one, beside *dest*.

    ``<file>.decode.json`` (written beside a saved frame from its artifact's
    row, :func:`install_computed_file_for_node`, or by
    ``parsers.save_dataset_parquet``) names the JSON-encoded object columns of
    a parquet file, so a copy of the file without it loads its list and dict
    columns as JSON strings. Every path that copies a dataset's data file to a
    new place copies it with this. Distinct from file_meta's ``.meta.json``
    counts sidecar.
    """
    from utk_curio.sandbox.util.codec import PARQUET_DECODE_SIDECAR_SUFFIX

    sidecar = source.with_name(source.name + PARQUET_DECODE_SIDECAR_SUFFIX)
    if sidecar.is_file():
        copy(sidecar, dest.with_name(dest.name + PARQUET_DECODE_SIDECAR_SUFFIX))


_INSTALL_LOCK_NAMESPACE = "computed-output-install"


@contextmanager
def output_install_lock(dest: Path) -> Iterator[None]:
    """One install at a time into the computed dataset folder *dest*.

    Each install removes what the output before it left
    (:func:`drop_other_files`), so two at once could remove each other's
    files. A play installs without the project's spec lock, so this is the
    lock two installs of one node share. Its file sits beside the folder,
    where the store's listings skip it.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(
        dest.parent / f".{dest.name}.install.lock",
        namespace=_INSTALL_LOCK_NAMESPACE,
        key=str(dest),
    ):
        yield


def drop_other_files(dest: Path, keep: Iterable[Path]) -> None:
    """Remove every file in the dataset folder *dest* but its manifest and
    *keep*, then the folders that leaves empty: what the output it held
    before left, once its manifest names the new one. A file that cannot be
    removed stays, with a warning; the output the manifest names is whole
    either way."""
    root = dest.resolve()
    if not root.is_dir():
        return
    kept = {Path(path).resolve() for path in (dest / "manifest.json", *keep)}
    # Deepest first, so a folder is emptied before it is looked at.
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                if not any(path.iterdir()):
                    path.rmdir()
            elif path not in kept:
                path.unlink()
        except OSError as exc:
            logger.warning("Could not remove %s, left by an earlier output: %s", path, exc)


# A sandbox artifact id, and the dataset file a node run writes beside it: the
# millisecond it was made and a random part. Neither is ever written again, so
# a data file named after one holds one output for good.
_ONE_OUTPUT_NAME = re.compile(r"^\d{13}_[0-9a-f]{8}(?:[._]|$)")


def _names_one_output(name: str | None) -> bool:
    """Whether *name* is an artifact id or a node run's dataset file name."""
    return bool(name and _ONE_OUTPUT_NAME.match(name))


def _dated_now() -> str:
    """Now on the record clock, to the millisecond: how a computed dataset is dated.

    To the millisecond, because a Run All writes several outputs in one second
    and the catalog's "Recent activity" lists them in the order they were made.
    """
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _held_manifest(dest: Path) -> DatasetManifest | None:
    """The manifest a dataset folder holds before it is written again, if any."""
    if not dest.is_dir():
        return None
    try:
        return load_dataset_manifest(dest)
    except (ManifestError, OSError, ValueError):
        return None


def _same_file(a: Path, b: Path) -> bool:
    """Whether *a* and *b* hold the same bytes: one file under two names (a
    hard link), or two files with equal contents."""
    try:
        return os.path.samefile(a, b) or filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _decode_sidecar_path(data_path: Path) -> Path:
    from utk_curio.sandbox.util.codec import PARQUET_DECODE_SIDECAR_SUFFIX

    return data_path.with_name(data_path.name + PARQUET_DECODE_SIDECAR_SUFFIX)


def decode_sidecar_beside(data_path: Path) -> str | None:
    """The text of *data_path*'s parquet decode sidecar
    (:func:`copy_decode_sidecar`), or None when it has none."""
    sidecar = _decode_sidecar_path(data_path)
    try:
        return sidecar.read_text(encoding="utf-8") if sidecar.is_file() else None
    except OSError:
        return None


def write_decode_sidecar(data_path: Path, text: str | None) -> None:
    """Make *text* *data_path*'s parquet decode sidecar, or, when *text* is
    None, remove the one it has."""
    sidecar = _decode_sidecar_path(data_path)
    if text is None:
        sidecar.unlink(missing_ok=True)
    else:
        write_whole(sidecar, lambda partial: partial.write_text(text, encoding="utf-8"))


def _holds_data(
    dest: Path, data_file: str, *, source_path: Path | None, file_bytes: bytes | None,
    decode_sidecar: str | None = None,
) -> bool:
    """Whether the dataset folder *dest* already holds this data file, byte for
    byte, with *decode_sidecar* as its parquet decode sidecar, or none."""
    data_path = dest / data_file
    if decode_sidecar_beside(data_path) != decode_sidecar:
        return False
    if source_path is not None:
        return _same_file(source_path, data_path)
    if file_bytes is not None:
        try:
            return data_path.read_bytes() == file_bytes
        except OSError:
            return False
    return False


def keep_installed_output(user_key: str, dest: Path, manifest: DatasetManifest) -> InstallResult:
    """Keep the output a dataset folder already holds, under *manifest*.

    A save sends the output of every node the canvas keeps, and a run records
    the output its play has just installed, so most installs find their output
    already there. Installing it again would remove the folder first, and a
    reader that does not take the project's spec lock would find no output
    (#941). The folder stays; its manifest is replaced only when it changed,
    a renamed node for one.

    The manifest is written under the folder's install lock
    (:func:`output_install_lock`), after reading the folder again: a play
    that installed a newer output since the caller looked keeps it, and this
    manifest is not written over it, naming files that install removed.
    """
    with output_install_lock(dest):
        held = _held_manifest(dest)
        if held is not None and held.data_file == manifest.data_file:
            try:
                held_text = (dest / "manifest.json").read_text(encoding="utf-8")
            except OSError:
                held_text = None
            if held_text != manifest_text(manifest):
                replace_manifest(manifest, dest)
    return _index(
        user_key, InstallResult(manifest=load_dataset_manifest(dest), dest=dest, replaced=False),
    )


def _holds_whole_output(dest: Path, held: DatasetManifest) -> bool:
    """Whether the dataset folder *dest* holds the whole output *held* names:
    its data file, and for a bundle every part its ``bundle.json`` lists."""
    from utk_curio.sandbox.util.catalog_helpers import listed_bundle_parts

    data = dest / held.data_file
    if not data.is_file():
        return False
    if data.name != "bundle.json":
        return True
    try:
        named = json.loads(data.read_text(encoding="utf-8")).get("parts")
    except (OSError, ValueError, AttributeError):
        return False
    return isinstance(named, list) and bool(named) and len(listed_bundle_parts(data)) == len(named)


def keep_recorded_output(
    user_key: str,
    *,
    node_id: str,
    dataflow_id: str,
    title: str | None = None,
    node_type: str | None = None,
    dataflow_name: str | None = None,
    upstream_inputs: list[dict] | None = None,
) -> InstallResult | None:
    """Keep the output a node's computed dataset holds, under the title and
    lineage a save gives it now.

    A save sends the output of every node the canvas keeps. One its dataflow
    already records for the node, under the same name, is the output this
    dataset holds: every reader reads it here, in place, and nothing copies
    it back where it was made, so the save needs no source to find it again.
    Only a changed title or lineage is written, as
    :func:`keep_installed_output` writes it. None when the folder holds no
    whole output; the caller installs it then.
    """
    dest = dataset_dir(user_key, f"{computed_dataset_id(node_id, dataflow_id)}@1")
    held = _held_manifest(dest)
    if held is None or not _holds_whole_output(dest, held):
        return None
    return keep_installed_output(user_key, dest, dataclasses.replace(
        held,
        name=title or held.name,
        producer_node_type=node_type,
        producer_dataflow_name=dataflow_name,
        upstream_inputs=list(upstream_inputs) if upstream_inputs else None,
    ))


def _computed_dates(held: DatasetManifest | None, *, same_output: bool) -> tuple[str, str]:
    """``(created_at, updated_at)`` for a computed dataset being written.

    Writing again the output the dataset already holds keeps its dates. A save
    sends the output of every node the dataflow keeps, and a run records the
    output its play has just installed, so one output is written many times;
    dating every write put an output computed earlier ahead of one computed
    since. A new output is dated now.
    """
    if same_output and held is not None and held.updated_at:
        return held.created_at or held.updated_at, held.updated_at
    now = _dated_now()
    return now, now


def install_computed_file_for_node(
    user_key: str,
    file_bytes: bytes | None,
    safe_filename: str,
    fmt: str,
    *,
    node_id: str,
    dataflow_id: str | None = None,
    node_type: str | None = None,
    dataflow_name: str | None = None,
    upstream_inputs: list[dict] | None = None,
    title: str | None = None,
    source_path: Path | None = None,
    decode_sidecar: str | None = None,
) -> InstallResult:
    """Save a node-computed output into the user's dataset store keyed by *node_id*.

    Uses ``computed.<sanitized_dataflow_id>.<sanitized_node_id>@1`` (namespaced by
    the producing dataflow so the same node id in two dataflows stays distinct)
    so re-executing the same node always replaces the same dataset folder,
    keeping a stable dataset identity across multiple executions. A new
    output takes the place of the one the folder holds, so the latest
    execution's file is always reflected; it goes in beside the old one,
    which goes only once the manifest names the new one. The output the
    folder already holds, the same data file byte
    for byte, is not written again (:func:`keep_installed_output`), and
    writing it again keeps the dataset's dates (:func:`_computed_dates`).

    The producer/upstream arguments are persisted as lineage on the manifest so
    the account-level dataset stays connected to its workflow, source node, and
    upstream inputs without depending on a project reference.

    Provide *source_path* to materialize the data file by hard-linking the
    on-disk artifact (no full-file copy / no read into memory); *file_bytes* is
    used otherwise. Exactly one must be supplied. A saved frame is the store's
    own file, linked: the store keeps its decode in the artifact's row, so
    *decode_sidecar* is the text the data file's ``.decode.json`` holds. Left
    out, it is the one beside *source_path*, if that file has one.

    A *dataflow_id* is required: persisting without one would mint the legacy
    un-namespaced ``computed.<node>`` id, which permanently duplicates the
    namespaced dataset the dataflow save writes moments later (issue #166).
    """
    if not dataflow_id:
        raise InstallerError(
            "Computed dataset install requires a dataflow id; "
            "refusing to mint a legacy un-namespaced dataset dir."
        )
    if decode_sidecar is None and source_path is not None:
        decode_sidecar = decode_sidecar_beside(source_path)
    dataset_id = computed_dataset_id(node_id, dataflow_id)
    dir_name = f"{dataset_id}@1"

    dest = dataset_dir(user_key, dir_name)
    held = _held_manifest(dest)
    safe_filename = _validate_store_filename(safe_filename)
    data_file = f"data/{safe_filename}"
    holds_data = (
        held is not None
        and held.data_file == data_file
        and _holds_data(
            dest, data_file, source_path=source_path, file_bytes=file_bytes,
            decode_sidecar=decode_sidecar,
        )
    )
    created_at, updated_at = _computed_dates(
        held,
        same_output=(
            held is not None
            and held.data_file == data_file
            and _names_one_output(safe_filename)
        ),
    )
    display_title = title or title_from_filename(safe_filename)
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format=fmt,
        description=f"{fmt.upper()} dataset computed by a dataflow node.",
        publisher="User",
        license="",
        tags=[fmt, "computed"],
        data_file=data_file,
        major=1,
        source_label="Computed",
        created_at=created_at,
        updated_at=updated_at,
        row_count=None,
        feature_count=None,
        schema=None,
        producer_node_id=node_id,
        producer_node_type=node_type,
        producer_dataflow_id=dataflow_id,
        producer_dataflow_name=dataflow_name,
        upstream_inputs=list(upstream_inputs) if upstream_inputs else None,
    )
    if holds_data:
        return keep_installed_output(user_key, dest, manifest_obj)
    if source_path is None and file_bytes is None:
        raise InstallerError("install_computed_file_for_node requires file_bytes or source_path")

    from utk_curio.sandbox.util.catalog_helpers import files_read_beside

    # A new output goes in beside the one the folder holds, the manifest then
    # names it, and only then do the old output's files go. A reader, which
    # takes no lock, finds the whole old output or the whole new one, and an
    # install that fails leaves the old one as it was.
    with output_install_lock(dest):
        data_path = dest / data_file
        if source_path is not None:
            write_whole(data_path, lambda partial: _link_or_copy(source_path, partial))
        else:
            write_whole(data_path, lambda partial: partial.write_bytes(file_bytes))
        write_decode_sidecar(data_path, decode_sidecar)

        replace_manifest(manifest_obj, dest)
        try:
            manifest = load_dataset_manifest(dest)
        except ManifestError as exc:
            shutil.rmtree(dest, ignore_errors=True)
            raise InstallerError(f"Failed to create computed dataset manifest: {exc}") from exc
        drop_other_files(dest, [data_path, *files_read_beside(data_path)])

    return _index(user_key, InstallResult(manifest=manifest, dest=dest, replaced=True))


def install_computed_file(
    user_key: str,
    file_bytes: bytes,
    safe_filename: str,
    fmt: str,
    *,
    title: str | None = None,
    node_id: str | None = None,
    replace: bool = False,
) -> InstallResult:
    """Save a node-computed output file into the user's dataset store.

    Similar to :func:`install_imported_file` but uses the ``computed.x{hash}@1``
    naming convention so computed datasets are visually distinct from user-uploaded
    imports.  The *node_id* is stored in the manifest tags for provenance.

    .. deprecated::
        Prefer :func:`install_computed_file_for_node` which keys the dataset
        folder on *node_id* so re-execution replaces the same folder.
    """
    hash_hex = hashlib.sha256(file_bytes).hexdigest()[:8]
    dataset_id = f"computed.x{hash_hex}"
    dir_name = f"{dataset_id}@1"

    dest = dataset_dir(user_key, dir_name)

    # Fast path: already fully installed and no replacement requested.
    if dest.exists() and not replace:
        try:
            manifest = load_dataset_manifest(dest)
            if (dest / manifest.data_file).is_file():
                return _index(
                    user_key,
                    InstallResult(manifest=manifest, dest=dest, replaced=False),
                )
        except ManifestError:
            # Corrupt or incomplete prior install; remove and reinstall below.
            logger.debug(
                "Corrupt or incomplete prior install at %s; reinstalling",
                dest,
                exc_info=True,
            )
        shutil.rmtree(dest, ignore_errors=True)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)

    safe_filename = _validate_store_filename(safe_filename)
    data_path = dest / "data" / safe_filename
    data_path.write_bytes(file_bytes)

    now = _dated_now()
    display_title = title or title_from_filename(safe_filename)
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format=fmt,
        description=f"{fmt.upper()} dataset computed by a dataflow node.",
        publisher="User",
        license="",
        tags=[fmt, "computed"],
        data_file=f"data/{safe_filename}",
        major=1,
        source_label="Computed",
        created_at=now,
        updated_at=now,
        row_count=None,
        feature_count=None,
        schema=None,
    )
    write_manifest(manifest_obj, dest)

    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create computed dataset manifest: {exc}") from exc

    return _index(user_key, InstallResult(manifest=manifest, dest=dest, replaced=True))


def install_imported_file(
    user_key: str,
    file_bytes: bytes,
    safe_filename: str,
    fmt: str,
    *,
    title: str | None = None,
    replace: bool = False,
    group_id: str | None = None,
    layer_name: str | None = None,
    source_updated_at: str | None = None,
    source_encoding: str | None = None,
    discovery_source: dict | None = None,
) -> InstallResult:
    """Save an uploaded file into the user's dataset store with a generated manifest.

    Every import mints a **fresh, unique** dataset folder (``imported.x<uuid>``),
    so re-uploading a byte-identical file is always treated as a new, independent
    dataset — content is never used to reuse a previous import's directory.
    ``group_id`` / ``layer_name`` link multi-part imports (e.g. the layers of one
    OSM PBF); ``source_updated_at`` records the original file's last-modified
    date, distinct from the record's ``created_at`` / ``updated_at``.
    """
    return _install_imported(
        user_key,
        lambda data_path: data_path.write_bytes(file_bytes),
        safe_filename,
        fmt,
        title=title,
        group_id=group_id,
        layer_name=layer_name,
        source_updated_at=source_updated_at,
        source_encoding=source_encoding,
        discovery_source=discovery_source,
    )


def install_imported_path(
    user_key: str,
    source_path: Path,
    safe_filename: str,
    fmt: str,
    *,
    title: str | None = None,
    group_id: str | None = None,
    layer_name: str | None = None,
    source_updated_at: str | None = None,
    source_encoding: str | None = None,
    discovery_source: dict | None = None,
    description: str | None = None,
    collection: dict | None = None,
) -> InstallResult:
    """Move a file already on disk into a fresh dataset folder.

    The path-taking sibling of :func:`install_imported_file`: the bytes are
    never read into memory, so a large file costs a rename rather than its own
    size in RAM. *source_path* is consumed. It is moved with ``os.replace``
    when it sits on the same filesystem as the store, which every staging
    directory under ``.curio/users/<key>/`` does, and copied then removed
    otherwise.
    """
    source_path = Path(source_path)
    if not source_path.is_file():
        raise InstallerError(f"nothing to install at {source_path}")

    def _place(data_path: Path) -> None:
        try:
            os.replace(source_path, data_path)
        except OSError:
            shutil.copyfile(source_path, data_path)
            source_path.unlink(missing_ok=True)

    return _install_imported(
        user_key,
        _place,
        safe_filename,
        fmt,
        title=title,
        group_id=group_id,
        layer_name=layer_name,
        source_updated_at=source_updated_at,
        source_encoding=source_encoding,
        discovery_source=discovery_source,
        description=description,
        collection=collection,
    )


def _check_content(data_path: Path, fmt: str, safe_filename: str) -> None:
    """Refuse an import whose bytes are not the format it is stored as.

    An upload's format comes from its name, and a download's from its URL and
    headers, so a ``geotiff`` is checked for a TIFF's first bytes and a
    ``netcdf`` for a NetCDF file's. The loader opens a GeoTIFF with rasterio,
    which reads whatever format the bytes are. An ``onnx`` model has no such
    bytes, so its protobuf fields are read instead (``domain/onnx_model.py``).
    """
    if fmt not in ("geotiff", "netcdf", "onnx"):
        return
    with open(data_path, "rb") as fh:
        if fmt == "geotiff":
            matches = fh.read(4) in TIFF_SIGNATURES
            what = "a TIFF file, so it cannot be imported as a GeoTIFF"
        elif fmt == "netcdf":
            matches = fh.read(8).startswith(NETCDF_SIGNATURES)
            what = "a NetCDF file, so it cannot be imported as NetCDF"
        else:
            matches = is_onnx_model(fh, data_path.stat().st_size)
            what = "an ONNX model, so it cannot be imported as ONNX"
    if not matches:
        raise InstallerError(f"{safe_filename} is not {what}.")


def _install_imported(
    user_key: str,
    place_data,
    safe_filename: str,
    fmt: str,
    *,
    title: str | None = None,
    group_id: str | None = None,
    layer_name: str | None = None,
    source_updated_at: str | None = None,
    source_encoding: str | None = None,
    discovery_source: dict | None = None,
    description: str | None = None,
    collection: dict | None = None,
) -> InstallResult:
    """Mint ``imported.x<uuid>@1``, let *place_data* put the file, write the manifest."""
    # A per-import unique token — never the file content — guarantees each import
    # is a distinct dataset. The dir-name regex requires each dot-segment to
    # start with [a-z]; the 'x' prefix keeps the (hex) uuid segment letter-first.
    unique = uuid.uuid4().hex[:12]
    dataset_id = f"imported.x{unique}"
    dir_name = f"{dataset_id}@1"

    dest = dataset_dir(user_key, dir_name)

    # Validate at the write boundary even though every caller pre-sanitizes
    # (secure_filename) — keep the "validate at every write boundary" invariant.
    safe_filename = _validate_store_filename(safe_filename)

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(exist_ok=True)
    data_path = dest / "data" / safe_filename
    try:
        place_data(data_path)
        _check_content(data_path, fmt, safe_filename)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    now = utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    display_title = title or title_from_filename(safe_filename)
    manifest_obj = DatasetManifest(
        id=dataset_id,
        name=display_title,
        version="1.0.0",
        format=fmt,
        description=description or f"{fmt.upper()} dataset imported by the user.",
        publisher="User",
        license="",
        tags=[fmt, "imported"],
        data_file=f"data/{safe_filename}",
        major=1,
        source_label="Imported",
        created_at=now,
        updated_at=now,
        source_updated_at=source_updated_at,
        row_count=None,
        feature_count=None,
        schema=None,
        group_id=group_id,
        layer_name=layer_name,
        source_encoding=source_encoding,
        discovery_source=discovery_source,
        collection=collection,
    )
    write_manifest(manifest_obj, dest)

    try:
        manifest = load_dataset_manifest(dest)
    except ManifestError as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallerError(f"Failed to create imported dataset manifest: {exc}") from exc

    # A fresh unique dir is always created — never a reuse of a prior import.
    return _index(user_key, InstallResult(manifest=manifest, dest=dest, replaced=False))
