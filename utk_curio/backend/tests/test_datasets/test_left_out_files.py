"""The files the pip package leaves out, and a pip install fetching them.

PyPI takes no file over 100 MiB, and the wheel and the sdist were over it. The
repository keeps every catalog file; the pip package leaves out the big ones,
each named in ``downloadOnFirstUse`` by the manifest of its dataset or model
package, and a pip install downloads each from GitHub the first time Curio
needs it: from the commit its package was built from, checked against the
size and sha256 the release build recorded, through the egress policy, into
Curio's state directory.

- The packaging: the manifests name exactly the twelve files ``EXPECTED``
  lists; ``MANIFEST.in`` and ``setup.py``, applied as setuptools applies
  them, leave out exactly those and the frontend's source maps; the release
  script records each. A new dataset's manifest is all it takes to leave its
  file out, a folder a manifest names leaves out every file in it, and no
  file of the release names a dataset or a package.
- The fetch: a missing listed file is fetched, verified and placed, then read
  where it was placed; a wrong sha256, a refused address, a dropped
  connection or a checkout without a record places nothing; a file the
  package holds is never fetched; two readers fetch a file once; the fetched
  folder is its owner's alone; a download removes other releases' files.
- The readers: the Data Catalog's details, preview, download and install, and
  a node's ``curio_load_data``, on a catalog laid out as a pip install has it.

No test opens a socket: ``FakeGitHub`` stands in for the transport and the
resolver. The module under test is imported inside each test.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.left_out_files import (
    COMMIT,
    EXPECTED,
    REPO,
    FakeGitHub,
    catalog_copy,
    listed,
    url_of,
    write_record,
)

SIDEWALK = "datasets/data.projectsidewalk.chicago-labels@1/data/chicago-labels.parquet"
SIDEWALK_FOLDER = "datasets/data.projectsidewalk.chicago-labels@1"
MRT = "datasets/data.utk.milan-mrt@1/data/milan-mrt.tif"
RED_LIGHT = "datasets/data.cityofchicago.red-light-violations@1/data/red-light-violations.parquet"
#: SCOUT's seven flood rasters, whole, which the quad-cities-flood-vulnerability test dataflow reads.
FLOOD = [
    "datasets/data.scout.flood-nbs-classes@1/data/flood-nbs-classes.tif",
    *(
        f"datasets/data.scout.flood-depth-{period}-{kind}@1/data/flood-depth-{period}-{kind}.tif"
        for period in ("2020-2050", "2050-2080", "2080-2100")
        for kind in ("nbs", "no-nbs")
    ),
]
FLOOD_DATAFLOW = REPO / "docs" / "examples" / "dataflows" / "quad-cities-flood-vulnerability.json"
#: What a test's GitHub serves for SIDEWALK: small, so the fetch tests are quick.
PAYLOAD = b"PAR1" + bytes(range(256)) * 64 + b"PAR1"
CLONE = "https://github.com/urban-toolkit/curio"

#: A built frontend: its bundles, and the source maps beside them.
DIST = "utk_curio/frontend/urban-workflows/dist"
BUILT = [f"{DIST}/index.html", f"{DIST}/main.js", f"{DIST}/main.js.map", f"{DIST}/vendors.js", f"{DIST}/vendors.js.map"]
INFRASTRUCTURE = "utk_curio/backend/app/datasets/infrastructure"
#: What the release runs to leave the files out and record them
#: (``publish-pip-to-pypi.yml``), and the module that downloads them.
RELEASE_FILES = (
    "setup.py",
    "MANIFEST.in",
    "utk_curio/shipped.py",
    "scripts/record_left_out_files.py",
    "scripts/check_dist_sizes.py",
    f"{INFRASTRUCTURE}/left_out_files.py",
)


def _module():
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    return left_out_files


def _by_path(name: str, path: Path):
    """The module at *path*, loaded by its path rather than run."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record_script():
    return _by_path("_curio_record_left_out_files", REPO / "scripts" / "record_left_out_files.py")


def _setup_py():
    """``setup.py``, not as ``__main__``, so ``setup()`` does not run."""
    return _by_path("_curio_setup", REPO / "setup.py")


def _tree(root: Path, files: dict) -> Path:
    """*files*, ``{repository path: bytes, or a manifest as a dict}``, written
    under *root*: a repository's catalogs in small."""
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(content).encode("utf-8") if isinstance(content, dict) else content)
    return root


def _dataset(dataset_id: str, data_file: str, **fields) -> dict:
    return {
        "id": dataset_id, "name": dataset_id, "version": "1.0.0", "format": "csv",
        "dataFile": data_file, "compatibility": {"major": 1}, **fields,
    }


