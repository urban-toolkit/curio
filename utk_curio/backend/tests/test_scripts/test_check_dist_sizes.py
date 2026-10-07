"""``scripts/check_dist_sizes.py``: the release workflow's check, before the
upload step, that every file it built fits PyPI's limit for one file,
104,857,600 bytes (100 MiB).

The files are sparse, so a file of the limit's size costs no disk. The script
runs as the workflow runs it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "check_dist_sizes.py"
LIMIT = 104_857_600
WHEEL = "utk_curio-0.17.0-py3-none-any.whl"
SDIST = "utk_curio-0.17.0.tar.gz"


def _sized(path: Path, size: int) -> Path:
    with open(path, "wb") as handle:
        handle.truncate(size)
    return path


def _check(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), str(folder)], cwd=REPO, capture_output=True, text=True)


def test_a_file_over_the_limit_fails_the_check_and_every_size_is_printed(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    _sized(dist / WHEEL, 72_000_000)
    _sized(dist / SDIST, LIMIT + 1)

    run = _check(dist)

    assert run.returncode == 1, run.stdout + run.stderr
    out = run.stdout + run.stderr
    assert f"{WHEEL}: 72,000,000 bytes" in out, out
    assert f"{SDIST}: 104,857,601 bytes" in out, out
    over = [line for line in out.splitlines() if "over PyPI's limit" in line]
    assert len(over) == 1 and SDIST in over[0], out


def test_files_up_to_the_limit_pass(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    _sized(dist / WHEEL, LIMIT)
    _sized(dist / SDIST, 1024)

    run = _check(dist)

    assert run.returncode == 0, run.stdout + run.stderr
    assert f"{WHEEL}: 104,857,600 bytes" in run.stdout and f"{SDIST}: 1,024 bytes" in run.stdout
    assert "over PyPI's limit" not in run.stdout + run.stderr


def test_a_folder_with_nothing_built_fails(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()

    run = _check(dist)

    assert run.returncode == 1, run.stdout + run.stderr
