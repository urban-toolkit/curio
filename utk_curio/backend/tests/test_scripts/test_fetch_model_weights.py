"""``scripts/fetch_model_weights.py``: a model package's weights, from Hugging Face.

The script reads a shipped package's ``model.fetch`` and downloads each file
it lists from ``https://huggingface.co/<repo>/resolve/<revision>/<path>``,
into the package's entry folder or, with ``--into <dir>``, into
``<dir>/<id>@<major>/<entry>``, the folder ``--model-weights-dir`` reads. Each
file streams to a temporary file, is checked against its digest, and only
then is moved into place, readable by every account.

No test opens a socket: each hands the script an opener that answers from
bytes in memory (``_HuggingFace``) and keeps every request. The token is a
made-up one, and no output may hold it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "fetch_model_weights.py"
PACKAGE_ID = "model.test.prompted"
DIR = f"{PACKAGE_ID}@1"
ENTRY = "models/checkpoint"
REPOSITORY = "acme/tiny-prompted"
REVISION = "3c879f39826c281e95690f02c7821c4de09afae7"
TOKEN = "hf_made_up_token_for_tests"
CONFIG = b'{"model_type": "tiny"}'
WEIGHTS = bytes(range(256)) * 4
FILES = {"config.json": CONFIG, "model.safetensors": WEIGHTS}


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _script():
    spec = importlib.util.spec_from_file_location("_curio_fetch_model_weights", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _HuggingFace:
    """The opener the script is handed: answers each request with the bytes
    *files* hold for the path its URL names, or refuses every request with
    *status*; keeps each request."""

    def __init__(self, files=None, status=None):
        self.files = dict(files or {})
        self.status = status
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.status is not None:
            raise urllib.error.HTTPError(request.full_url, self.status, "refused", {}, io.BytesIO())
        path = urllib.parse.unquote(request.full_url.split(f"/resolve/{REVISION}/", 1)[1])
        if path not in self.files:
            raise AssertionError(f"the script asked for {path}, which was already in place")
        return io.BytesIO(self.files[path])


@pytest.fixture()
def shipped(tmp_path):
    """A folder holding ``packages/`` as Curio ships it, with the test package."""
    folder = tmp_path / "shipped" / "packages" / DIR
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({
        "id": PACKAGE_ID, "version": "1.0.0", "name": "Prompted segmenter", "kind": "model",
        "model": {
            "type": "concept-segmentation", "runtime": "transformers", "entry": ENTRY, "license": "Acme's terms",
            "fetch": {"huggingface": REPOSITORY, "revision": REVISION, "files": [
                {"path": "config.json", "gitSha1": _git_blob_sha1(CONFIG)},
                {"path": "model.safetensors", "sha256": hashlib.sha256(WEIGHTS).hexdigest()},
            ]},
        },
    }), encoding="utf-8")
    return tmp_path / "shipped"


def _run(shipped, *argv, opener, environ=None):
    """``(exit code, stdout, stderr)`` of the script run on *argv*."""
    out, err = io.StringIO(), io.StringIO()
    code = _script().main(
        list(argv), opener=opener, environ={"HF_TOKEN": TOKEN} if environ is None else environ,
        shipped_root=shipped, out=out, err=err,
    )
    return code, out.getvalue(), err.getvalue()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_it_fetches_each_file_checks_it_and_places_it_for_every_account(shipped):
    """Into the package's entry folder, each file at its revision, every
    account able to read it (an isolated node runs as an account of its own),
    whatever the umask; it says each file's name and size."""
    hugging_face = _HuggingFace(FILES)
    umask = os.umask(0o077)
    try:
        code, out, err = _run(shipped, PACKAGE_ID, opener=hugging_face)
    finally:
        os.umask(umask)

    assert (code, err) == (0, "")
    entry = shipped / "packages" / DIR / ENTRY
    assert {name: (entry / name).read_bytes() for name in FILES} == FILES
    assert [_mode(entry / name) for name in FILES] == [0o644, 0o644]
    assert [_mode(entry), _mode(entry.parent)] == [0o755, 0o755]
    assert sorted(path.name for path in entry.iterdir()) == sorted(FILES), "a temporary file was left"
    assert [request.full_url for request in hugging_face.requests] == [
        f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}" for name in FILES
    ]
    assert "config.json: 22 B, fetched" in out and "model.safetensors: 1.02 kB, fetched" in out, out
    assert "Done: 2 fetched, 0 already here." in out, out


