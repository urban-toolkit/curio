"""The pip package installs nothing in site-packages but ``utk_curio/`` and its
dist-info, and a pip install still finds everything Curio ships beside its code.

The repository keeps the Data Catalog's datasets, the Discovery Catalog's
sources, the Model Catalog's models, the Node Catalog's packages, the scripts
and DuckDB's extensions in folders beside ``utk_curio/``: ``datasets/``,
``discovery/``, ``models/``, ``packages/``, ``scripts/`` and ``vendor/``. A
wheel that installs those folders as they are puts a ``datasets/`` of Curio's
into site-packages, where Hugging Face's ``datasets`` package lives: the two
mix in one folder, uninstalling either can break the other, and without
Hugging Face's package ``import datasets`` finds Curio's data.

The release builds the sdist, then the wheel from the sdist
(``publish-pip-to-pypi.yml``). The tests run those two steps through
setuptools' build backend on a project made of Curio's build files, its code
(without the frontend and the test suites), every folder it ships beside the
code, and the record of the files the package leaves out, which
``scripts/record_left_out_files.py`` writes before the build. They unpack the
wheel as pip installs it, into a site-packages that already holds Hugging
Face's ``datasets`` (a stand-in), and ask the installed copy what it reads
(``_support/pip_install_probe.py``), started from an empty folder.

No test opens a socket, and the build downloads nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from utk_curio.backend.tests._support.left_out_files import COMMIT, listed
from utk_curio.backend.tests._support.pip_install_probe import MARKER

REPO = Path(__file__).resolve().parents[4]
PROBE = REPO / "utk_curio" / "backend" / "tests" / "_support" / "pip_install_probe.py"
#: The folders the repository keeps beside utk_curio/.
FOLDERS = ("datasets", "discovery", "models", "packages", "scripts", "vendor")
#: Curio's files the build reads. pyproject.toml also names README.md and
#: LICENSE, which the CI image does not hold; the project gets stand-ins.
BUILD_FILES = ("pyproject.toml", "setup.py", "MANIFEST.in", "package.json", "package-lock.json")
#: Where the release build writes the record of the files the package leaves out.
RECORD = PurePosixPath("utk_curio", "backend", "app", "datasets", "infrastructure", "left_out_files.record.json")
#: Hugging Face's datasets package, as a site-packages holds it before Curio is installed.
HUGGING_FACE = '"""A stand-in for Hugging Face\'s datasets package."""\n\nHUGGING_FACE = True\n'


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(folder: Path) -> dict[str, str]:
    """The sha256 of each file under *folder*, by its path there."""
    folder = Path(folder)
    if not folder.is_dir():
        return {}
    return {
        path.relative_to(folder).as_posix(): _sha256(path.read_bytes())
        for path in sorted(folder.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def _with_manifest(folder: str) -> list[str]:
    """The entries of the checkout's *folder* that hold a manifest.json."""
    return sorted(path.parent.name for path in (REPO / folder).glob("*/manifest.json"))


def _code_only(directory: str, names: list[str]) -> set[str]:
    """What the project leaves out of the checkout's ``utk_curio/``: the
    frontend and the test suites, which the probe never runs, compiled files,
    hidden folders such as a run's ``.curio``, and a record of a local release
    build (the project records its own)."""
    here = Path(directory)
    ignored = {
        name for name in names
        if name in ("__pycache__", "node_modules") or name.endswith(".pyc") or name.startswith(".")
    }
    if here == REPO / "utk_curio":
        ignored |= {"frontend"} & set(names)
    if here.parent == REPO / "utk_curio" and here.name in ("backend", "sandbox"):
        ignored |= {"tests"} & set(names)
    return ignored | ({RECORD.name} & set(names))


def _build(hook: str, project: Path, out: Path) -> Path:
    """Run setuptools' build backend *hook* (``build_sdist``, ``build_wheel``)
    in *project*, as ``python -m build --no-isolation`` does; the built file."""
    run = subprocess.run(
        [sys.executable, "-c", f"import setuptools.build_meta as backend; print(backend.{hook}({str(out)!r}))"],
        cwd=project, capture_output=True, text=True, timeout=600,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    return out / run.stdout.strip().splitlines()[-1]


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    """The sdist, and the wheel built from the unpacked sdist, of Curio's
    code and every folder it ships beside it, with the record of the files the
    package leaves out."""
    root = tmp_path_factory.mktemp("release")
    project = root / "project"
    project.mkdir()
    for name in BUILD_FILES:
        shutil.copy2(REPO / name, project / name)
    (project / "README.md").write_text("Curio\n", encoding="utf-8")
    (project / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    shutil.copytree(REPO / "utk_curio", project / "utk_curio", ignore=_code_only)
    for folder in FOLDERS:
        shutil.copytree(REPO / folder, project / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    recorded = subprocess.run(
        [sys.executable, str(project / "scripts" / "record_left_out_files.py"),
         "--commit", COMMIT, "--out", str(project / RECORD)],
        cwd=project, capture_output=True, text=True, timeout=300,
    )
    assert recorded.returncode == 0, recorded.stdout[-3000:] + recorded.stderr[-3000:]

    out = root / "dist"
    out.mkdir()
    sdist = _build("build_sdist", project, out)
    with tarfile.open(sdist) as archive:
        archive.extractall(root / "unpacked", filter="data")
    (unpacked,) = (root / "unpacked").iterdir()
    wheel = _build("build_wheel", unpacked, out)

    with tarfile.open(sdist) as archive:
        top = PurePosixPath(unpacked.name)
        in_sdist = {
            PurePosixPath(member.name).relative_to(top).as_posix(): _sha256(archive.extractfile(member).read())
            for member in archive.getmembers()
            if member.isfile()
        }
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        (top_level,) = [name for name in names if name.endswith(".dist-info/top_level.txt")]
        top_level_names = archive.read(top_level).decode("utf-8").split()
    return SimpleNamespace(wheel=wheel, sdist=in_sdist, wheel_names=names, top_level=top_level_names)


def _in_sdist(release, folder: str) -> dict[str, str]:
    """The sha256 of each file the sdist holds under *folder*, by its path there."""
    prefix = f"{folder}/"
    return {name[len(prefix):]: digest for name, digest in release.sdist.items() if name.startswith(prefix)}


@pytest.fixture(scope="module")
def pip_install(release, tmp_path_factory):
    """The wheel unpacked as pip installs it, into a site-packages that holds
    Hugging Face's datasets package, and what the installed copy reads when
    Curio starts from an empty folder (``_support/pip_install_probe.py``)."""
    root = tmp_path_factory.mktemp("pip-install")
    site = root / "site-packages"
    (site / "datasets").mkdir(parents=True)
    (site / "datasets" / "__init__.py").write_text(HUGGING_FACE, encoding="utf-8")
    with zipfile.ZipFile(release.wheel) as archive:
        archive.extractall(site)
    launch = root / "launch"
    launch.mkdir()
    home = root / "home"
    home.mkdir()
    # Nothing of this process's environment but PATH: no CURIO_* root, and no
    # PYTHONPATH that holds the checkout.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "PYTHONPATH": str(site),
        "PYTHONDONTWRITEBYTECODE": "1",
        "CURIO_LAUNCH_CWD": str(launch),
    }
    run = subprocess.run(
        [sys.executable, "-c", PROBE.read_text(encoding="utf-8")],
        cwd=launch, env=env, capture_output=True, text=True, timeout=600,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    (line,) = [line for line in run.stdout.splitlines() if line.startswith(MARKER)]
    report = json.loads(line[len(MARKER):])
    assert Path(report["utk_curio"]) == (site / "utk_curio").resolve(), (
        f"the probe ran Curio from {report['utk_curio']}, not from the pip install in {site}"
    )
    return SimpleNamespace(site=site, home=home, report=report)


def test_the_wheel_installs_nothing_but_utk_curio_and_its_dist_info(release):
    """pip unpacks the wheel into site-packages as it is, so each top-level
    entry of the wheel is a folder of site-packages: only ``utk_curio/`` and
    the wheel's ``.dist-info/`` may be, and ``top_level.txt`` names only
    ``utk_curio``."""
    top = sorted({PurePosixPath(name).parts[0] for name in release.wheel_names})
    dist_info = [name for name in top if name.endswith(".dist-info")]
    others = [name for name in top if name != "utk_curio" and name not in dist_info]
    assert len(dist_info) == 1 and not others, (
        f"a pip install puts {', '.join(name + '/' for name in others)} in site-packages beside "
        f"utk_curio/: datasets/ there is Hugging Face's datasets package, so the two mix in one "
        f"folder and pip uninstall of either can break the other"
    )
    assert release.top_level == ["utk_curio"], f"the wheel's top_level.txt names {release.top_level}"


def test_the_sdist_keeps_the_folders_where_the_repository_has_them(release):
    """Each folder Curio ships beside ``utk_curio/`` is in the sdist at its
    repository path, byte for byte, and neither archive holds a file the
    package leaves out."""
    for folder in FOLDERS:
        in_sdist = _in_sdist(release, folder)
        assert in_sdist, f"the sdist holds nothing at {folder}/"
        changed = sorted(rel for rel, digest in in_sdist.items() if digest != _sha256((REPO / folder / rel).read_bytes()))
        assert not changed, f"the sdist's {folder}/ differs from the repository's at {changed}"
    for repo_path in listed():
        assert repo_path not in release.sdist, f"the sdist holds {repo_path}, which the package leaves out"
        held = [name for name in release.wheel_names if name.endswith(f"/{repo_path}") or name == repo_path]
        assert not held, f"the wheel holds {held}, which the package leaves out"


def test_a_pip_install_leaves_hugging_faces_datasets_package_alone(pip_install):
    """Hugging Face's datasets package, installed before Curio, holds nothing
    of Curio's afterwards, and ``import datasets`` still finds it."""
    theirs = sorted(
        path.relative_to(pip_install.site).as_posix() for path in (pip_install.site / "datasets").rglob("*")
    )
    assert theirs == ["datasets/__init__.py"], (
        f"installing Curio put {len(theirs) - 1} entries of its own into Hugging Face's "
        f"datasets/ package in site-packages, such as {[name for name in theirs if name != 'datasets/__init__.py'][:3]}"
    )
    assert pip_install.report["import_datasets"] == str((pip_install.site / "datasets" / "__init__.py").resolve())


def test_a_pip_install_reads_every_shipped_folder_from_inside_utk_curio(pip_install):
    """Each reader of the folders Curio ships beside its code looks inside
    ``utk_curio/`` in site-packages, never in a folder of site-packages that
    another package may own."""
    package = (pip_install.site / "utk_curio").resolve()
    report = pip_install.report
    where = {
        "the Data Catalog (datasets/)": report["datasets"]["root"],
        "the Discovery Catalog (discovery/)": report["discovery"]["root"],
        "the Model Catalog (models/)": report["models"]["root"],
        "the Node Catalog (packages/)": report["packages"]["root"],
        "curio test (scripts/test.sh)": report["scripts"]["test_sh"],
        "DuckDB's extensions (vendor/duckdb-extensions/)": report["duckdb_extensions"]["root"],
        "the record of the files the package leaves out": report["record"]["path"],
    }
    outside = {what: path for what, path in where.items() if not Path(path).resolve().is_relative_to(package)}
    assert not outside, f"a pip install reads these outside {package}: {outside}"


def test_a_pip_install_lists_every_shipped_dataset_model_source_and_package(pip_install):
    """The Data Catalog, the Model Catalog, the Discovery Catalog and the Node
    Catalog of a pip install list every entry the repository ships."""
    report = pip_install.report
    assert sorted(item["dirName"] for item in report["datasets"]["items"]) == _with_manifest("datasets")
    assert report["models"]["listed"] == _with_manifest("models")
    assert report["discovery"]["listed"] == _with_manifest("discovery")
    assert report["packages"]["listed"] == _with_manifest("packages")


def test_a_pip_install_reads_each_file_the_sdist_ships_and_nothing_else(pip_install, release):
    """Byte for byte, the folder each reader looks in holds the files of that
    folder the sdist carries, which the wheel is built from, and nothing else."""
    report = pip_install.report
    read_from = {
        "datasets": report["datasets"]["root"],
        "discovery": report["discovery"]["root"],
        "models": report["models"]["root"],
        "packages": report["packages"]["root"],
        "scripts": str(Path(report["scripts"]["test_sh"]).parent),
        "vendor/duckdb-extensions": report["duckdb_extensions"]["root"],
    }
    for folder, root in read_from.items():
        found, shipped = _files(Path(root)), _in_sdist(release, folder)
        assert found == shipped, (
            f"{root}, where a pip install reads {folder}/, holds {sorted(set(found) - set(shipped))[:5]} "
            f"that the package does not ship there, and lacks {sorted(set(shipped) - set(found))[:5]}"
        )


def test_a_pip_install_gives_each_left_out_file_its_recorded_size(pip_install):
    """The record the release wrote names the commit and each left-out file's
    size, and the Data Catalog gives that size for a data file it has not
    downloaded yet."""
    record = pip_install.report["record"]
    assert record["commit"] == COMMIT
    assert record["sizes"] == {repo_path: (REPO / repo_path).stat().st_size for repo_path in listed()}
    items = {item["dirName"]: item for item in pip_install.report["datasets"]["items"]}
    for repo_path in listed():
        kind, folder, *_rest = repo_path.split("/")
        if kind == "datasets":
            assert items[folder]["path"] is None, items[folder]
            assert items[folder]["sizeBytes"] == (REPO / repo_path).stat().st_size, items[folder]


def test_a_pip_installs_launcher_and_agents_read_the_shipped_packages(pip_install):
    """The launcher pip-installs the built-in package's Python dependencies,
    the dataflow runner knows the shipped packages' code nodes, and the
    agents' prompt fields read the built-in manifest, as in a clone."""
    from utk_curio.backend.app.execution import workflow_spec
    from utk_curio.backend.app.packages.domain.versions import merge_python_deps
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    builtin = REPO / "packages" / "curio.builtin@1"
    merged, _conflicts = merge_python_deps([("curio.builtin@1", dict(load_package_manifest(builtin).python_deps))])
    report = pip_install.report
    assert report["launcher_dependencies"] == [merged]
    assert report["package_code_types"] == workflow_spec.package_code_types()
    assert report["builtin_manifest"] == json.loads((builtin / "manifest.json").read_text(encoding="utf-8"))


def test_a_pip_install_seeds_the_sandbox_with_the_duckdb_extensions_it_ships(pip_install):
    """The launcher copies every DuckDB extension Curio ships to where the
    sandbox's duckdb-wasm looks before it downloads one."""
    vendored = {
        rel: digest
        for rel, digest in _files(REPO / "vendor" / "duckdb-extensions").items()
        if rel.endswith(".duckdb_extension.wasm")
    }
    assert vendored, "no DuckDB extension in this checkout"
    seeded = _files(pip_install.home / ".duckdb" / "extensions" / "extensions.duckdb.org")
    assert seeded == vendored, f"seeded {sorted(seeded)}, the package ships {sorted(vendored)}"
