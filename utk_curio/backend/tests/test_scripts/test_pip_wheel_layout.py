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

Curio also reads part of ``docs/``: the dataflows it ships, which every
account is seeded with and agents' runs are shown; the example data their
nodes read by its path in ``docs/examples/data/``, through ``/file/`` or from
node code; the folder of the Discovery Catalog's Example storage source; the
agent evaluation's prompt fixtures and their schema; and the Trill schema the
agents' prompt fields project. A pip install needs those files and none of the
guides, images, walkthroughs or screenshot baselines.

The release builds the sdist, then the wheel from the sdist
(``publish-pip-to-pypi.yml``). The tests run those two steps through
setuptools' build backend on a project made of Curio's build files, its code
(without the frontend and the test suites), every folder it ships beside the
code, ``docs/``, and the record of the files the package leaves out, which
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
from utk_curio.backend.tests._support.pip_install_probe import (
    MARKER,
    example_data_paths,
    python_nodes_reading_example_data,
)

REPO = Path(__file__).resolve().parents[4]
PROBE = REPO / "utk_curio" / "backend" / "tests" / "_support" / "pip_install_probe.py"
#: The folders the repository keeps beside utk_curio/, and docs/, part of
#: which the package ships.
FOLDERS = ("datasets", "discovery", "docs", "models", "packages", "scripts", "vendor")
#: Where the wheel carries them, under the folder that holds utk_curio/.
IN_THE_WHEEL = PurePosixPath("utk_curio", "_shipped")
#: The credits of the Example storage's Mapillary photos, whose license
#: (CC BY-SA 4.0) asks that they travel with the photos.
PHOTO_CREDITS = PurePosixPath("docs", "examples", "data", "mapillary-ATTRIBUTION.md")
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


def _spelled_example_data() -> list[str]:
    """Each path in ``docs/examples/data/`` a node of a dataflow Curio ships
    spells, as its code or its ``pbfFileUrl`` spells it."""
    from utk_curio.backend.app.projects.shipped import shipped_dataflows

    spelled = set()
    for dataflow in shipped_dataflows():
        spec = json.loads(Path(dataflow.path).read_text(encoding="utf-8"))
        for node in spec["dataflow"]["nodes"]:
            spelled |= example_data_paths(node.get("content"))
    return sorted(spelled)


def _example_data() -> list[str]:
    """The files of ``docs/examples/data/`` the dataflows Curio ships read, by
    repository path: each one a node spells, and the files of each folder."""
    files = set()
    for repo_path in _spelled_example_data():
        path = REPO / repo_path
        files |= {path} if path.is_file() else {inner for inner in path.rglob("*") if inner.is_file()}
    return sorted(path.relative_to(REPO).as_posix() for path in files)


def _shipped_folder_sources() -> dict[str, str]:
    """The checkout's Discovery sources that are folders, by directory name,
    each with its folder's repository path."""
    sources = {}
    for manifest in sorted((REPO / "discovery").glob("*/manifest.json")):
        provider = json.loads(manifest.read_text(encoding="utf-8")).get("provider") or {}
        if provider.get("type") == "folder":
            sources[manifest.parent.name] = provider["root"]
    return sources


