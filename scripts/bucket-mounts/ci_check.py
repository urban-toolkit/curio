"""The checks CI's bucket-mounts job runs in its stand-in for Curio's container
(.github/workflows/docker-compose.yml, docker-compose.ci-bucket-mounts.yml).

Each runs the backend's own code, discovery/infrastructure/bucket_mounts.py,
loaded by its path: the stand-in has the checkout, not Curio's libraries.

    selftest       the self-test the backend runs as it starts, which must read
                   as an execution account that is not root
    source-mount   mount two sources' buckets as the backend mounts them
                   (application/bucket_mount_sources.py): rclone takes the
                   parameters, names each mount as the backend expects, the
                   mount shows here, and its listing fails, since nothing
                   listens on the proxy's port in the stand-in
    leave-mounted  mount the service's test folder, read it as that account,
                   check it refuses a write, and leave it mounted, as a service
                   that stops without unmounting leaves its mounts
    dead           the test mount is still listed here, and dead
    gone           the test mount is gone, and its folder lists again

Each prints what it found, and exits 1 when the check fails.
"""

from __future__ import annotations

import errno
import importlib.util
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "utk_curio" / "backend" / "app" / "discovery" / "infrastructure" / "bucket_mounts.py"


def load():
    """bucket_mounts.py, loaded by its path."""
    spec = importlib.util.spec_from_file_location("bucket_mounts", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def listed(path: Path) -> bool:
    """Whether this container's mount table has a mount at *path*."""
    with open("/proc/self/mounts", encoding="utf-8") as table:
        return any(len(fields) > 1 and fields[1] == str(path) for fields in (line.split() for line in table))


def fail(message: str) -> int:
    print(f"FAILED: {message}")
    return 1


def account_of(mounts):
    """The execution account the reads run as: there, and not root."""
    account = mounts.execution_account()
    if account is None or account.uid == 0:
        raise SystemExit(fail("no execution account other than root: a read as root proves nothing"))
    return account


def selftest(mounts) -> int:
    account_of(mounts)
    outcome = mounts.self_test_from_env()
    if outcome is None:
        return fail("the environment names no mount service")
    print(f"self-test: passed={outcome.passed} problem={outcome.problem}: {outcome.detail}")
    return 0 if outcome.passed else fail(mounts.PROBLEMS.get(outcome.problem, outcome.problem))


#: Two sources' mounts: the shipped Sentinel-2 source's bucket, virtual-hosted
#: (discovery/source.aws.sentinel-2-chicago@1), and a path-style one with a
#: port. Each is (mount name, endpoint, bucket, folder, path style).
SOURCE_MOUNTS = (
    ("source.ci.virtual-hosted@1", "https://s3.us-west-2.amazonaws.com", "sentinel-cogs",
     "sentinel-s2-l2a-cogs/16/T/DM/2024/7", False),
    ("source.ci.path-style@1", "https://data.example.org:9000", "bucket", "", True),
)
#: How long a source mount's listing may take to fail with no way out.
NO_WAY_OUT_SECONDS = 60


def source_mount(mounts) -> int:
    folder, socket_path = mounts.configured()
    client = mounts.RcClient(socket_path)
    for name, endpoint, bucket, prefix, path_style in SOURCE_MOUNTS:
        parameters = mounts.s3_parameters(endpoint, path_style=path_style)
        path = mounts.remote_path(bucket, prefix)
        fs = mounts.connection_string("s3", parameters, path)
        point = f"{mounts.SERVICE_MOUNTS}/{name}"
        try:
            client.call("operations/mkdir", {"fs": mounts.SERVICE_MOUNTS, "remote": name})
            client.call("mount/mount", {"fs": fs, "mountPoint": point, **mounts.SOURCE_MOUNT_OPTIONS})
        except mounts.RcError as error:
            return fail(f"mounting {fs} at {point}: {error.reason}")
        try:
            failed = _a_source_mount(client, folder / name, point, mounts.listed_fs("s3", parameters, path))
        finally:
            try:
                client.call("mount/unmount", {"mountPoint": point})
            except mounts.RcError as error:
                print(f"could not unmount {point}: {error.reason}")
        if failed:
            return failed
        print(f"mounted {fs} at {point}; it reached no bucket with no proxy, and is unmounted")
    return 0


def _a_source_mount(client, here: Path, point: str, expected: str) -> int:
    entries = client.call("mount/listmounts").get("mountPoints") or []
    names = [entry.get("Fs") for entry in entries if entry.get("MountPoint") == point]
    if names != [expected]:
        return fail(f"the service lists {point} as {names}, not [{expected!r}]")
    print(f"the service lists {point} as {expected}")
    if not listed(here):
        return fail(f"the mount at {point} did not reach this container at {here}")
    started = time.monotonic()
    box = {}

    def read():
        try:
            box["entries"] = os.listdir(here)
        except OSError as exc:
            box["error"] = exc

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(NO_WAY_OUT_SECONDS)
    took = time.monotonic() - started
    if reader.is_alive():
        return fail(f"listing {here} gave no answer in {NO_WAY_OUT_SECONDS} s")
    if "error" not in box:
        return fail(f"listing {here} answered {box['entries'][:5]} with no proxy to reach a bucket through")
    print(f"listing {here} failed after {took:.1f} s, as it must with no way out: {box['error']}")
    return 0


def leave_mounted(mounts) -> int:
    account = account_of(mounts)
    folder, socket_path = mounts.configured()
    client = mounts.RcClient(socket_path)
    try:
        mounts.unmount_test_folder(client, only_if_mounted=True)
        mounts.mount_test_folder(client)
        text = mounts.read_test_file(folder / mounts.SELFTEST_MOUNT / mounts.SELFTEST_FILE, account)
    except mounts.SelfTestFailed as failed:
        return fail(f"{failed.problem}: {failed.detail}")
    if text.strip() != mounts.SELFTEST_LINE:
        return fail(f"the test mount holds {text!r}")
    written = folder / mounts.SELFTEST_MOUNT / "written-by-ci"
    try:
        with open(written, "w", encoding="utf-8") as handle:
            handle.write("a read-only mount takes no file")
    except OSError as exc:
        print(f"a write into the test mount was refused, as it must be: {exc}")
    else:
        return fail(f"the test mount took a write: {written}")
    print(f"mounted, read as {account.name} and left mounted: {folder / mounts.SELFTEST_MOUNT}")
    return 0


#: How long dead waits for the killed service's mount to stop answering.
DEAD_WAIT_SECONDS = 15


def dead(mounts) -> int:
    folder, _ = mounts.configured()
    mount = folder / mounts.SELFTEST_MOUNT
    deadline = time.monotonic() + DEAD_WAIT_SECONDS
    while True:
        if not listed(mount):
            return fail(f"no mount is listed at {mount}: the stopped service left nothing to clear")
        try:
            os.listdir(mount)
        except OSError as exc:
            if exc.errno != errno.ENOTCONN:
                return fail(f"listing {mount} failed with {exc}, not ENOTCONN")
            print(f"{mount} is dead, as a stopped service leaves it: {exc}")
            return 0
        if time.monotonic() >= deadline:
            return fail(f"{mount} still answers {DEAD_WAIT_SECONDS} s on: the service did not stop")
        time.sleep(0.5)


def gone(mounts) -> int:
    folder, _ = mounts.configured()
    mount = folder / mounts.SELFTEST_MOUNT
    if listed(mount):
        return fail(f"a mount is still listed at {mount}: the service's start did not clear it")
    print(f"{mount} is no mount any more, and lists: {os.listdir(mount)}")
    return 0


CHECKS = {
    "selftest": selftest, "source-mount": source_mount,
    "leave-mounted": leave_mounted, "dead": dead, "gone": gone,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in CHECKS:
        print(f"usage: {argv[0]} {{{','.join(CHECKS)}}}")
        return 2
    return CHECKS[argv[1]](load())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
