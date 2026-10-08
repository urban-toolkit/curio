"""The pip package carries DuckDB's extensions, and a pip install reads them there.

Curio serves DuckDB's wasm extensions itself (``vendor/duckdb-extensions/``,
#318): the launcher seeds the sandbox's duckdb-wasm with them, and the backend
hands them to the browser's duckdb worker through
``/file/vendor/duckdb-extensions/``. Where they are missing, both download them
from extensions.duckdb.org.

The release builds the sdist, then the wheel from the sdist
(``publish-pip-to-pypi.yml``). The tests run those two steps through
setuptools' build backend on a small project: Curio's build files,
``utk_curio/__init__.py`` and the vendored extensions. They unpack the wheel as
pip installs it, into a site-packages that then holds ``utk_curio/``, and start
Curio from an empty folder of the user's.

No test opens a socket, and the build downloads nothing.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[4]
VENDORED = REPO / "vendor" / "duckdb-extensions"
#: Where the wheel carries them, under the folder that holds ``utk_curio/``.
IN_THE_PACKAGE = PurePosixPath("vendor", "duckdb-extensions")
#: Curio's files the build reads. pyproject.toml also names README.md and
#: LICENSE, which the CI image does not hold; the project gets stand-ins.
BUILD_FILES = ("pyproject.toml", "setup.py", "MANIFEST.in", "package.json", "package-lock.json")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _vendored() -> dict[str, str]:
    """The sha256 of each extension Curio serves, by its path under
    ``vendor/duckdb-extensions/``."""
    found = {
        path.relative_to(VENDORED).as_posix(): _sha256(path.read_bytes())
        for path in sorted(VENDORED.rglob("*.duckdb_extension.wasm"))
    }
    assert found, f"no DuckDB extension in {VENDORED}"
    return found


def _under(files: dict[str, bytes], folder: PurePosixPath) -> dict[str, str]:
    """The sha256 of each of *files* (by archive path) under *folder*, by its path there."""
    return {
        PurePosixPath(name).relative_to(folder).as_posix(): _sha256(data)
        for name, data in files.items()
        if PurePosixPath(name).is_relative_to(folder)
    }


def _on_disk(folder: Path) -> dict[str, str]:
    """The sha256 of each file under *folder*, by its path there."""
    if not folder.is_dir():
        return {}
    return {
        path.relative_to(folder).as_posix(): _sha256(path.read_bytes())
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


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
    """The sdist, and the wheel built from the unpacked sdist."""
    root = tmp_path_factory.mktemp("release")
    project = root / "project"
    (project / "utk_curio").mkdir(parents=True)
    for name in BUILD_FILES:
        shutil.copy2(REPO / name, project / name)
    (project / "README.md").write_text("Curio\n", encoding="utf-8")
    (project / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    shutil.copy2(REPO / "utk_curio" / "__init__.py", project / "utk_curio" / "__init__.py")
    shutil.copytree(VENDORED, project / IN_THE_PACKAGE)

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
            PurePosixPath(member.name).relative_to(top).as_posix(): archive.extractfile(member).read()
            for member in archive.getmembers()
            if member.isfile()
        }
    with zipfile.ZipFile(wheel) as archive:
        in_wheel = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    return SimpleNamespace(wheel=wheel, sdist_files=in_sdist, wheel_files=in_wheel)


@pytest.fixture
def pip_install(release, tmp_path, monkeypatch):
    """The wheel unpacked into site-packages, the folder that holds
    ``utk_curio/`` (``node_runtime.REPO_ROOT``), and Curio started from an
    empty folder."""
    from utk_curio.sandbox.util import node_runtime

    site = tmp_path / "site-packages"
    with zipfile.ZipFile(release.wheel) as archive:
        archive.extractall(site)
    launch = tmp_path / "launch"
    launch.mkdir()
    monkeypatch.setattr(node_runtime, "REPO_ROOT", site)
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(launch))
    return SimpleNamespace(site=site, launch=launch)


def test_the_sdist_and_the_wheel_carry_every_vendored_extension(release):
    """Every extension Curio serves, byte for byte, in the sdist and in the
    wheel, both at ``vendor/duckdb-extensions/``."""
    vendored = _vendored()
    in_sdist = _under(release.sdist_files, IN_THE_PACKAGE)
    in_wheel = _under(release.wheel_files, IN_THE_PACKAGE)
    assert in_sdist == vendored, (
        f"the sdist carries {sorted(in_sdist)} of the DuckDB extensions Curio serves, "
        f"{sorted(vendored)}, and the release builds the wheel from the sdist"
    )
    assert in_wheel == vendored, (
        f"the wheel carries {sorted(in_wheel)} at {IN_THE_PACKAGE}/ of the DuckDB extensions "
        f"Curio serves, {sorted(vendored)}"
    )


def test_a_pip_install_serves_the_browser_the_extensions_its_wheel_carries(app, pip_install):
    """The browser's duckdb worker asks the backend for each extension, and a
    pip install's backend answers with the copy in site-packages, though the
    folder Curio was started from holds none."""
    vendored = _vendored()
    client = app.test_client()
    for name, sha256 in vendored.items():
        url = f"/file/{IN_THE_PACKAGE}/{name}"
        resp = client.get(url, buffered=True)
        assert resp.status_code == 200, (
            f"{url} answered {resp.status_code} on a pip install, so the browser's duckdb worker "
            f"fetches {name} from extensions.duckdb.org"
        )
        assert _sha256(resp.data) == sha256, url


def test_a_pip_install_seeds_the_sandbox_with_the_extensions_its_wheel_carries(pip_install, tmp_path, monkeypatch):
    """The launcher copies each extension from site-packages to where the
    sandbox's duckdb-wasm looks before it downloads one."""
    from utk_curio.cli import dependencies

    vendored = _vendored()
    shipped = _on_disk(pip_install.site / IN_THE_PACKAGE)
    assert shipped == vendored, (
        f"a pip install's site-packages holds {sorted(shipped)} at {IN_THE_PACKAGE}/ of the DuckDB "
        f"extensions Curio serves, {sorted(vendored)}, so the sandbox's duckdb-wasm downloads "
        f"the rest from extensions.duckdb.org"
    )
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)

    dependencies.seed_duckdb_extensions()

    seeded = _on_disk(home / ".duckdb" / "extensions" / "extensions.duckdb.org")
    assert seeded == vendored, f"seeded {sorted(seeded)}, the package carries {sorted(vendored)}"
