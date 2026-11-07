"""The CI image's Python packages for the pytest a job runs on the runner.

``scripts/ci_image_python.sh`` is ``.github/actions/image-env``. On an arcade
runner it mounts the image's own site-packages read-only in place, through a
helper container whose bind reaches the runner, since copying them wrote 9.4 GB
per job onto the disk all arcade runners share. Elsewhere, and when the mount
does not come up, it copies them as before. ``release`` unmounts in each
helper before removing it, unmounts a bind a killed helper left, and never
touches a mount outside its own folder or removes that folder while anything
is still mounted in it.

Docker, ``mountpoint``, ``python`` and ``sleep`` are stand-ins here: each logs
or answers what the script asks, so the test runs anywhere and fast.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "ci_image_python.sh"
IMAGE = "ghcr.io/urban-toolkit/curio-ci:584ee988783fdb22f4468d698b42e235d0b3fb72"
IN_IMAGE = "/usr/local/lib/python3.12/site-packages"

#: Logs every call. The helper's run marks its bind's source as mounted and
#: fills it, unless FAKE_NO_MOUNT is set; a copy fills its destination; an
#: nsenter umount drops its mount from the mount table, unless FAKE_STUCK is
#: set; ps answers the helpers listed in FAKE_HELPERS.
FAKE_DOCKER = r"""#!/bin/sh
echo "$*" >> "$DOCKER_LOG"
fill() { mkdir -p "$1/playwright" "$1/pytest"; }
case "$1" in
  ps) cat "$FAKE_HELPERS" 2> /dev/null ;;
  create) echo copy-container ;;
  cp) fill "$3" ;;
  run)
    last=""
    for arg in "$@"; do
      case "$arg" in
        type=bind,source=*) site=${arg#type=bind,source=}; site=${site%%,*} ;;
      esac
      last=$arg
    done
    case "$*" in
      *nsenter*)
        if [ -z "${FAKE_STUCK:-}" ]; then
          grep -v -F " $last " "$CURIO_CI_MOUNTINFO" > "$CURIO_CI_MOUNTINFO.new" || true
          mv "$CURIO_CI_MOUNTINFO.new" "$CURIO_CI_MOUNTINFO"
        fi ;;
      *bind-propagation=rshared*)
        if [ -z "${FAKE_NO_MOUNT:-}" ]; then fill "$site"; touch "$site/.mounted"; fi
        echo helper-container ;;
    esac ;;
esac
exit 0
"""

#: mountpoint -q <path>: mounted once the helper marked it.
FAKE_MOUNTPOINT = '#!/bin/sh\n[ -e "$2/.mounted" ]\n'

#: python -m venv --without-pip <dir>: a virtual environment whose python
#: imports playwright and pytest only when its site-packages holds them.
FAKE_PYTHON = r"""#!/bin/sh
[ "$1 $2" = "-m venv" ] || exit 1
dir=$4
mkdir -p "$dir/bin" "$dir/lib/python3.12/site-packages"
printf '#!/bin/sh\n[ -d "%s/playwright" ] && [ -d "%s/pytest" ]\n' \
  "$dir/lib/python3.12/site-packages" "$dir/lib/python3.12/site-packages" > "$dir/bin/python"
chmod +x "$dir/bin/python"
"""


def _run(tmp_path, command, runner, helpers=(), mounted=(), **fakes):
    """Run the script; return its result, the docker calls, the home and GITHUB_PATH's lines."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in [("docker", FAKE_DOCKER), ("mountpoint", FAKE_MOUNTPOINT),
                       ("python", FAKE_PYTHON), ("sleep", "#!/bin/sh\nexit 0\n")]:
        tool = bin_dir / name
        tool.write_text(text)
        tool.chmod(0o755)
    home = tmp_path / "home"
    (home / "curio-image-python").mkdir(parents=True, exist_ok=True)
    temp = tmp_path / "temp"
    temp.mkdir(exist_ok=True)
    (tmp_path / "helpers.txt").write_text("".join(f"{cid}\n" for cid in helpers))
    (tmp_path / "mountinfo").write_text(
        "".join(f"{100 + i} 1 0:{50 + i} / {where} ro,relatime shared:1 - overlay overlay ro\n"
                for i, where in enumerate(mounted)))
    log = tmp_path / "docker.log"
    log.write_text("")
    github_path = tmp_path / "github_path"
    github_path.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "DOCKER_LOG": str(log),
           "FAKE_HELPERS": str(tmp_path / "helpers.txt"), "CURIO_CI_MOUNTINFO": str(tmp_path / "mountinfo"),
           "RUNNER_NAME": runner, "RUNNER_TEMP": str(temp), "HOME": str(home),
           "GITHUB_PATH": str(github_path), "GITHUB_RUN_ID": "42", "GITHUB_RUN_ATTEMPT": "1", **fakes}
    result = subprocess.run(["bash", str(SCRIPT), *command], env=env, capture_output=True, text=True,
                            timeout=60)
    return result, log.read_text().splitlines(), home, github_path.read_text().splitlines()


