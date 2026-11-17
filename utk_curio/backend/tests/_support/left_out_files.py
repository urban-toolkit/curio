"""A release record and a GitHub that the left-out files tests control.

The pip package leaves a few big catalog files out, and a pip install
downloads each from raw.githubusercontent.com the first time Curio needs it
(``datasets/infrastructure/left_out_files.py``). The manifest of each one's
dataset or model package names it in ``downloadOnFirstUse``. No test may open
a socket (``tests/netguard.py``), so ``FakeGitHub`` stands in for both seams
``egress.download`` takes: the transport and the DNS resolver. It answers with
the repository's own bytes, which are the bytes a release would serve.

The module under test is imported inside the functions that need it, so a
test module importing this one still loads on a tree without it.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[4]
#: The files the pip package leaves out, the one place a test writes them:
#: the data files of eleven datasets and Deep Umbra's weights.
#: ``test_left_out_files.py`` checks that the manifests name exactly these.
EXPECTED = (
    "datasets/data.cityofchicago.red-light-violations@1/data/red-light-violations.parquet",
    "datasets/data.cityofchicago.speed-camera-violations@1/data/speed-camera-violations.parquet",
    "datasets/data.projectsidewalk.chicago-labels@1/data/chicago-labels.parquet",
    "datasets/data.scout.flood-depth-2020-2050-nbs@1/data/flood-depth-2020-2050-nbs.tif",
    "datasets/data.scout.flood-depth-2020-2050-no-nbs@1/data/flood-depth-2020-2050-no-nbs.tif",
    "datasets/data.scout.flood-depth-2050-2080-nbs@1/data/flood-depth-2050-2080-nbs.tif",
    "datasets/data.scout.flood-depth-2050-2080-no-nbs@1/data/flood-depth-2050-2080-no-nbs.tif",
    "datasets/data.scout.flood-depth-2080-2100-nbs@1/data/flood-depth-2080-2100-nbs.tif",
    "datasets/data.scout.flood-depth-2080-2100-no-nbs@1/data/flood-depth-2080-2100-no-nbs.tif",
    "datasets/data.scout.flood-nbs-classes@1/data/flood-nbs-classes.tif",
    "datasets/data.utk.milan-mrt@1/data/milan-mrt.tif",
    "packages/model.scout.deep-umbra@1/models/deep_umbra.onnx",
)
#: The commit a test's release is built from.
COMMIT = "0123456789abcdef0123456789abcdef01234567"
#: An address raw.githubusercontent.com resolves to: public, so the egress
#: policy lets it through.
GITHUB_ADDRESS = "185.199.108.133"
RAW = "https://raw.githubusercontent.com/urban-toolkit/curio"


def listed() -> list[str]:
    """The repository paths of the files the pip package leaves out."""
    return list(EXPECTED)


def url_of(repo_path: str, commit: str = COMMIT) -> str:
    return f"{RAW}/{commit}/{repo_path}"


def write_record(path: Path, repo_paths, *, commit: str = COMMIT, contents=None) -> Path:
    """A record as the release build writes it: each file's size and sha256,
    from the repository's bytes or from *contents* (``{repo path: bytes}``)."""
    contents = contents or {}
    files = {}
    for repo_path in repo_paths:
        data = contents[repo_path] if repo_path in contents else (REPO / repo_path).read_bytes()
        files[repo_path] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    path.write_text(json.dumps({"commit": commit, "files": files}, indent=2), encoding="utf-8")
    return path


def shipped_catalog_bytes(repo: Path) -> int:
    """The bytes of ``datasets/`` under *repo* that the Data Catalog's size
    budget counts (``test_catalog_dataset_coverage.py``)."""
    return sum(path.stat().st_size for path in (Path(repo) / "datasets").rglob("*") if path.is_file())


def catalog_copy(folder: str, root: Path) -> Path:
    """The repository's catalog folder *folder* (``datasets/<dir>`` or
    ``packages/<dir>``) copied under *root* without the files the pip package
    leaves out, as a pip install has it. Returns the copy."""
    left_out = set(listed())
    for path in sorted((REPO / folder).rglob("*")):
        rel = path.relative_to(REPO).as_posix()
        if not path.is_file() or rel in left_out:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return root / folder