def _files_under(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _kept_by_the_build(root: Path, files: set[str]) -> set[str]:
    """Of *files*, paths under *root*, those the sdist and the wheel ship:
    ``setup.py`` drops from setuptools' list of the files that ship what the
    manifests under *root* name in ``downloadOnFirstUse``."""
    from setuptools.command.egg_info import FileList

    kept = FileList()
    kept.files = sorted(files)
    _setup_py().leave_out_first_use_files(kept, root)
    return set(kept.files)


def _auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _only_locks(root: Path) -> bool:
    """Nothing but lock files under *root*: no file placed, no partial left."""
    return all(path.suffix == ".lock" for path in root.rglob("*") if path.is_file())


# ---------------------------------------------------------------------------
# The packaging
# ---------------------------------------------------------------------------

def test_the_list_names_catalog_files_the_repository_holds():
    """Each listed file is in the repository, and is the data file of a Data
    Catalog dataset or the weights a model package's ``model`` block names:
    the one big file of its folder, whose small files (manifest, sidecars,
    code) still ship. Deep Umbra's weights are its model package's."""
    files = listed()
    assert files and len(files) == len(set(files)), files
    for repo_path in files:
        assert (REPO / repo_path).is_file(), repo_path
        kind, folder, *rest = repo_path.split("/")
        assert kind in ("datasets", "packages") and rest, repo_path
        manifest = json.loads((REPO / kind / folder / "manifest.json").read_text(encoding="utf-8"))
        if kind == "datasets":
            named = manifest.get("dataFile")
        else:
            assert manifest.get("kind") == "model", repo_path
            named = manifest["model"]["entry"]
        assert "/".join(rest) == named, (repo_path, named)
    assert "packages/model.scout.deep-umbra@1/models/deep_umbra.onnx" in files


def test_manifest_in_and_setup_py_leave_out_exactly_the_listed_files_and_the_frontends_source_maps(monkeypatch):
    """``MANIFEST.in`` and ``setup.py`` build the sdist, and the release
    builds the wheel from the sdist (``publish-pip-to-pypi.yml``).
    ``MANIFEST.in``'s rules, applied as setuptools applies them, every line in
    order, then what ``setup.py``'s ``egg_info`` drops from that list (the
    files the manifests name in ``downloadOnFirstUse``), to every file under
    ``datasets/``, ``models/`` and ``packages/``, the release's record, the
    repository's ``package.json`` and ``package-lock.json`` (``setup.py``
    copies them into the wheel), and a built frontend: the listed files and
    the frontend's source maps stay out, and nothing else does. A package's
    own source map ships: ``curio.example-ui@1`` names it in its
    ``integrity.json``."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    repository = sorted(
        path.relative_to(REPO).as_posix()
        for folder in ("datasets", "models", "packages")
        for path in (REPO / folder).rglob("*")
        if path.is_file()
    )
    shipped_beside_the_code = [f"{INFRASTRUCTURE}/left_out_files.record.json"]
    node_packages = ["package.json", "package-lock.json"]
    everything = set(repository) | set(BUILT) | set(shipped_beside_the_code) | set(node_packages)
    files = FileList()
    files.set_allfiles(sorted(everything))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            files.process_template_line(line)
    _setup_py().leave_out_first_use_files(files)
    shipped = set(files.files)

    left_out = set(listed())
    source_maps = {path for path in BUILT if path.endswith(".map")}
    assert left_out <= set(repository), sorted(left_out - set(repository))
    assert shipped == everything - left_out - source_maps, (
        sorted(shipped - (everything - left_out - source_maps)),
        sorted((everything - left_out - source_maps) - shipped),
    )
    assert "packages/curio.example-ui@1/scripts/behaviors.js.map" in shipped


def test_the_release_records_each_listed_file_with_its_size_and_sha256(tmp_path):
    """``scripts/record_left_out_files.py``, which the release workflow runs
    before ``python -m build``: the commit, and each listed file's size and
    sha256, which Curio then reads as this release's record."""
    out = tmp_path / "record.json"
    run = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "record_left_out_files.py"), "--commit", COMMIT, "--out", str(out)],
        cwd=REPO, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["commit"] == COMMIT
    assert sorted(record["files"]) == sorted(listed())
    for repo_path, entry in record["files"].items():
        data = (REPO / repo_path).read_bytes()
        assert entry == {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}, repo_path

    read = _module().read_record(out)
    assert read.commit == COMMIT
    assert {path: (f.size, f.sha256) for path, f in read.files.items()} == {
        path: (entry["size"], entry["sha256"]) for path, entry in record["files"].items()
    }


