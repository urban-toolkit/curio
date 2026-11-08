"""Disk room for a CI job (``scripts/ci_disk.sh``).

``free`` prints the free disk of Docker's data root and of the job's
workspace. On a GitHub-hosted runner ``drop-tools`` removes the toolchains no
CI job uses, in the background, and ``wait-tools`` waits for that removal; on
any other runner both do nothing. The Pythons and Nodes setup-python and
setup-node pick from, and Google Chrome, which the e2e suite launches by its
path, always stay.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci_disk.sh"

DROPPED = [
    "usr/share/dotnet",
    "usr/local/lib/android",
    "opt/ghc",
    "usr/local/.ghcup",
    "usr/share/swift",
    "usr/lib/jvm",
    "usr/local/share/powershell",
    "opt/az",
    "opt/microsoft",
    "opt/hostedtoolcache/CodeQL",
    "opt/hostedtoolcache/go",
    "opt/hostedtoolcache/Ruby",
    "opt/hostedtoolcache/PyPy",
    "usr/local/julia1.12.1",
]
KEPT = [
    "opt/hostedtoolcache/Python/3.12.16",
    "opt/hostedtoolcache/node/26.1.0",
    "opt/google/chrome",
    "usr/bin",
    "usr/share/fonts",
]

FAKE_DOCKER = """#!/bin/sh
case "$1 $2" in
  "info --format") echo "$DOCKER_ROOT" ;;
esac
exit 0
"""


def _runner_root(tmp_path) -> Path:
    """A runner's folders under tmp_path, each holding a file."""
    root = tmp_path / "root"
    for folder in DROPPED + KEPT:
        (root / folder).mkdir(parents=True)
        (root / folder / "file").write_text("x")
    return root


def _run(tmp_path, *args, environment="github-hosted"):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    for folder in ("docker-root", "temp", "workspace"):
        (tmp_path / folder).mkdir(exist_ok=True)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "DOCKER_ROOT": str(tmp_path / "docker-root"), "RUNNER_ENVIRONMENT": environment,
           "RUNNER_TEMP": str(tmp_path / "temp"), "GITHUB_WORKSPACE": str(tmp_path / "workspace"),
           "CURIO_CI_DISK_ROOT": str(tmp_path / "root"), "CURIO_CI_DISK_SUDO": ""}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=120)


def test_free_says_how_much_room_docker_and_the_workspace_have(tmp_path):
    result = _run(tmp_path, "free", "before the pull", environment="self-hosted")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "Free disk before the pull:"
    assert lines[1].split() == ["Mounted", "on", "Size", "Used", "Avail", "Use%"]
    # Docker's root and the workspace are on one file system here: one line.
    assert len(lines) == 3


def test_a_github_hosted_runner_drops_the_unused_toolchains_and_keeps_the_rest(tmp_path):
    root = _runner_root(tmp_path)
    dropped = _run(tmp_path, "drop-tools")
    assert dropped.returncode == 0, dropped.stderr
    assert "Free disk before the unused toolchains go:" in dropped.stdout
    waited = _run(tmp_path, "wait-tools")
    assert waited.returncode == 0, waited.stderr
    assert "Free disk after the unused toolchains went:" in waited.stdout
    assert "still being removed" not in waited.stdout
    assert [folder for folder in DROPPED if (root / folder).exists()] == []
    assert [folder for folder in KEPT if not (root / folder / "file").exists()] == []
    assert not (tmp_path / "temp" / "curio-drop-tools.pid").exists()


@pytest.mark.parametrize("environment", ["self-hosted", ""])
def test_any_other_runner_keeps_every_toolchain(tmp_path, environment):
    root = _runner_root(tmp_path)
    dropped = _run(tmp_path, "drop-tools", environment=environment)
    waited = _run(tmp_path, "wait-tools", environment=environment)
    assert (dropped.returncode, dropped.stdout, waited.returncode, waited.stdout) == (0, "", 0, "")
    assert [folder for folder in DROPPED + KEPT if not (root / folder / "file").exists()] == []


def test_wait_tools_with_no_removal_started_returns_at_once(tmp_path):
    result = _run(tmp_path, "wait-tools")
    assert (result.returncode, result.stdout) == (0, "")
