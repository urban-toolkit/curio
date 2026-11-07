#!/usr/bin/env python3
"""Fetch the weights a model package names in its ``fetch`` block.

A model package whose weights stay out of git and the pip package names them
in its manifest's ``model.fetch`` (``utk_curio/backend/app/packages/domain/
model_fetch.py``): files of a Hugging Face repository at one commit. Whoever
runs a Curio runs this once, on the machine that keeps the files:

    HF_TOKEN=<token> python scripts/fetch_model_weights.py <package id>
    HF_TOKEN=<token> python scripts/fetch_model_weights.py <package id> --into <dir>

It reads the shipped package's manifest (``utk_curio/shipped.py``) and
downloads each file from ``https://huggingface.co/<repo>/resolve/<revision>/
<path>`` into the package's entry folder, ``packages/<id>@<major>/models/
<name>/``; with ``--into <dir>``, into ``<dir>/<id>@<major>/models/<name>/``,
the folder ``curio.py start --model-weights-dir <dir>`` reads them from.

- The token is read from ``HF_TOKEN`` alone. It goes to Hugging Face's own
  host, never to the host it redirects a large file to, and is never printed
  or written.
- Each file streams to a temporary file beside its place, is checked against
  the digest the manifest names (``sha256``, or ``gitSha1``, the git blob hash
  of a file that is not in Git LFS), is made readable by every account, and
  is then moved into place. A file that does not match is not placed.
- A file already in place with the right digest is skipped.

It imports nothing but the standard library and two modules of Curio that do
the same, read by their paths, so it runs with the host's own Python, outside
Curio's environment.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HUGGING_FACE = "https://huggingface.co"
#: The one host the token is sent to.
HUGGING_FACE_HOST = "huggingface.co"
#: The one place the token is read from.
TOKEN_VARIABLE = "HF_TOKEN"
CHUNK = 1024 * 1024
TIMEOUT_S = 60
#: Every account may read the files and enter the folders: an isolated node
#: runs as an account of its own and reads them in place.
FILE_MODE = 0o644
FOLDER_MODE = 0o755

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

GATED = (
    "Hugging Face refused {path} of {repo} (HTTP {status}). Its files are gated: sign in at "
    "{page}, accept the terms there, then run this again with {variable} set to a token "
    "with read access ({tokens}){given}."
)


class FetchError(RuntimeError):
    """A file that could not be fetched; the message says why, and never holds the token."""


def _code_root() -> Path:
    """The folder that holds ``utk_curio/``: the repository in a clone,
    site-packages in a pip install, whose ``scripts/`` sits in
    ``utk_curio/_shipped/``."""
    here = Path(__file__).resolve().parent
    for folder in here.parents:
        if (folder / "utk_curio" / "shipped.py").is_file():
            return folder
    raise SystemExit(f"{Path(__file__).name} found no utk_curio/shipped.py above {here}")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _modules():
    """``(shipped, model_fetch)``: where Curio's shipped folders are, and the
    reader of a ``fetch`` block, both read by their paths."""
    code = _code_root() / "utk_curio"
    return (
        _load("_curio_shipped", code / "shipped.py"),
        _load("_curio_model_fetch", code / "backend" / "app" / "packages" / "domain" / "model_fetch.py"),
    )


def size_text(size: int) -> str:
    """*size* bytes as Hugging Face shows a file's size: ``3.44 GB``."""
    for unit, scale in (("GB", 10**9), ("MB", 10**6), ("kB", 10**3)):
        if size >= scale:
            return f"{size / scale:.2f} {unit}"
    return f"{size} B"