def test_the_record_names_a_commit(tmp_path):
    """A release is built from a commit, and the record says which: a branch
    name or a short hash is refused, and nothing is written."""
    out = tmp_path / "record.json"
    for commit in ("main", COMMIT[:9]):
        run = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "record_left_out_files.py"), "--commit", commit, "--out", str(out)],
            cwd=REPO, capture_output=True, text=True,
        )
        assert run.returncode != 0, run.stdout
        assert "commit" in (run.stdout + run.stderr)
        assert not out.exists()


def test_the_manifests_name_exactly_the_files_the_pip_package_leaves_out(monkeypatch):
    """Each of the twelve files (``EXPECTED``) is named in
    ``downloadOnFirstUse`` by the manifest of its dataset or model package, by
    its path in that folder, and no manifest names another. A running Curio
    reads the same twelve from the manifests."""
    named = set()
    for catalog in ("datasets", "packages"):
        for manifest in sorted((REPO / catalog).glob("*/manifest.json")):
            for rel in json.loads(manifest.read_text(encoding="utf-8")).get("downloadOnFirstUse", []):
                named.add(f"{catalog}/{manifest.parent.name}/{rel}")
    assert named == set(EXPECTED), (sorted(named - set(EXPECTED)), sorted(set(EXPECTED) - named))

    module = _module()
    monkeypatch.setattr(module, "SHIPPED_ROOT", REPO)
    assert sorted(module.left_out_paths()) == sorted(EXPECTED)
    assert all(module.is_left_out(repo_path) for repo_path in EXPECTED)


def test_a_new_dataset_that_names_its_data_file_is_left_out_with_no_list_edit(tmp_path, monkeypatch):
    """Its manifest is all it takes: the release records the file, the
    sdist's file list leaves it out, and a running Curio counts it as a file
    to download on first use. Another dataset's file ships."""
    module = _module()
    big = "datasets/data.test.big@1/data/big.csv"
    small = "datasets/data.test.small@1/data/small.csv"
    root = _tree(tmp_path / "repo", {
        "datasets/data.test.big@1/manifest.json": _dataset(
            "data.test.big", "data/big.csv", downloadOnFirstUse=["data/big.csv"],
        ),
        big: b"a,b\n1,2\n",
        "datasets/data.test.small@1/manifest.json": _dataset("data.test.small", "data/small.csv"),
        small: b"a\n1\n",
    })

    record = _record_script().build_record(root, COMMIT)
    assert record == {
        "commit": COMMIT,
        "files": {big: {"size": 8, "sha256": hashlib.sha256(b"a,b\n1,2\n").hexdigest()}},
    }
    everything = _files_under(root)
    assert _kept_by_the_build(root, everything) == everything - {big}

    monkeypatch.setattr(module, "SHIPPED_ROOT", root)
    assert module.left_out_paths() == (big,)
    assert module.is_left_out(big) and not module.is_left_out(small)


def test_a_folder_a_manifest_names_leaves_out_every_file_in_it(tmp_path, monkeypatch):
    """A model package names its checkpoint's folder: each file in it is
    recorded and left out of the sdist, and a running Curio counts each as a
    file to download, as the folder holds them in a checkout and as the
    release recorded them in a pip install. The package's other files ship."""
    module = _module()
    folder = "packages/ai.test.checkpoint@1"
    inside = [f"{folder}/models/checkpoint/config.json", f"{folder}/models/checkpoint/weights.bin"]
    code = f"{folder}/sources/run.py"
    contents = {inside[0]: b"{}", inside[1]: bytes(range(64))}
    root = _tree(tmp_path / "repo", {
        f"{folder}/manifest.json": {
            "id": "ai.test.checkpoint", "version": "1.0.0", "name": "Checkpoint", "publisher": "Test",
            "compatibility": {"major": 1}, "kind": "model",
            "templates": [{"id": "run", "label": "Run", "category": "computation", "engine": "python",
                           "editor": "code", "inputPorts": [], "outputPorts": [{"types": ["JSON"]}]}],
            "model": {"type": "semantic-segmentation", "runtime": "transformers", "entry": "models/checkpoint",
                      "license": "MIT"},
            "downloadOnFirstUse": ["models/checkpoint"],
        },
        code: b"return 1\n",
        **contents,
    })

    assert sorted(_record_script().build_record(root, COMMIT)["files"]) == inside
    everything = _files_under(root)
    assert _kept_by_the_build(root, everything) == everything - set(inside)

    monkeypatch.setattr(module, "SHIPPED_ROOT", root)
    assert module.left_out_paths() == tuple(inside)
    assert all(module.is_left_out(repo_path) for repo_path in inside)
    assert not module.is_left_out(code) and not module.is_left_out(f"{folder}/manifest.json")

    site = tmp_path / "site"
    shutil.copytree(root / folder, site / folder, ignore=shutil.ignore_patterns("models"))
    monkeypatch.setattr(module, "SHIPPED_ROOT", site)
    monkeypatch.setattr(module, "RECORD_PATH", write_record(tmp_path / "record.json", inside, contents=contents))
    assert not (site / folder / "models").exists()
    assert module.left_out_paths() == tuple(inside)