def _read(pip_install, reader: str):
    """What the probe's *reader* of ``docs/`` found; fails with the error it
    raised instead."""
    found = pip_install.report[reader]
    failed = isinstance(found, dict) and set(found) == {"error"}
    assert not failed, f"in a pip install, {reader} failed: {found['error'] if failed else ''}"
    return found


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
    code, every folder it ships beside it and ``docs/``, with the record of
    the files the package leaves out."""
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
    Curio starts from an empty folder (``_support/pip_install_probe.py``),
    which asks ``/file/`` for the example data the shipped dataflows read."""
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
        [sys.executable, "-c", PROBE.read_text(encoding="utf-8"), json.dumps(_example_data())],
        cwd=launch, env=env, capture_output=True, text=True, timeout=600,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]
    (line,) = [line for line in run.stdout.splitlines() if line.startswith(MARKER)]
    report = json.loads(line[len(MARKER):])
    assert Path(report["utk_curio"]) == (site / "utk_curio").resolve(), (
        f"the probe ran Curio from {report['utk_curio']}, not from the pip install in {site}"
    )
    return SimpleNamespace(site=site, home=home, launch=launch, report=report)


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
    """Each folder Curio ships beside ``utk_curio/``, and what it ships of
    ``docs/``, is in the sdist at its repository path, byte for byte, and
    neither archive holds a file the package leaves out."""
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
    """Each reader of the folders Curio ships beside its code, and of the
    parts of ``docs/`` it reads, looks inside ``utk_curio/`` in site-packages,
    never in a folder of site-packages that another package may own."""
    package = (pip_install.site / "utk_curio").resolve()
    report = pip_install.report
    fixtures = _read(pip_install, "prompt_fixtures")
    where = {
        "the Data Catalog (datasets/)": report["datasets"]["root"],
        "the Discovery Catalog (discovery/)": report["discovery"]["root"],
        "the Model Catalog (models/)": report["models"]["root"],
        "the Node Catalog (packages/)": report["packages"]["root"],
        "curio test (scripts/test.sh)": report["scripts"]["test_sh"],
        "DuckDB's extensions (vendor/duckdb-extensions/)": report["duckdb_extensions"]["root"],
        "the record of the files the package leaves out": report["record"]["path"],
        "the dataflows Curio ships (docs/examples/)": _read(pip_install, "dataflows")["root"],
        "the prompt fixtures (docs/examples/prompts/)": fixtures["root"],
        "the prompt fixtures' schema (docs/schemas/)": fixtures["schema"],
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
        "docs/examples": _read(pip_install, "dataflows")["root"],
        "docs/schemas": str(Path(_read(pip_install, "prompt_fixtures")["schema"]).parent),
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


def test_a_pip_install_seeds_and_lists_every_dataflow_curio_ships(pip_install):
    """``--with-examples`` seeds a pip install's accounts with the dataflows a
    clone ships (``projects/shipped.py``): the use case, the examples and the
    tests the projects page lists. The packages and datasets they declare,
    which the launcher and the seeders provision, are a clone's too."""
    from utk_curio.backend.app.datasets.seed import example_dep_dataset_dirs
    from utk_curio.backend.app.packages.service import example_dep_package_ids
    from utk_curio.backend.app.projects.shipped import shipped_dataflows

    keys = [dataflow.key for dataflow in shipped_dataflows()]
    assert keys, "no shipped dataflow in this checkout"
    found = _read(pip_install, "dataflows")
    assert found["keys"] == keys, (
        f"a pip install seeds {len(found['keys'])} of the {len(keys)} dataflows Curio ships, "
        f"reading them from {found['root']}"
    )
    assert found["packages"] == list(example_dep_package_ids())
    assert found["datasets"] == list(example_dep_dataset_dirs())


def test_a_pip_installs_agents_are_shown_the_worked_examples_a_clone_shows(pip_install):
    """An agent's run in a pip install is shown the shipped dataflows that
    ``llm-prompts/examples.md`` lists under "Used" (``turns/examples.py``), as
    in a clone: the index's links lead to the dataflows the package ships."""
    from utk_curio.backend.app.agents.application.turns import examples

    keys = [example.key for example in examples.used_examples()]
    assert keys, "no worked example in this checkout"
    found = _read(pip_install, "worked_examples")
    assert found == keys, f"a pip install's runs are shown {len(found)} of the {len(keys)} worked examples"


def test_a_pip_installs_prompt_fields_read_the_trill_schema(pip_install):
    """The agents' prompt fields (``contracts.py``) of a pip install read the
    Trill schema, and render from its template the shared preamble the
    package ships."""
    from utk_curio.backend.app.agents.domain import contracts

    trill = json.loads((REPO / contracts.TRILL_SCHEMA).read_text(encoding="utf-8"))
    assert _read(pip_install, "trill_schema") == trill
    preamble = (REPO / contracts.PROMPTS_DIR / "default_preamble.md").read_text(encoding="utf-8")
    assert _read(pip_install, "default_preamble") == preamble


def test_a_pip_install_validates_every_prompt_fixture_against_its_schema(pip_install):
    """The agent evaluation of a pip install (``tools/agent_eval.py``) loads
    every prompt fixture, each validated against its schema, finds the
    example each was written for, covers the examples a clone covers, and
    refuses a fixture its schema does not allow."""
    from utk_curio.backend.app.agents.evaluation import fixtures

    loaded = fixtures.load_fixtures()
    ids = [fixture.fixture_id for fixture in loaded]
    assert ids, "no prompt fixture in this checkout"
    found = _read(pip_install, "prompt_fixtures")
    assert found["fixtures"] == ids, f"a pip install loads {len(found['fixtures'])} of the {len(ids)} prompt fixtures"
    assert found["digests_match"] == [fixture.fixture_id for fixture in loaded if fixtures.digest_matches(fixture)]
    assert found["examples"] == [path.relative_to(fixtures.EXAMPLES_ROOT).as_posix() for path in fixtures.example_paths()]
    assert found["an_empty_fixture"] == "FixtureError", (
        f"validating an empty fixture in a pip install raised {found['an_empty_fixture']}, "
        f"not the FixtureError its schema gives"
    )


def test_a_pip_install_finds_the_folder_of_every_shipped_folder_source(pip_install, release):
    """Each Discovery source Curio ships as a folder (the Example storage,
    whose collections examples 10 and 18 to 23 read) finds its folder inside
    ``utk_curio/`` in site-packages, holding the files the sdist ships there."""
    package = (pip_install.site / "utk_curio").resolve()
    sources = _shipped_folder_sources()
    assert sources, "no folder source in this checkout's discovery/"
    found = _read(pip_install, "folder_sources")
    assert sorted(found) == sorted(sources)
    for name, repo_path in sources.items():
        root = found[name]
        assert not isinstance(root, dict), f"a pip install cannot find the folder of {name}: {root['error']}"
        assert Path(root).resolve().is_relative_to(package), f"a pip install reads {name}'s folder at {root}, outside {package}"
        files, shipped = _files(Path(root)), _in_sdist(release, repo_path)
        assert shipped and files == shipped, (
            f"{root} holds {sorted(set(files) - set(shipped))[:5]} that the package does not ship at "
            f"{repo_path}, and lacks {sorted(set(shipped) - set(files))[:5]}"
        )


def test_the_wheel_carries_of_docs_only_what_curio_reads(release):
    """Of ``docs/``, the wheel carries the files Curio reads and nothing else:
    the dataflows it ships and the example data their nodes read by its path
    in ``docs/examples/data/``, the prompt fixtures and their schema, the
    Trill schema, and each folder source's folder, with the credits of its
    photos. No guide, image, walkthrough or screenshot baseline. A shipped
    dataflow that reads a file the package does not carry fails here."""
    from utk_curio.backend.app.agents.domain import contracts
    from utk_curio.backend.app.agents.evaluation import fixtures
    from utk_curio.backend.app.projects.shipped import shipped_dataflows

    spelled = _spelled_example_data()
    assert spelled, "no shipped dataflow reads example data in this checkout"
    missing = [repo_path for repo_path in spelled if not (REPO / repo_path).exists()]
    assert not missing, f"shipped dataflows read {missing}, which this checkout does not hold"
    read = {dataflow.path for dataflow in shipped_dataflows()}
    read |= {REPO / repo_path for repo_path in _example_data()}
    read |= {*fixtures.fixture_paths(), fixtures.FIXTURE_SCHEMA_PATH, REPO / contracts.TRILL_SCHEMA, REPO / PHOTO_CREDITS}
    for repo_path in _shipped_folder_sources().values():
        read |= {path for path in (REPO / repo_path).rglob("*") if path.is_file()}
    expected = sorted(path.resolve().relative_to(REPO).as_posix() for path in read)
    prefix = f"{IN_THE_WHEEL}/"
    carried = sorted(name[len(prefix):] for name in release.wheel_names if name.startswith(f"{prefix}docs/"))
    assert carried == expected, (
        f"of docs/, the wheel carries {sorted(set(carried) - set(expected))[:5]}, which Curio does not read, "
        f"and lacks {sorted(set(expected) - set(carried))[:5]} of the {len(expected)} files it reads"
    )


def test_a_pip_install_serves_the_example_data_its_dataflows_read(pip_install):
    """``/file/`` serves each file of ``docs/examples/data/`` the shipped
    dataflows read, byte for byte, with Curio started from an empty folder:
    the Autark examples (06, 07, 08, 11 and their tests) fetch their
    OpenStreetMap extracts through it."""
    expected = {repo_path: _sha256((REPO / repo_path).read_bytes()) for repo_path in _example_data()}
    assert expected, "no shipped dataflow reads example data in this checkout"
    served = _read(pip_install, "file_route")
    wrong = {repo_path: answer for repo_path, answer in served.items() if answer != expected.get(repo_path)}
    assert sorted(served) == sorted(expected) and not wrong, (
        f"in a pip install started from an empty folder, /file/ answers {wrong} for example data "
        f"the shipped dataflows read"
    )


def test_a_pip_installs_nodes_read_the_example_data_by_the_path_they_spell(pip_install):
    """Run in-process from an empty folder, as a launch runs every node unless
    it isolates them, each Python node of a shipped dataflow that opens
    example data by its path reads it: example 08's raster, and the access
    scores and images of the test dataflows. The folder gets no ``docs/``."""
    expected = [node["key"] for node in python_nodes_reading_example_data()]
    assert "08-autark-spatial-join-regression/niteroi-raster" in expected, expected
    runs = _read(pip_install, "in_process_runs")
    assert sorted(runs) == sorted(expected)
    failed = {key: run["stderr"][-600:] for key, run in runs.items() if run["stderr"]}
    assert not failed, f"in a pip install started from an empty folder, these nodes fail: {failed}"
    assert not (pip_install.launch / "docs").exists(), "a run wrote docs/ into the folder Curio started from"


def test_a_pip_installs_isolated_runs_read_the_example_data_through_their_work_directory(pip_install):
    """An isolated run's work directory holds a ``docs/`` that leads to the
    one the pip install ships, so each node that opens example data by its
    path reads it there, as the forked child runs it."""
    package = (pip_install.site / "utk_curio").resolve()
    found = _read(pip_install, "isolated_runs")
    assert Path(found["docs"]).resolve().is_relative_to(package), (
        f"an isolated run's work directory reads docs/ at {found['docs']}, not inside {package}"
    )
    assert sorted(found["runs"]) == sorted(node["key"] for node in python_nodes_reading_example_data())
    failed = {key: run["stderr"][-600:] for key, run in found["runs"].items() if not run["ok"]}
    assert not failed, f"in a pip install, these nodes fail in an isolated run's work directory: {failed}"


def test_a_pip_installs_agent_evaluation_writes_its_reports_in_the_launch_folder(pip_install):
    """``agent_eval run`` without ``--out`` writes its reports in ``eval/`` of
    Curio's state directory, ``.curio/`` in the folder it starts from, never
    in site-packages."""
    out = Path(_read(pip_install, "agent_eval_out")).resolve()
    assert not out.is_relative_to(pip_install.site.resolve()), f"agent_eval run writes its reports in site-packages, at {out}"
    assert out == (pip_install.launch / ".curio" / "eval").resolve()
