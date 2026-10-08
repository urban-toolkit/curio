"""The files the pip package leaves out, and a pip install fetching them.

PyPI takes no file over 100 MiB, and the wheel and the sdist were over it. The
repository keeps every catalog file; the pip package leaves out the big ones
named in one list (``datasets/infrastructure/left_out_files.json``), and a
pip install downloads each from GitHub the first time Curio needs it: from
the commit its package was built from, checked against the size and sha256
the release build recorded, through the egress policy, into Curio's state
directory.

- The packaging: ``MANIFEST.in``, applied as setuptools applies it, leaves out
  exactly the listed files and the frontend's source maps; the release
  script records each listed file.
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
import json
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.left_out_files import (
    COMMIT,
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
#: What a test's GitHub serves for SIDEWALK: small, so the fetch tests are quick.
PAYLOAD = b"PAR1" + bytes(range(256)) * 64 + b"PAR1"
CLONE = "https://github.com/urban-toolkit/curio"

#: A built frontend: its bundles, and the source maps beside them.
DIST = "utk_curio/frontend/urban-workflows/dist"
BUILT = [f"{DIST}/index.html", f"{DIST}/main.js", f"{DIST}/main.js.map", f"{DIST}/vendors.js", f"{DIST}/vendors.js.map"]
INFRASTRUCTURE = "utk_curio/backend/app/datasets/infrastructure"


def _module():
    from utk_curio.backend.app.datasets.infrastructure import left_out_files

    return left_out_files


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
    Catalog dataset or the entry of a Model Catalog model: the one big file of
    its folder, whose small files (manifest, sidecars) still ship."""
    files = listed()
    assert files and len(files) == len(set(files)), files
    for repo_path in files:
        assert (REPO / repo_path).is_file(), repo_path
        kind, folder, *rest = repo_path.split("/")
        assert kind in ("datasets", "models") and rest, repo_path
        manifest = json.loads((REPO / kind / folder / "manifest.json").read_text(encoding="utf-8"))
        named = manifest.get("dataFile") if kind == "datasets" else manifest.get("entry")
        assert "/".join(rest) == named, (repo_path, named)


def test_manifest_in_leaves_out_exactly_the_listed_files_and_the_frontends_source_maps(monkeypatch):
    """``MANIFEST.in`` builds the sdist, and the release builds the wheel from
    the sdist (``publish-pip-to-pypi.yml``). Its rules, applied as setuptools
    applies them, every line in order, to every file under ``datasets/``,
    ``models/`` and ``packages/``, the list and its record, the repository's
    ``package.json`` and ``package-lock.json`` (``setup.py`` copies them into
    the wheel), and a built frontend: the listed files and the frontend's
    source maps stay out, and
    nothing else does. A package's own source map ships: ``curio.example-ui@1``
    names it in its ``integrity.json``."""
    from setuptools._distutils.filelist import FileList

    monkeypatch.chdir(REPO)
    repository = sorted(
        path.relative_to(REPO).as_posix()
        for folder in ("datasets", "models", "packages")
        for path in (REPO / folder).rglob("*")
        if path.is_file()
    )
    shipped_beside_the_code = [f"{INFRASTRUCTURE}/left_out_files.json", f"{INFRASTRUCTURE}/left_out_files.record.json"]
    node_packages = ["package.json", "package-lock.json"]
    everything = set(repository) | set(BUILT) | set(shipped_beside_the_code) | set(node_packages)
    files = FileList()
    files.set_allfiles(sorted(everything))
    for line in (REPO / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            files.process_template_line(line)
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
    ours = fetched / COMMIT / "models" / "model.scout.deep-umbra@1" / "manifest.json"
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