def test_a_manifest_that_names_a_path_outside_its_folder_stops_the_release(tmp_path, monkeypatch):
    """The record and the sdist's file list refuse it, so the release leaves
    out nothing but files of a catalog folder; a running Curio counts nothing
    from that manifest."""
    module = _module()
    root = _tree(tmp_path / "repo", {
        "datasets/data.test.escape@1/manifest.json": _dataset(
            "data.test.escape", "data/x.csv", downloadOnFirstUse=["../../setup.py"],
        ),
        "datasets/data.test.escape@1/data/x.csv": b"a\n1\n",
        "setup.py": b"",
    })

    with pytest.raises(ValueError, match="downloadOnFirstUse"):
        _record_script().build_record(root, COMMIT)
    with pytest.raises(ValueError, match="downloadOnFirstUse"):
        _kept_by_the_build(root, _files_under(root))
    monkeypatch.setattr(module, "SHIPPED_ROOT", root)
    assert module.left_out_paths() == ()
    assert not module.is_left_out("setup.py")


def test_the_release_stops_at_a_named_file_the_checkout_lacks(tmp_path):
    big = "datasets/data.test.big@1/data/big.csv"
    root = _tree(tmp_path / "repo", {
        "datasets/data.test.big@1/manifest.json": _dataset(
            "data.test.big", "data/big.csv", downloadOnFirstUse=["data/big.csv"],
        ),
    })

    with pytest.raises(FileNotFoundError, match=re.escape(big)):
        _record_script().build_record(root, COMMIT)


def test_no_release_file_names_a_dataset_or_a_package():
    """The manifests decide what the pip package leaves out: no file of the
    release, nor the module that downloads the files, names a shipped dataset
    or package, by id or by folder, and no list of the files is kept beside
    the module."""
    names = set()
    for catalog in ("datasets", "packages"):
        for manifest in (REPO / catalog).glob("*/manifest.json"):
            names |= {manifest.parent.name, json.loads(manifest.read_text(encoding="utf-8"))["id"]}
    assert len(names) > 50, sorted(names)
    found = sorted(
        f"{rel} names {name}"
        for rel in RELEASE_FILES
        for name in names
        if name in (REPO / rel).read_text(encoding="utf-8")
    )
    assert not found, found
    assert not (REPO / INFRASTRUCTURE / "left_out_files.json").exists()


# ---------------------------------------------------------------------------
# The fetch
# ---------------------------------------------------------------------------

@pytest.fixture()
def pip_tree(tmp_path, monkeypatch):
    """A pip install's view of SIDEWALK: its catalog folder without the data
    file, Curio's state directory, and a release record for PAYLOAD."""
    module = _module()
    monkeypatch.setenv("CURIO_STATE_DIR", str(tmp_path / "state"))
    record = write_record(tmp_path / "record.json", [SIDEWALK], contents={SIDEWALK: PAYLOAD})
    monkeypatch.setattr(module, "RECORD_PATH", record)
    root = tmp_path / "site-packages"
    catalog_copy(SIDEWALK_FOLDER, root)
    return SimpleNamespace(module=module, root=root, shipped=root / SIDEWALK, state=tmp_path / "state")


def test_a_left_out_file_is_fetched_verified_and_placed_on_first_read(pip_tree, monkeypatch):
    m = pip_tree.module
    github = FakeGitHub(contents={SIDEWALK: PAYLOAD}).serve(monkeypatch)
    assert not pip_tree.shipped.exists()

    placed = m.fetch(SIDEWALK, pip_tree.shipped)

    assert github.urls == [url_of(SIDEWALK)]
    # The egress policy resolved the host before anything was asked of it.
    assert github.hosts == ["raw.githubusercontent.com"]
    assert placed == m.fetched_root(COMMIT) / SIDEWALK
    assert placed.is_relative_to(pip_tree.state)
    assert placed.read_bytes() == PAYLOAD
    # Readable by the execution account an isolated node runs as.
    assert stat.S_IMODE(placed.stat().st_mode) == 0o644
    # Beside it, what a reader finds beside it in a clone: the manifest and the
    # parquet's decode sidecar.
    folder = m.fetched_root(COMMIT) / SIDEWALK_FOLDER
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [
        "data/chicago-labels.parquet", "data/chicago-labels.parquet.decode.json", "manifest.json",
    ]
    for rel in ("manifest.json", "data/chicago-labels.parquet.decode.json"):
        assert (folder / rel).read_bytes() == (pip_tree.root / SIDEWALK_FOLDER / rel).read_bytes()

    # Read again: it is where it was placed, and nothing is fetched.
    assert m.fetch(SIDEWALK, pip_tree.shipped) == placed
    assert placed.read_bytes() == PAYLOAD
    assert len(github.urls) == 1