_RANGE = re.compile(r"^bytes=(\d+)-$")


def answer_with(body: bytes, headers=None, *, ranges: bool = True, cut=None, chunk_size=None):
    """``(status, headers, location, chunks)``: *body* as a file host answers
    a ``GET`` sent with *headers*. A ``Range: bytes=<n>-`` gets the rest of
    the file from byte n, 206 with its ``Content-Range``, or 416 when n is
    not before the file's end; with *ranges* False the host ignores it and
    sends the whole file, as a host that serves no ranges does. *cut*, an
    exception, is raised once the first half of what is sent has gone, as a
    connection dropped mid-download does. *chunk_size* sends the bytes in
    chunks of that many."""
    asked = _RANGE.match(str((headers or {}).get("Range") or "")) if ranges else None
    start = int(asked.group(1)) if asked else None
    if start is not None and start >= len(body):
        return 416, {"Content-Range": f"bytes */{len(body)}", "Content-Length": "0"}, None, iter([])
    sent = body if start is None else body[start:]
    answer = {"Content-Length": str(len(sent))}
    if start is not None:
        answer["Content-Range"] = f"bytes {start}-{len(body) - 1}/{len(body)}"
    half = len(sent) // 2

    def pieces(part: bytes):
        step = chunk_size or max(len(part), 1)
        for offset in range(0, len(part), step):
            yield part[offset:offset + step]

    def chunks():
        yield from pieces(sent[:half])
        if cut is not None:
            raise cut
        yield from pieces(sent[half:])

    return (200 if start is None else 206), answer, None, chunks()


class FakeGitHub:
    """Answers ``GET https://raw.githubusercontent.com/urban-toolkit/curio/<commit>/<path>``
    with the repository's bytes, or with *contents* (``{repo path: bytes}``),
    as :func:`answer_with` answers.

    Keeps every URL asked for, and every request with the headers it was sent
    with. *fail*, an exception, is raised instead of answering; *cut* sends
    the first half of the body and then raises it, as a connection dropped
    mid-download does. *ranges* and *chunk_size* are :func:`answer_with`'s.
    """

    def __init__(self, *, commit: str = COMMIT, contents=None, fail=None, cut=None, ranges=True, chunk_size=None):
        self.commit = commit
        self.contents = dict(contents or {})
        self.fail = fail
        self.cut = cut
        self.ranges = ranges
        self.chunk_size = chunk_size
        self.urls: list[str] = []
        self.requests: list[SimpleNamespace] = []
        self.hosts: list[str] = []

    def resolver(self, host: str) -> list[str]:
        self.hosts.append(host)
        return [GITHUB_ADDRESS]

    def body(self, repo_path: str) -> bytes | None:
        if repo_path in self.contents:
            return self.contents[repo_path]
        path = REPO / repo_path
        return path.read_bytes() if path.is_file() else None

    def request(self, method, url, *, trusted_host=None, headers=None, timeout_s=None):
        self.urls.append(url)
        self.requests.append(SimpleNamespace(method=method, url=url, headers=dict(headers or {})))
        if self.fail is not None:
            raise self.fail
        prefix = f"{RAW}/{self.commit}/"
        body = self.body(url[len(prefix):]) if method == "GET" and url.startswith(prefix) else None
        if body is None:
            return 404, {"Content-Length": "14"}, None, iter([b"404: Not Found"])
        return answer_with(body, headers, ranges=self.ranges, cut=self.cut, chunk_size=self.chunk_size)

    def serve(self, monkeypatch) -> "FakeGitHub":
        """Make this the GitHub the module under test downloads from."""
        from utk_curio.backend.app.datasets.infrastructure import left_out_files

        monkeypatch.setattr(left_out_files, "request_fn", self.request)
        monkeypatch.setattr(left_out_files, "resolver", self.resolver)
        return self