def test_a_runner_that_is_not_an_arcade_one_copies_them(tmp_path):
    result, calls, home, path = _run(tmp_path, ["take", IMAGE], "GitHub Actions 7")
    assert result.returncode == 0, result.stderr
    assert calls[0] == f"create {IMAGE}"
    assert calls[1] == f"cp copy-container:{IN_IMAGE} {tmp_path}/temp/curio-image-python/lib/python3.12/site-packages"
    assert not any(call.startswith(("run ", "ps ", "exec ")) for call in calls)
    assert path == [f"{tmp_path}/temp/curio-image-python/bin"]
    assert "image-env: copy (not an arcade runner)" in result.stdout
    assert "of packages in" in result.stdout


def test_an_arcade_runner_mounts_the_images_own_folder_read_only_and_copies_nothing(tmp_path):
    result, calls, home, path = _run(tmp_path, ["take", IMAGE], "arcade-cpu-05")
    assert result.returncode == 0, result.stderr
    venv = f"{home}/curio-image-python/42-1-"
    [helper] = [call for call in calls if call.startswith("run ")]
    assert helper.startswith(f"run -d --rm --privileged --network none --log-driver none "
                             f"--label curio-ci.image-python={venv}")
    assert f"--mount type=bind,source={venv}" in helper
    assert "/lib/python3.12/site-packages,target=/mnt/site,bind-propagation=rshared" in helper
    assert helper.endswith(f"--entrypoint bash {IMAGE} -c mount --bind -o ro {IN_IMAGE} /mnt/site "
                           f"&& exec sleep infinity")
    assert not any(call.startswith(("create ", "cp ")) for call in calls)
    [bin_dir] = path
    assert bin_dir.startswith(venv) and bin_dir.endswith("/bin")
    assert "image-env: in place" in result.stdout
    assert "nothing copied" in result.stdout


def test_a_mount_that_never_reaches_the_runner_is_let_go_and_the_packages_are_copied(tmp_path):
    result, calls, home, path = _run(tmp_path, ["take", IMAGE], "arcade-cpu-05", FAKE_NO_MOUNT="1")
    assert result.returncode == 0, result.stderr
    assert "::warning::image-env: the image's packages could not be used in place " \
           "(no mount reached the runner within 10 s)" in result.stdout
    assert "image-env: copy (in place failed: no mount reached the runner within 10 s)" in result.stdout
    run = next(i for i, call in enumerate(calls) if call.startswith("run "))
    assert calls.index("ps -aq --filter label=curio-ci.image-python", run) < calls.index(f"create {IMAGE}")
    assert path == [f"{tmp_path}/temp/curio-image-python/bin"]
    assert not (home / "curio-image-python").exists()


def test_a_take_first_lets_go_of_what_an_earlier_job_left(tmp_path):
    result, calls, _, _ = _run(tmp_path, ["take", IMAGE], "arcade-cpu-05", helpers=["old-helper"])
    assert result.returncode == 0, result.stderr
    run = next(i for i, call in enumerate(calls) if call.startswith("run "))
    assert calls.index("exec old-helper umount -l /mnt/site") < calls.index("rm -f old-helper") < run


def test_release_unmounts_in_each_helper_before_it_removes_them_and_touches_no_other_container(tmp_path):
    result, calls, home, _ = _run(tmp_path, ["release"], "arcade-gpu-03", helpers=["h1", "h2"])
    assert result.returncode == 0, result.stderr
    assert calls[0] == "ps -q --filter label=curio-ci.image-python"
    assert calls.index("exec h1 umount -l /mnt/site") < calls.index("rm -f h1 h2")
    assert calls.index("exec h2 umount -l /mnt/site") < calls.index("rm -f h1 h2")
    assert "ps -aq --filter label=curio-ci.image-python" in calls
    assert [call for call in calls if call.startswith("rm ")] == ["rm -f h1 h2"]
    assert not (home / "curio-image-python").exists()


def test_release_unmounts_a_bind_a_killed_helper_left_and_no_other_mount(tmp_path):
    home = tmp_path / "home"
    stale = f"{home}/curio-image-python/41-1-7/lib/python3.12/site-packages"
    others = ["/var/lib/docker", f"{home}/curio-image-python-other/x", "/home/runner/actions-runner/_work"]
    result, calls, _, _ = _run(tmp_path, ["release"], "arcade-cpu-05", mounted=[*others, stale])
    assert result.returncode == 0, result.stderr
    nsenter = [call for call in calls if "nsenter" in call]
    assert nsenter == [f"run --rm --privileged --pid=host --network none alpine nsenter -t 1 -m -- umount -l {stale}"]
    assert not any(other in call for other in others for call in calls)
    assert not (home / "curio-image-python").exists()


def test_release_never_removes_its_folder_while_something_is_still_mounted_in_it(tmp_path):
    home = tmp_path / "home"
    stale = f"{home}/curio-image-python/41-1-7/lib/python3.12/site-packages"
    result, _, _, _ = _run(tmp_path, ["release"], "arcade-cpu-05", mounted=[stale], FAKE_STUCK="1")
    assert result.returncode == 0, result.stderr
    assert f"::warning::image-env: still mounted under {home}/curio-image-python: {stale}" in result.stdout
    assert (home / "curio-image-python").exists()


def test_release_does_nothing_on_a_runner_that_is_not_an_arcade_one(tmp_path):
    for runner in ["utk-gpu", "utk-desktop-03", "GitHub Actions 7"]:
        result, calls, home, _ = _run(tmp_path, ["release"], runner, helpers=["h1"])
        assert result.returncode == 0, result.stderr
        assert calls == []
        assert (home / "curio-image-python").exists()