def test_a_file_with_another_sha256_is_refused_and_nothing_is_placed(pip_tree, monkeypatch):
    m = pip_tree.module
    tampered = PAYLOAD[:-1] + b"X"
    FakeGitHub(contents={SIDEWALK: tampered}).serve(monkeypatch)

    with pytest.raises(m.LeftOutFileUnavailable) as raised:
        m.fetch(SIDEWALK, pip_tree.shipped)

    assert "sha256" in str(raised.value) and SIDEWALK in str(raised.value)
    assert not (m.fetched_root(COMMIT) / SIDEWALK).exists()
    assert _only_locks(m.fetched_root(COMMIT))


def test_a_file_the_package_holds_is_never_fetched(pip_tree, monkeypatch):
    m = pip_tree.module
    github = FakeGitHub(fail=AssertionError("a file the package holds was fetched")).serve(monkeypatch)
    pip_tree.shipped.write_bytes(b"shipped in the package")

    assert m.fetch(SIDEWALK, pip_tree.shipped) == pip_tree.shipped
    assert github.urls == []


def test_a_checkout_has_no_record_and_never_downloads(pip_tree, monkeypatch, tmp_path):
    """A clone holds every file; one that lost a listed file says where the
    file is, and asks GitHub nothing, since no release recorded it."""
    m = pip_tree.module
    github = FakeGitHub(contents={SIDEWALK: PAYLOAD}).serve(monkeypatch)
    monkeypatch.setattr(m, "RECORD_PATH", tmp_path / "no-record.json")

    with pytest.raises(m.LeftOutFileUnavailable) as raised:
        m.fetch(SIDEWALK, pip_tree.shipped)

    assert github.urls == []
    assert SIDEWALK in str(raised.value) and CLONE in str(raised.value)


def test_a_failed_download_says_what_failed_and_how_to_get_the_file(pip_tree, monkeypatch):
    m = pip_tree.module
    FakeGitHub(fail=OSError("Network is unreachable")).serve(monkeypatch)

    with pytest.raises(m.LeftOutFileUnavailable) as raised:
        m.fetch(SIDEWALK, pip_tree.shipped)

    message = str(raised.value)
    target = m.fetched_root(COMMIT) / SIDEWALK
    for words in (SIDEWALK, url_of(SIDEWALK), "Network is unreachable", str(target), CLONE):
        assert words in message, message
    assert not target.exists()
    assert _only_locks(m.fetched_root(COMMIT))


def test_the_download_goes_through_the_egress_policy(pip_tree, monkeypatch):
    """A host that resolves to a private address is refused before any request."""
    m = pip_tree.module
    github = FakeGitHub(contents={SIDEWALK: PAYLOAD}).serve(monkeypatch)
    monkeypatch.setattr(m, "resolver", lambda host: ["169.254.169.254"])

    with pytest.raises(m.LeftOutFileUnavailable) as raised:
        m.fetch(SIDEWALK, pip_tree.shipped)

    assert github.urls == []
    assert "non-public address" in str(raised.value)
    assert not (m.fetched_root(COMMIT) / SIDEWALK).exists()


def test_a_partial_download_never_counts_as_present(pip_tree, monkeypatch):
    m = pip_tree.module
    FakeGitHub(contents={SIDEWALK: PAYLOAD}, cut=OSError("Connection reset by peer")).serve(monkeypatch)

    with pytest.raises(m.LeftOutFileUnavailable) as raised:
        m.fetch(SIDEWALK, pip_tree.shipped)

    assert "Connection reset by peer" in str(raised.value)
    assert not (m.fetched_root(COMMIT) / SIDEWALK).exists()
    assert _only_locks(m.fetched_root(COMMIT))

    # The next read fetches it whole.
    github = FakeGitHub(contents={SIDEWALK: PAYLOAD}).serve(monkeypatch)
    assert m.fetch(SIDEWALK, pip_tree.shipped).read_bytes() == PAYLOAD
    assert len(github.urls) == 1


