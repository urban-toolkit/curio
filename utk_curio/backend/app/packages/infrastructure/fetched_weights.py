"""The weights a shipped model package's ``fetch`` names, downloaded the first time a node needs them.

A model package whose weights stay out of git and the pip package names them in
its model block's ``fetch`` (``domain/model_fetch.py``): files of a Hugging Face
repository at one commit, each with its digest. The first run of a node that
loads the model downloads them (:func:`download`), as a pip install downloads
the files its package leaves out, through the same code
(``datasets/infrastructure/left_out_files.py``: ``download_checked``,
``one_download_at_a_time``, ``remove_stale_partials``, ``unavailable``):

- on the server, while the backend resolves the node's models and before the
  sandbox runs the node: an isolated child has no network, and the node's time
  limit starts after the download;
- from :func:`model_fetch.source_url`, the block's repository at its revision,
  with no token, through the egress policy;
- each file streamed to a partial file in the entry folder, checked against the
  digest the block names, made readable by every account and renamed into
  place; a file that does not match is never placed;
- each placed file stamped with that digest beside it
  (``model_fetch.write_stamp``), as ``scripts/fetch_model_weights.py`` stamps
  it: a file is in place only when its stamp names the digest the block
  names (:func:`missing_files`), so a block that names other digests, in a
  later version of the package, downloads its files again. A file with no
  stamp, placed by hand or before stamps, is hashed once under the model's
  lock and stamped when it matches. A file that is not the one the block
  names is removed before it downloads again, so no node reads it, even
  when that download fails;
- one download per model at a time, across processes and the stacks that share
  a ``--model-weights-dir``: a second first use waits, then finds what the
  first placed;
- into the folder reads already use (``model_packages.fetched_weights_folder``),
  its folders :data:`model_fetch.FOLDER_MODE`, which an isolated node enters to
  read them in place, and in the catalog's own copy its ``models/`` closed to
  its owner, as the sandbox's isolation leaves it;
- a failure raises ``LeftOutFileUnavailable``, which the node's run reports
  (``left_out_files.failures``), naming ``scripts/fetch_model_weights.py``,
  which fetches them ahead.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from utk_curio.backend.app.packages.domain.manifest import PackageManifest
from utk_curio.backend.app.packages.domain.model_fetch import (
    FOLDER_MODE,
    HUGGING_FACE,
    MODELS_DIR,
    FetchedFile,
    ModelFetch,
    checked_in_place,
    digest_of,
    discard,
    is_stamped,
    source_url,
    write_stamp,
)
from utk_curio.backend.app.packages.repositories import catalog_dir as packages_catalog_dir

log = logging.getLogger(__name__)

#: The file one model's download holds, in its entry folder. A dotfile, so the
#: package's integrity and archives leave it out.
LOCK = ".download.lock"
#: What fetches the weights ahead, which a failure names.
SCRIPT = "scripts/fetch_model_weights.py"
#: The answers of Hugging Face (``X-Error-Code``) that say the file is gone,
#: whatever the status.
_GONE = frozenset({"RepoNotFound", "RevisionNotFound", "EntryNotFound"})


def missing_files(fetch: ModelFetch, entry: Path) -> list[FetchedFile]:
    """The files *fetch* lists that are not in place in the folder *entry*:
    not there, or not stamped with the digest *fetch* names
    (``model_fetch.is_stamped``). Reads the stamps, never a file."""
    return [item for item in fetch.files if not is_stamped(entry / item.path, item)]


def download(manifest: PackageManifest, root: Path) -> Path:
    """*root*, whose entry holds every file *manifest*'s ``fetch`` lists,
    those missing downloaded now. *manifest* is the catalog's copy of the
    package: a shipped manifest is the one whose source a download trusts.

    Raises ``LeftOutFileUnavailable`` (collected for the node's run by
    ``left_out_files.failures``), and places no file that failed."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    block = manifest.model
    package = f"{manifest.package_id}@{manifest.major}"
    folder = Path(root)
    entry = folder / block.entry
    if not missing_files(block.fetch, entry):
        return folder
    lock = entry / LOCK
    # The catalog's own copy, with no --model-weights-dir: its models/ stays
    # its owner's, as the sandbox's isolation leaves a shipped package's.
    closed = folder / MODELS_DIR if packages_catalog_dir.model_weights_dir() is None else None
    try:
        _make_folders(entry, closed=closed)
        os.close(os.open(lock, os.O_WRONLY | os.O_CREAT, 0o644))
    except OSError as exc:
        raise left_out_files.unavailable(package, _cannot_write(manifest, entry, exc)) from exc
    with left_out_files.one_download_at_a_time(lock, key=str(entry)):
        # Another first use may have placed them while this one waited.
        left_out_files.remove_stale_partials(entry)
        for item in block.fetch.files:
            if not _checked(left_out_files, manifest, item, entry):
                _download(left_out_files, manifest, item, entry)
    return folder


def _checked(left_out_files, manifest: PackageManifest, item: FetchedFile, entry: Path) -> bool:
    """Under the model's lock: whether *item*'s file in *entry* is the one the
    block names (``model_fetch.checked_in_place``), a file with no stamp
    hashed once and stamped when it matches."""
    try:
        return checked_in_place(entry / item.path, item)
    except OSError as exc:
        package = f"{manifest.package_id}@{manifest.major}"
        raise left_out_files.unavailable(package, _cannot_write(manifest, entry, exc)) from exc