def test_the_token_goes_to_hugging_face_alone_and_is_never_printed(shipped):
    """Sent as an unredirected header, which urllib never carries to another
    host; a redirect back to Hugging Face's own host sends it again."""
    script = _script()
    hugging_face = _HuggingFace(FILES)

    code, out, err = _run(shipped, PACKAGE_ID, opener=hugging_face)

    assert code == 0 and TOKEN not in out + err
    for request in hugging_face.requests:
        assert request.unredirected_hdrs == {"Authorization": f"Bearer {TOKEN}"}
        assert "Authorization" not in request.headers
    handler = script.TokenOnHuggingFace(TOKEN)
    request = hugging_face.requests[1]
    to_files = handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://cdn-lfs.hf.co/x?sig=1")
    assert to_files.get_header("Authorization") is None
    back = handler.redirect_request(request, io.BytesIO(), 307, "Temporary Redirect", {},
                                    f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/model.safetensors")
    assert back.get_header("Authorization") == f"Bearer {TOKEN}"
    # urllib's own handler, which an opener holds when given none, never does.
    plain = urllib.request.HTTPRedirectHandler().redirect_request(
        request, io.BytesIO(), 302, "Found", {}, "https://cdn-lfs.hf.co/x?sig=1",
    )
    assert plain.get_header("Authorization") is None


def test_a_file_whose_digest_does_not_match_is_not_placed(shipped):
    code, out, err = _run(shipped, PACKAGE_ID, opener=_HuggingFace({**FILES, "config.json": b"{}"}))

    assert code == 1
    assert err.startswith(f"config.json: Hugging Face sent 2 B whose git blob sha1 is {_git_blob_sha1(b'{}')}, "
                          f"not the {_git_blob_sha1(CONFIG)} the manifest names, so it was not placed."), err
    entry = shipped / "packages" / DIR / ENTRY
    assert list(entry.iterdir()) == [], "a file that does not match, or its temporary file, was left"


def test_a_file_already_in_place_with_its_digest_is_skipped(shipped):
    _run(shipped, PACKAGE_ID, opener=_HuggingFace(FILES))

    code, out, err = _run(shipped, PACKAGE_ID, opener=_HuggingFace())

    assert (code, err) == (0, "")
    assert "config.json: 22 B, already here" in out and "Done: 0 fetched, 2 already here." in out, out


def test_a_file_in_place_whose_digest_differs_is_fetched_again(shipped):
    entry = shipped / "packages" / DIR / ENTRY
    entry.mkdir(parents=True)
    (entry / "config.json").write_bytes(b"stale")

    code, out, _err = _run(shipped, PACKAGE_ID, opener=_HuggingFace(FILES))

    assert code == 0 and (entry / "config.json").read_bytes() == CONFIG
    assert "Done: 2 fetched, 0 already here." in out, out


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("environ, unset", [({"HF_TOKEN": TOKEN}, False), ({}, True)], ids=["a token", "no token"])
def test_a_gated_repository_says_how_to_get_access_and_never_prints_the_token(shipped, status, environ, unset):
    code, out, err = _run(shipped, PACKAGE_ID, opener=_HuggingFace(status=status), environ=environ)

    assert code == 1
    assert err.startswith(
        f"Hugging Face refused config.json of {REPOSITORY} (HTTP {status}). Its files are gated: sign in at "
        f"https://huggingface.co/{REPOSITORY}, accept the terms there, then run this again with HF_TOKEN set "
        "to a token with read access (https://huggingface.co/settings/tokens)"
    ), err
    assert ("HF_TOKEN is not set" in err) is unset, err
    assert TOKEN not in out + err
    assert not (shipped / "packages" / DIR / ENTRY / "config.json").exists()


def test_into_writes_the_folder_model_weights_dir_reads(shipped, tmp_path):
    """``<dir>/<package id>@<major>/<entry>``, where the backend looks with
    ``--model-weights-dir <dir>`` (``model_fetch.fetched_root``); the package's
    own folder is left as it was."""
    from utk_curio.backend.app.packages.domain.model_fetch import fetched_root

    into = tmp_path / "model-weights"

    code, out, err = _run(shipped, f"{PACKAGE_ID}@1", "--into", str(into), opener=_HuggingFace(FILES))

    assert (code, err) == (0, "")
    root = fetched_root(into.resolve(), PACKAGE_ID, 1)
    assert root == into.resolve() / DIR
    assert {name: (root / ENTRY / name).read_bytes() for name in FILES} == FILES
    assert [_mode(into), _mode(root), _mode(root / ENTRY)] == [0o755, 0o755, 0o755]
    assert not (shipped / "packages" / DIR / "models").exists()
    assert str(root / ENTRY) in out, out


def test_a_package_that_names_nothing_to_fetch_or_that_curio_does_not_ship_is_refused(shipped):
    manifest = shipped / "packages" / DIR / "manifest.json"
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    del raw["model"]["fetch"]
    manifest.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(SystemExit, match="names no weights to fetch"):
        _run(shipped, PACKAGE_ID, opener=_HuggingFace())
    with pytest.raises(SystemExit, match="Curio ships no package model.test.absent"):
        _run(shipped, "model.test.absent", opener=_HuggingFace())
    with pytest.raises(SystemExit, match="is not a package id"):
        _run(shipped, "../model.test.prompted", opener=_HuggingFace())