def test_two_readers_fetch_a_file_once(pip_tree, monkeypatch):
    """While one reader downloads a file, a second waits for it rather than
    downloading it again, then reads what the first placed."""
    m = pip_tree.module
    github = FakeGitHub(contents={SIDEWALK: PAYLOAD})
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_request(method, url, **kwargs):
        calls.append(url)
        entered.set()
        assert release.wait(30)
        return github.request(method, url, **kwargs)

    monkeypatch.setattr(m, "request_fn", slow_request)
    monkeypatch.setattr(m, "resolver", github.resolver)
    results, errors = [], []

    def read():
        try:
            results.append(m.fetch(SIDEWALK, pip_tree.shipped))
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    first = threading.Thread(target=read)
    first.start()
    assert entered.wait(30)
    second = threading.Thread(target=read)
    second.start()
    time.sleep(0.5)
    assert len(calls) == 1, calls
    release.set()
    first.join(30)
    second.join(30)

    assert errors == []
    assert len(calls) == 1, calls
    target = m.fetched_root(COMMIT) / SIDEWALK
    assert results == [target, target]
    assert target.read_bytes() == PAYLOAD


def test_the_fetched_folder_is_its_owners_alone(pip_tree, monkeypatch):
    """As the sandbox's isolation leaves the shipped models: an execution
    account reaches a fetched file only through the hardlink a run stages, and
    cannot rename or replace one. The fetch closes the folder itself, since a
    pip install's first fetch usually comes after the sandbox hardened what
    existed when it started."""
    m = pip_tree.module
    FakeGitHub(contents={SIDEWALK: PAYLOAD}).serve(monkeypatch)
    m.fetched_dir().mkdir(parents=True)
    m.fetched_dir().chmod(0o777)

    m.fetch(SIDEWALK, pip_tree.shipped)

    assert m.fetched_dir().is_relative_to(pip_tree.state)
    assert stat.S_IMODE(m.fetched_dir().stat().st_mode) == 0o700


#: A release other than the one the record names.
OTHER_COMMIT = "fedcba9876543210fedcba9876543210fedcba98"


def test_a_download_removes_the_files_of_other_releases(pip_tree, monkeypatch, tmp_path):
    """An upgrade fetches into its own release's folder, and its first download
    removes the folders of other releases. Nothing else goes: not this
    release's other files, not a folder whose name is no commit, and not a
    symlink or what it points at."""
    m = pip_tree.module
    FakeGitHub(contents={SIDEWALK: PAYLOAD}).serve(monkeypatch)
    fetched = m.fetched_dir()
    older = fetched / OTHER_COMMIT / MRT
    older.parent.mkdir(parents=True)
    older.write_bytes(b"an older release's raster")
    ours = fetched / COMMIT / "packages" / "model.scout.deep-umbra@1" / "manifest.json"
    ours.parent.mkdir(parents=True)
    ours.write_text("{}", encoding="utf-8")
    notes = fetched / "notes"
    notes.mkdir()
    (notes / "readme.txt").write_text("kept", encoding="utf-8")
    outside = tmp_path / "outside"
    (outside / "datasets").mkdir(parents=True)
    (outside / "datasets" / "kept.txt").write_text("kept", encoding="utf-8")
    link = fetched / ("a" * 40)
    link.symlink_to(outside, target_is_directory=True)

    m.fetch(SIDEWALK, pip_tree.shipped)

    assert not (fetched / OTHER_COMMIT).exists()
    assert (fetched / COMMIT / SIDEWALK).read_bytes() == PAYLOAD
    assert ours.read_text(encoding="utf-8") == "{}"
    assert (notes / "readme.txt").read_text(encoding="utf-8") == "kept"
    assert link.is_symlink()
    assert (outside / "datasets" / "kept.txt").read_text(encoding="utf-8") == "kept"


# ---------------------------------------------------------------------------
# The Data Catalog and a node, on a pip install's catalog
# ---------------------------------------------------------------------------

@pytest.fixture()
def pip_catalog(tmp_path, monkeypatch):
    """The Data Catalog as a pip install has it: two shipped datasets whose
    data files the package leaves out, and the release's record of them."""
    module = _module()
    root = tmp_path / "site-packages"
    for repo_path in (MRT, RED_LIGHT):
        catalog_copy("/".join(repo_path.split("/")[:2]), root)
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(root / "datasets"))
    monkeypatch.setattr(module, "RECORD_PATH", write_record(tmp_path / "record.json", [MRT, RED_LIGHT]))
    assert not (root / MRT).exists() and not (root / RED_LIGHT).exists()
    return root