def git_blob_sha1(path: Path) -> str:
    """The git blob hash of the file at *path*: the ``gitSha1`` Hugging Face
    lists for a file that is not in Git LFS."""
    digest = hashlib.sha1(b"blob %d\0" % path.stat().st_size, usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_of(path: Path, item) -> tuple[str, str]:
    """``(kind, digest)`` of the file at *path*, of the kind *item* names."""
    if item.sha256 is not None:
        return "sha256", sha256_of(path)
    return "git blob sha1", git_blob_sha1(path)


def _package_folder(shipped, package: str, shipped_root) -> Path:
    """The shipped folder of *package*, ``<id>`` (its highest major) or
    ``<id>@<major>``."""
    package_id, _, major = package.partition("@")
    if not _NAME.match(package_id) or ".." in package_id or (major and not major.isdigit()):
        raise SystemExit(f"{package!r} is not a package id, such as model.example.name or model.example.name@1")
    packages = shipped.path("packages", shipped_root)
    found = []
    for folder in sorted(packages.iterdir()) if packages.is_dir() else []:
        name, _, folder_major = folder.name.rpartition("@")
        if name == package_id and folder_major.isdigit() and major in ("", folder_major) \
                and (folder / "manifest.json").is_file():
            found.append((int(folder_major), folder))
    if not found:
        raise SystemExit(f"Curio ships no package {package} (looked in {packages})")
    return max(found)[1]


def _read_manifest(folder: Path, model_fetch):
    """``(package id, model block, fetch)`` of the package in *folder*."""
    try:
        raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{folder / 'manifest.json'} cannot be read: {exc}") from exc
    model = raw.get("model") if isinstance(raw, dict) and raw.get("kind") == "model" else None
    if not isinstance(model, dict) or model.get("fetch") is None:
        raise SystemExit(f"{folder.name} names no weights to fetch: its manifest's model block has no fetch")
    try:
        model_fetch.check_fetched_entry(str(model.get("entry") or ""), str(model.get("runtime") or ""))
        fetch = model_fetch.parse_fetch(model["fetch"])
    except model_fetch.ModelFetchError as exc:
        raise SystemExit(f"{folder.name}'s model.fetch cannot be read: {exc}") from exc
    return str(raw.get("id")), model, fetch


def _make_folder(folder: Path) -> None:
    """Make *folder* and the parents it lacks, each one every account may enter."""
    missing = []
    current = folder
    while not current.exists():
        missing.append(current)
        current = current.parent
    for path in reversed(missing):
        path.mkdir(exist_ok=True)
        os.chmod(path, FOLDER_MODE)


def file_url(fetch, path: str) -> str:
    """Where Hugging Face serves *path* of *fetch*'s repository at its revision."""
    return f"{HUGGING_FACE}/{fetch.huggingface}/resolve/{fetch.revision}/{urllib.parse.quote(path)}"


def _request(url: str, credential: str) -> urllib.request.Request:
    request = urllib.request.Request(url, headers={"User-Agent": "curio-fetch-model-weights"})
    if credential:
        # Unredirected: urllib carries a header added with add_header to the
        # host a redirect names (Hugging Face sends large files from another
        # host), and this one to none.
        request.add_unredirected_header("Authorization", f"Bearer {credential}")
    return request


class TokenOnHuggingFace(urllib.request.HTTPRedirectHandler):
    """Follows a redirect as urllib does, and sends the token again only when
    it leads back to Hugging Face's own host, never to the host that serves
    its large files."""

    def __init__(self, credential: str):
        super().__init__()
        self._credential = credential

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if (
            redirected is not None and self._credential
            and urllib.parse.urlsplit(redirected.full_url).hostname == HUGGING_FACE_HOST
        ):
            redirected.add_unredirected_header("Authorization", f"Bearer {self._credential}")
        return redirected


def _download(opener, url: str, credential: str, target: Path, item, fetch, token_given: bool) -> int:
    """Stream *url* into a temporary file beside *target*, check it against
    *item*'s digest, and move it into place. Returns its size."""
    _make_folder(target.parent)
    try:
        response = opener.open(_request(url, credential), timeout=TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise FetchError(GATED.format(
                path=item.path, repo=fetch.huggingface, status=exc.code,
                page=f"{HUGGING_FACE}/{fetch.huggingface}", variable=TOKEN_VARIABLE,
                tokens=f"{HUGGING_FACE}/settings/tokens",
                given="" if token_given else f"; {TOKEN_VARIABLE} is not set",
            )) from None
        if exc.code == 404:
            raise FetchError(
                f"Hugging Face has no {item.path} in {fetch.huggingface} at {fetch.revision} (HTTP 404)."
            ) from None
        raise FetchError(f"Hugging Face answered HTTP {exc.code} for {item.path}.") from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc.__class__.__name__
        raise FetchError(f"Could not download {item.path} from Hugging Face: {reason}.") from None
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".part")
    partial = Path(name)
    try:
        with os.fdopen(handle, "wb") as sink, response:
            for chunk in iter(lambda: response.read(CHUNK), b""):
                sink.write(chunk)
            sink.flush()
            os.fsync(sink.fileno())
        size = partial.stat().st_size
        kind, actual = digest_of(partial, item)
        expected = item.sha256 if item.sha256 is not None else item.git_sha1
        if actual != expected:
            raise FetchError(
                f"{item.path}: Hugging Face sent {size_text(size)} whose {kind} is {actual}, not the "
                f"{expected} the manifest names, so it was not placed."
            )
        os.chmod(partial, FILE_MODE)
        os.replace(partial, target)
        return size
    finally:
        partial.unlink(missing_ok=True)


def _readable_by_all(folder: Path) -> bool:
    mode = folder.stat().st_mode
    return mode & 0o005 == 0o005


def main(argv=None, *, opener=None, environ=None, shipped_root=None, out=None, err=None) -> int:
    """Fetch the files of the package *argv* names. *opener* opens each
    request (``urllib.request.build_opener()``'s by default), *environ* is
    where the token is read (``os.environ``), and *shipped_root* the folder
    that holds ``packages/`` (Curio's own, through ``utk_curio/shipped.py``)."""
    out = out or sys.stdout
    err = err or sys.stderr
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Fetch the weights a model package names in its manifest's model.fetch, from Hugging Face.",
    )
    parser.add_argument("package", help="the package id, such as model.example.name, or with its major, @1")
    parser.add_argument(
        "--into", metavar="DIR",
        help="write <DIR>/<package id>@<major>/<entry> instead of the package's own folder: "
             "the folder curio.py start --model-weights-dir DIR reads",
    )
    args = parser.parse_args(argv)
    shipped, model_fetch = _modules()

    folder = _package_folder(shipped, args.package, shipped_root)
    package_id, model, fetch = _read_manifest(folder, model_fetch)
    major = int(folder.name.rpartition("@")[2])
    if args.into:
        into = Path(args.into).expanduser().resolve()
        _make_folder(into)
        if not _readable_by_all(into):
            print(f"Note: {into} is not open to every account, and an isolated node reads the weights "
                  f"there: run chmod 755 {into}.", file=err)
        root = model_fetch.fetched_root(into, package_id, major)
    else:
        root = folder
    entry = root / str(model["entry"])
    credential = str(environ.get(TOKEN_VARIABLE) or "").strip()
    token_given = TOKEN_VARIABLE in environ
    opener = opener or urllib.request.build_opener(TokenOnHuggingFace(credential))

    print(f"{package_id}@{major}: {len(fetch.files)} files of {fetch.huggingface} at {fetch.revision}, "
          f"into {entry}", file=out)
    fetched = present = 0
    for item in fetch.files:
        target = entry / item.path
        if target.is_file():
            _kind, actual = digest_of(target, item)
            if actual == (item.sha256 if item.sha256 is not None else item.git_sha1):
                print(f"  {item.path}: {size_text(target.stat().st_size)}, already here", file=out)
                present += 1
                continue
        print(f"  {item.path}: fetching", file=out, flush=True)
        try:
            size = _download(opener, file_url(fetch, item.path), credential, target, item, fetch, token_given)
        except FetchError as exc:
            print(str(exc), file=err)
            return 1
        print(f"  {item.path}: {size_text(size)}, fetched", file=out)
        fetched += 1
    print(f"Done: {fetched} fetched, {present} already here.", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
