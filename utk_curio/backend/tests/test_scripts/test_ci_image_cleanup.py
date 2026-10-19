"""Removing the images CI jobs leave on a self-hosted runner's daemon.

``scripts/ci_image_cleanup.sh`` is stop-stack's cleanup. It removes the CI
stacks' image names (``curio-ci*-curio``) and the pulled images of other
commits. An arcade runner keeps the job's own name on its image for the
project's next job, and an arcade job that has no image of its own (it failed
or was cancelled before its pull or build) removes none of them; utk-gpu, whose
daemon the deployed stacks share, keeps no CI image. No other image is ever
named for removal.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci_image_cleanup.sh"

SHA = "584ee988783fdb22f4468d698b42e235d0b3fb72"
OTHER_SHA = "ce9f3781eb54be4b658b64c64413d5ca155f4f75"
CI_REPO = "ghcr.io/urban-toolkit/curio-ci"
STACK_NAMES = [
    "curio-ci-curio:latest",
    "curio-ci-iso-curio:latest",
    "curio-ci-exec-user-curio:latest",
    "curio-ci-stress-curio:latest",
]
#: Images no CI cleanup may touch: a deployed stack's, a release's, alpine.
OTHERS = ["curio-curio:latest", "ghcr.io/urban-toolkit/curio:0.16.447", "alpine:latest"]
IMAGES = STACK_NAMES + [f"{CI_REPO}:{SHA}", f"{CI_REPO}:{OTHER_SHA}"] + OTHERS

#: Stands in for docker: logs every call, and answers `image ls` from
#: FAKE_IMAGES, all of it or one repository's.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
case "$1 $2" in
  "system df") echo "TYPE TOTAL ACTIVE SIZE RECLAIMABLE" ;;
  "image ls")
    if [ "$3" = "--format" ]; then cat "$FAKE_IMAGES"; else grep "^$3:" "$FAKE_IMAGES" || true; fi ;;
esac
exit 0
"""


def _cleanup(tmp_path, runner, project="curio-ci", own_image=True, repository="urban-toolkit/curio"):
    """Run the cleanup; return its result, the docker calls and the names it removed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    listing = tmp_path / "images.txt"
    listing.write_text("\n".join(IMAGES) + "\n")
    log = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "DOCKER_LOG": str(log),
           "FAKE_IMAGES": str(listing), "RUNNER_NAME": runner, "GITHUB_REPOSITORY": repository,
           "GITHUB_SHA": SHA}
    env.pop("CURIO_CI_OWN_IMAGE", None)
    if own_image:
        env["CURIO_CI_OWN_IMAGE"] = "1"
    result = subprocess.run(["bash", str(SCRIPT), project], env=env, capture_output=True, text=True, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    removed = sorted(name for call in calls if call.startswith("image rm ") for name in call.split()[2:])
    return result, calls, removed


@pytest.mark.parametrize("runner,project", [
    ("arcade-cpu-07", "curio-ci"),
    ("arcade-cpu-12", "curio-ci-iso"),
    ("arcade-gpu-03", "curio-ci"),
])
def test_an_arcade_runner_keeps_the_jobs_own_image(tmp_path, runner, project):
    result, calls, removed = _cleanup(tmp_path, runner, project)
    assert result.returncode == 0, result.stderr
    own = f"{project}-curio:latest"
    assert removed == sorted([name for name in STACK_NAMES if name != own] + [f"{CI_REPO}:{OTHER_SHA}"])
    assert not any(arg in ("-f", "--force") for call in calls if call.startswith("image rm ")
                   for arg in call.split()[2:])


@pytest.mark.parametrize("own_image", [True, False])
def test_utk_gpu_keeps_no_ci_image(tmp_path, own_image):
    result, _, removed = _cleanup(tmp_path, "utk-gpu", "curio-ci", own_image=own_image)
    assert result.returncode == 0, result.stderr
    assert removed == sorted(STACK_NAMES + [f"{CI_REPO}:{OTHER_SHA}"])


def test_an_arcade_job_without_an_image_of_its_own_removes_none(tmp_path):
    result, calls, removed = _cleanup(tmp_path, "arcade-cpu-07", "curio-ci", own_image=False)
    assert result.returncode == 0, result.stderr
    assert removed == []
    assert "no image of its own" in result.stdout
    assert "image prune -f" in calls
    assert "builder prune -af --filter until=24h" in calls


def test_the_ci_repository_is_found_from_a_mixed_case_name(tmp_path):
    _, _, removed = _cleanup(tmp_path, "arcade-cpu-07", repository="Urban-Toolkit/curio")
    assert f"{CI_REPO}:{OTHER_SHA}" in removed
    assert f"{CI_REPO}:{SHA}" not in removed


def test_the_disk_use_before_and_after_goes_to_the_log(tmp_path):
    result, calls, _ = _cleanup(tmp_path, "arcade-cpu-07")
    assert result.stdout.index("Docker disk use before the cleanup:") < result.stdout.index(
        "Docker disk use after the cleanup:")
    assert calls.count("system df") == 2