def _capture_sandbox(monkeypatch):
    """The backend's call to the sandbox, recorded instead of made."""
    captured = {}

    class Reply:
        status_code = 200

        def json(self):
            return {"stdout": [], "stderr": "", "output": {"path": "", "dataType": "str"}}

    def call(method, path, **kwargs):
        captured["body"] = json.loads(kwargs["data"])
        return Reply()

    monkeypatch.setattr("utk_curio.backend.app.execution.node_exec.sandbox_request", call)
    return captured


def _run_code(client, token, code):
    return client.post(
        "/processPythonCode",
        data=json.dumps({
            "code": code,
            "nodeType": "PYTHON_COMPUTATION",
            "input": {"path": "", "dataType": "str"},
            "saveOutputDataset": False,
        }),
        headers=_auth(token),
    )


def test_details_give_a_left_out_files_size_and_a_download_reads_it(client, user_and_token, pip_catalog, monkeypatch):
    """The details give the recorded size without downloading anything; the
    first read of the file fetches it, and the next reads it where it was
    placed."""
    _, token = user_and_token
    github = FakeGitHub().serve(monkeypatch)

    details = client.get("/api/datasets/data.utk.milan-mrt", headers=_auth(token))
    assert details.status_code == 200, details.get_data(as_text=True)
    assert details.get_json()["sizeBytes"] == (REPO / MRT).stat().st_size
    assert github.urls == []

    for _ in range(2):
        resp = client.get("/api/datasets/data.utk.milan-mrt/download", headers=_auth(token))
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.data == (REPO / MRT).read_bytes()
        resp.close()
    assert github.urls == [url_of(MRT)]


def test_a_preview_reads_a_left_out_dataset_after_fetching_it(client, user_and_token, pip_catalog, monkeypatch):
    _, token = user_and_token
    github = FakeGitHub().serve(monkeypatch)

    resp = client.get(
        "/api/datasets/data.cityofchicago.red-light-violations/preview?rowLimit=2", headers=_auth(token)
    )

    assert resp.status_code == 200, resp.get_data(as_text=True)
    preview = resp.get_json()
    assert not preview.get("unsupported"), preview
    assert len(preview["rows"]) == 2, preview
    assert github.urls == [url_of(RED_LIGHT)]


def test_adding_a_left_out_dataset_to_a_dataflow_fetches_it_into_the_users_store(
    client, user_and_token, pip_catalog, monkeypatch
):
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    user, token = user_and_token
    github = FakeGitHub().serve(monkeypatch)
    project_id = create_project(client, token, name="Milan heat")

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        headers=_auth(token),
        data=json.dumps({"datasetId": "data.utk.milan-mrt"}),
    )

    assert resp.status_code in (200, 201), resp.get_data(as_text=True)
    stored = dataset_dir(str(user.id), "data.utk.milan-mrt@1") / "data" / "milan-mrt.tif"
    assert stored.read_bytes() == (REPO / MRT).read_bytes()
    assert github.urls == [url_of(MRT)]


def test_a_failed_download_fails_the_install_with_what_failed(client, user_and_token, pip_catalog, monkeypatch):
    from utk_curio.backend.app.datasets.infrastructure.storage import dataset_dir
    from utk_curio.backend.tests.test_datasets.computed_test_helpers import create_project

    user, token = user_and_token
    FakeGitHub(fail=OSError("Network is unreachable")).serve(monkeypatch)
    project_id = create_project(client, token, name="Milan heat")

    resp = client.post(
        f"/api/dataflows/{project_id}/datasets/install",
        headers=_auth(token),
        data=json.dumps({"datasetId": "data.utk.milan-mrt"}),
    )

    assert resp.status_code >= 400, resp.get_data(as_text=True)
    error = resp.get_json()["error"]
    for words in (MRT, url_of(MRT), "Network is unreachable", CLONE):
        assert words in error, error
    assert not (dataset_dir(str(user.id), "data.utk.milan-mrt@1") / "manifest.json").exists()


def test_a_node_reads_a_left_out_dataset_where_it_was_placed(client, user_and_token, pip_catalog, monkeypatch):
    _, token = user_and_token
    github = FakeGitHub().serve(monkeypatch)
    captured = _capture_sandbox(monkeypatch)

    resp = _run_code(client, token, '    return curio_load_data("data.utk.milan-mrt")\n')

    assert resp.status_code == 200, resp.get_data(as_text=True)
    path = Path(captured["body"]["dataset_paths"]["data.utk.milan-mrt"])
    assert path.read_bytes() == (REPO / MRT).read_bytes()
    assert path == _module().fetched_root(COMMIT) / MRT
    assert github.urls == [url_of(MRT)]


