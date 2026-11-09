"""Removing the images CI jobs leave on a self-hosted runner's daemon.

``scripts/ci_image_cleanup.sh`` is stop-stack's cleanup, and build-image's
after a filtered run's collection. No CI image outlives its job, on any runner
and whatever the job did: the CI stacks' image names (``curio-ci*-curio``) and
every pulled CI image go, this commit's too. No other image is ever named for
removal, and none with -f, so an image a container uses stays. An arcade CPU
runner, whose daemon only CI uses, also loses all its build cache; elsewhere,
an arcade GPU runner among them, what no build used for a day goes, then all
but the 30 GB most recently used, so test-gpu's next build there reuses its
layers and the cache stops growing.
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
THIRD_SHA = "70df0d309e1f9c3c5a6b2b9e2fe2a1c0d8f2a6b1"
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

#: Stands in for docker: logs every call, answers `image ls` from FAKE_IMAGES,
#: all of it or one repository's, and `image rm` takes the names out of it, so
#: what is left after the cleanup is what the daemon would still hold. A call
#: holding a word of FAKE_REFUSE fails, as an unknown flag does.
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
for word in $FAKE_REFUSE; do
  case " $* " in *" $word "*) exit 1 ;; esac
done
case "$1 $2" in
  "system df") echo "TYPE TOTAL ACTIVE SIZE RECLAIMABLE" ;;
  "info --format") echo "$DOCKER_ROOT" ;;
  "image ls")
    if [ "$3" = "--format" ]; then cat "$FAKE_IMAGES"; else grep "^$3:" "$FAKE_IMAGES" || true; fi ;;
  "image rm")
    shift 2
    for name in "$@"; do
      grep -vxF -- "$name" "$FAKE_IMAGES" > "$FAKE_IMAGES.left" || true
      mv "$FAKE_IMAGES.left" "$FAKE_IMAGES"
    done ;;
esac
exit 0
"""


def _cleanup(tmp_path, runner, images=IMAGES, repository="urban-toolkit/curio", refuse=""):
    """Run the cleanup; return its result, the docker calls, the names it
    removed and the images left on the fake daemon. ``refuse`` lists the
    flags the fake docker does not know."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    listing = tmp_path / "images.txt"
    listing.write_text("\n".join(images) + "\n")
    docker_root = tmp_path / "docker-root"
    docker_root.mkdir()
    log = tmp_path / "docker.log"
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "DOCKER_LOG": str(log),
           "FAKE_IMAGES": str(listing), "DOCKER_ROOT": str(docker_root), "RUNNER_NAME": runner,
           "GITHUB_REPOSITORY": repository, "GITHUB_SHA": SHA, "GITHUB_WORKSPACE": str(tmp_path),
           "FAKE_REFUSE": refuse}
    # The variable that once told an arcade job whether it had an image of
    # its own; no job sets it any more, and the cleanup must not need it.
    env.pop("CURIO_CI_OWN_IMAGE", None)
    result = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    calls = log.read_text().splitlines() if log.exists() else []
    removed = sorted(name for call in calls if call.startswith("image rm ") for name in call.split()[2:])
    left = [line for line in listing.read_text().splitlines() if line]
    return result, calls, removed, left


@pytest.mark.parametrize("runner", ["arcade-cpu-07", "arcade-gpu-03", "utk-gpu", "utk-desktop-01"])
def test_no_ci_image_survives_a_job(tmp_path, runner):
    result, calls, removed, left = _cleanup(tmp_path, runner)
    assert result.returncode == 0, result.stderr
    assert left == OTHERS
    assert removed == sorted(STACK_NAMES + [f"{CI_REPO}:{SHA}", f"{CI_REPO}:{OTHER_SHA}"])
    assert not any(arg in ("-f", "--force") for call in calls if call.startswith("image rm ")
                   for arg in call.split()[2:])
    assert "image prune -f" in calls


def test_a_job_cancelled_before_its_pull_removes_the_images_earlier_jobs_left(tmp_path):
    # 11-08: jobs cancelled mid-pull kept two images each, 34 GB, and the next
    # job's pull of a third filled arcade's disk.
    earlier = ["curio-ci-curio:latest", f"{CI_REPO}:{OTHER_SHA}", f"{CI_REPO}:{THIRD_SHA}"]
    result, _, removed, left = _cleanup(tmp_path, "arcade-cpu-05", images=earlier + OTHERS)
    assert result.returncode == 0, result.stderr
    assert removed == sorted(earlier)
    assert left == OTHERS


KEPT_CACHE = ["builder prune -af --filter until=24h", "builder prune -af --reserved-space 30GB"]


@pytest.mark.parametrize("runner,prunes", [
    ("arcade-cpu-07", ["builder prune -af"]),
    ("arcade-cpu-40", ["builder prune -af"]),
    # 11-08: test-gpu built its image in 682 s on an arcade GPU runner with no
    # cache, against 27 to 40 s with it; 11-09: under the day's rule alone
    # arcade-gpu-01 held 80 GB of it.
    ("arcade-gpu-03", KEPT_CACHE),
    ("utk-gpu", KEPT_CACHE),
    ("utk-desktop-03", KEPT_CACHE),
])
def test_all_build_cache_goes_on_an_arcade_cpu_runner_and_elsewhere_a_day_and_30_gb_stay(tmp_path, runner, prunes):
    result, calls, _, _ = _cleanup(tmp_path, runner)
    assert result.returncode == 0, result.stderr
    assert [call for call in calls if call.startswith("builder prune")] == prunes


def test_a_docker_before_28_holds_the_build_cache_to_30_gb_with_keep_storage(tmp_path):
    result, calls, _, _ = _cleanup(tmp_path, "arcade-gpu-03", refuse="--reserved-space")
    assert result.returncode == 0, result.stderr
    assert [call for call in calls if call.startswith("builder prune")] == KEPT_CACHE + [
        "builder prune -af --keep-storage 30GB"]
    assert "::warning::" not in result.stdout


def test_a_docker_that_cannot_hold_the_build_cache_says_so_and_the_cleanup_goes_on(tmp_path):
    result, calls, _, left = _cleanup(tmp_path, "arcade-gpu-03", refuse="--reserved-space --keep-storage")
    assert result.returncode == 0, result.stderr
    assert "::warning::the build cache could not be held to 30GB" in result.stdout
    assert left == OTHERS
    assert "Free disk after the cleanup:" in result.stdout


def test_the_ci_repository_is_found_from_a_mixed_case_name(tmp_path):
    _, _, removed, _ = _cleanup(tmp_path, "arcade-cpu-07", repository="Urban-Toolkit/curio")
    assert f"{CI_REPO}:{OTHER_SHA}" in removed
    assert f"{CI_REPO}:{SHA}" in removed


def test_the_disk_use_before_and_after_and_the_free_disk_go_to_the_log(tmp_path):
    result, calls, _, _ = _cleanup(tmp_path, "arcade-cpu-07")
    before = result.stdout.index("Docker disk use before the cleanup:")
    after = result.stdout.index("Docker disk use after the cleanup:")
    assert before < after < result.stdout.index("Free disk after the cleanup:")
    assert calls.count("system df") == 2