def _make_folders(entry: Path, *, closed: Path | None) -> None:
    """Make *entry* and the folders above it it lacks, each one every account
    may enter (:data:`FOLDER_MODE`), whatever the umask. *closed*, the
    ``models/`` of the catalog's own copy, is its owner's alone, as the
    sandbox's isolation leaves it (``hardening.SENSITIVE_PATHS``): a node
    reads those weights through the copy its run stages."""
    made = []
    current = entry
    while not current.exists():
        made.append(current)
        current = current.parent
    for folder in reversed(made):
        folder.mkdir(exist_ok=True)
        os.chmod(folder, FOLDER_MODE)
    if closed is not None:
        # Another account's folder: the sandbox's hardening answers for it.
        with contextlib.suppress(OSError):
            os.chmod(closed, 0o700)


def _download(left_out_files, manifest: PackageManifest, item: FetchedFile, entry: Path) -> None:
    """Download *item* into *entry*, checked against its digest
    (``left_out_files.download_checked``)."""
    block = manifest.model
    package = f"{manifest.package_id}@{manifest.major}"
    target = entry / item.path
    url = source_url(block.fetch, item.path)
    if block.size_bytes <= 0:
        raise left_out_files.unavailable(package, _could_not_download(
            manifest, item, url, "its manifest gives no sizeBytes to bound the download", gated=False,
        ))
    gated = False

    def check(result, partial: Path) -> str | None:
        nonlocal gated
        if result.status != 200:
            reason, gated = _refused(block.fetch, item, result.status, result.headers)
            return reason
        kind, actual, expected = digest_of(partial, item, sha256=result.sha256)
        if actual != expected:
            return (
                f"the file Hugging Face sent ({result.bytes_written:,} bytes, {kind} {actual}) is not "
                f"the one the package's manifest names ({kind} {expected}), so it was not placed"
            )
        return None

    _make_folders(target.parent, closed=None)
    try:
        # What is there is not this file, or has no stamp and did not match:
        # it goes now, with its stamp, so no node reads it while the right
        # one downloads, nor after a download that fails.
        discard(target)
    except OSError as exc:
        raise left_out_files.unavailable(package, _cannot_write(manifest, entry, exc)) from exc
    log.info("Downloading %s of %s from %s", item.path, package, url)
    left_out_files.download_checked(
        url, target, partial_dir=entry, max_bytes=block.size_bytes, check=check,
        failed=lambda reason: left_out_files.unavailable(
            package, _could_not_download(manifest, item, url, reason, gated=gated),
        ),
        # The model's lock makes this download the one writer of its partial
        # file, so one a restart killed mid-download is written over, never
        # left beside the weights.
        partial_name=f".{target.name}.download{left_out_files.PARTIAL_SUFFIX}",
    )
    try:
        # Only once the file is in place: a stamp never names bytes that are
        # not there. A file a restart left unstamped is hashed once instead.
        write_stamp(target, item)
    except OSError as exc:
        raise left_out_files.unavailable(package, _cannot_write(manifest, entry, exc)) from exc
    log.info("Placed %s of %s at %s", item.path, package, target)


def _refused(fetch: ModelFetch, item: FetchedFile, status: int, headers: dict) -> tuple[str, bool]:
    """Why Hugging Face did not send *item*, and whether its repository is
    gated, from the answer's status and its ``X-Error-Code``."""
    code = (headers or {}).get("X-Error-Code") or (headers or {}).get("x-error-code")
    if code in _GONE or (status == 404 and code != "GatedRepo"):
        return (
            f"Hugging Face has no {item.path} in {fetch.huggingface} at {fetch.revision} "
            f"(HTTP {status}): the repository is gone, or holds other files", False,
        )
    if status in (401, 403) or code == "GatedRepo":
        return (
            f"Hugging Face refused it (HTTP {status}): {fetch.huggingface} is gated, or gone, "
            "and Curio asks with no token", True,
        )
    return f"Hugging Face answered HTTP {status}", False


def _fetch_ahead(manifest: PackageManifest, *, gated: bool) -> str:
    """The command that fetches *manifest*'s weights where this Curio reads
    them, with a token when the repository is gated."""
    weights_dir = packages_catalog_dir.model_weights_dir()
    into = f" --into {weights_dir}" if weights_dir is not None else ""
    token = "HF_TOKEN=<a token that may read it> " if gated else ""
    return f"{token}python {SCRIPT} {manifest.package_id}{into}"


def _could_not_download(manifest: PackageManifest, item: FetchedFile, url: str, reason: str, *, gated: bool) -> str:
    fetch = manifest.model.fetch
    return (
        f"Curio could not download {item.path}, a file of the weights of {manifest.package_id}, "
        f"from {url}: {reason}. Curio downloads them from {HUGGING_FACE}/{fetch.huggingface} the first "
        f"time a node runs the model. Whoever runs this Curio can fetch them once with: "
        f"{_fetch_ahead(manifest, gated=gated)}"
    )


def _cannot_write(manifest: PackageManifest, entry: Path, exc: OSError) -> str:
    return (
        f"Curio could not write the weights of {manifest.package_id} into {entry}: "
        f"{exc.strerror or exc}. Start Curio with --model-weights-dir naming a folder it can write, where "
        f"it downloads them the first time a node runs the model, or fetch them there once with: "
        f"python {SCRIPT} {manifest.package_id} --into <that folder>"
    )