def test_a_failed_download_fails_the_node_with_what_failed_and_how_to_get_the_file(
    client, user_and_token, pip_catalog, monkeypatch
):
    """The node fails with the download's own error, not the sandbox's "not
    available", and the sandbox is not asked to run it."""
    _, token = user_and_token
    FakeGitHub(fail=OSError("Network is unreachable")).serve(monkeypatch)
    captured = _capture_sandbox(monkeypatch)

    resp = _run_code(client, token, '    return curio_load_data("data.utk.milan-mrt")\n')

    assert resp.status_code == 200, resp.get_data(as_text=True)
    reply = resp.get_json()
    assert not reply["output"].get("path"), reply
    for words in (MRT, url_of(MRT), "Network is unreachable", CLONE):
        assert words in reply["stderr"], reply["stderr"]
    assert "body" not in captured


def test_scouts_flood_rasters_are_downloaded_the_first_time_the_flood_dataflows_loaders_run(
    client, user_and_token, tmp_path, monkeypatch
):
    """SCOUT's seven flood rasters are in the repository and out of the pip
    package. On a pip install's catalog, the first run of each of the
    quad-cities-flood-vulnerability dataflow's Data Loading nodes downloads the rasters its code
    names, each once, and hands the sandbox the files where they were placed;
    a second run downloads nothing. The census tracts and the waterways it
    also reads ship in the package: their loaders get the package's own files,
    and nothing is downloaded for them."""
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import resolve_references

    assert set(FLOOD) <= set(listed()), sorted(set(FLOOD) - set(listed()))
    module = _module()
    _, token = user_and_token
    root = tmp_path / "site-packages"
    for repo_path in FLOOD:
        catalog_copy("/".join(repo_path.split("/")[:2]), root)
    spec = json.loads(FLOOD_DATAFLOW.read_text(encoding="utf-8"))["dataflow"]
    flood_ids = {repo_path.split("/")[1].rsplit("@", 1)[0] for repo_path in FLOOD}
    held = {}
    for ref in spec["datasets"]:
        if ref["datasetId"] in flood_ids:
            continue
        folder = catalog_copy(f"datasets/{ref['dirName']}", root)
        held[ref["datasetId"]] = folder / json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["dataFile"]
        assert held[ref["datasetId"]].is_file(), f"{ref['datasetId']} is left out of the package"
    assert sorted(held) == ["data.cdc.quad-cities-svi-tracts", "data.usgs.quad-cities-waterways"]
    monkeypatch.setenv("CURIO_CATALOG_ROOT", str(root / "datasets"))
    monkeypatch.setattr(module, "RECORD_PATH", write_record(tmp_path / "record.json", FLOOD))
    assert not any((root / repo_path).exists() for repo_path in FLOOD)
    github = FakeGitHub().serve(monkeypatch)
    captured = _capture_sandbox(monkeypatch)

    shared = [n["metadata"]["widgets"][0] for n in spec["nodes"] if n["type"] == "curio.builtin/parameter"]
    codes = []
    for loader in (n for n in spec["nodes"] if n["type"] == "curio.builtin/data-loading"):
        code, problems = resolve_references(loader["content"], [], "python", shared=shared)
        assert problems == [], problems
        codes.append(textwrap.indent(code, "    "))
    fetched, read_in_place = [], []
    for code in codes:
        resp = _run_code(client, token, code)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        paths = captured["body"]["dataset_paths"]
        assert sorted(paths) == sorted(dataset_ids_in_code(code)), paths
        for dataset_id, path in paths.items():
            if dataset_id in held:
                assert Path(path).resolve() == held[dataset_id].resolve()
                read_in_place.append(dataset_id)
                continue
            (repo_path,) = [p for p in FLOOD if p.startswith(f"datasets/{dataset_id}@1/")]
            assert Path(path) == module.fetched_root(COMMIT) / repo_path
            assert Path(path).read_bytes() == (REPO / repo_path).read_bytes()
            fetched.append(repo_path)
    assert sorted(fetched) == sorted(FLOOD)
    assert sorted(read_in_place) == sorted(held)
    assert sorted(github.urls) == sorted(url_of(repo_path) for repo_path in FLOOD)

    # Run again: every raster is where it was placed, and nothing is downloaded.
    for code in codes:
        resp = _run_code(client, token, code)
        assert resp.status_code == 200, resp.get_data(as_text=True)
    assert len(github.urls) == len(FLOOD)
