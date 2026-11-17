"""Mounting a Discovery source's bucket, through the bucket mount service.

:func:`ensure` gives the folder a source's files are read from in place, when
this deployment runs the mount service (``--bucket-mounts-dir`` and
``--bucket-mount-socket``) and the source's bucket mounts
(``domain/bucket_mount.py``), or why not. A bucket's provider reads its
files there (``S3Storage.local_path`` and ``open``, through
:class:`BucketReads`, which the discovery service hands it); an add, media,
node code's collections and Cache files ask :func:`ensure` themselves.

rclone keeps each folder's listing for five minutes, so a file uploaded since
reads as missing: an add first has the listings of its files' folders read
again (:func:`refresh`), and a file not found is looked for once more after
its folder's listing is forgotten (:func:`forget`).

Mounting a source, the first time and after its mount was found dead, gone or
changed:

1. the host check: every address of the bucket's host is public
   (``egress_policy.public_addresses``). A host that fails it reaches no
   rclone call;
2. the host and port are admitted to the backend's proxy, the service's one
   way out (``infrastructure/mount_proxy.py``), which checks them again at
   each connection and connects to an address it checked. In a start of
   several backend processes the home process alone runs the proxy, and any
   process may mount: the hosts go into one list the start's processes share
   (:class:`SharedAdmissions`), each held by the process that admitted it;
3. ``operations/mkdir`` and ``mount/mount`` of the bucket's folder at
   ``/mounts/<sourceId>@<major>`` in the service, which is
   ``<bucket-mounts-dir>/<sourceId>@<major>`` here. Once that folder holds
   no mount of another remote, any other host the source was let through to
   before (its manifest named another host) is withdrawn, whichever process
   let it through;
4. that folder listed within :data:`LIST_SECONDS`, room for rclone's tries of
   a request that fails, on a thread of its own, so a hung FUSE call holds
   that thread and never the caller: the listing proves the mount reached
   this container and the bucket answers listings. A listing that fails or
   gives no answer names Curio's proxy when the proxy refused the bucket's
   host since the listing began (FUSE gives Curio EIO alone, so the proxy
   notes why, ``MountProxy.refusal_since``), and is otherwise followed by the
   self-test's way out (``bucket_mounts.reaches_proxy``): a service that
   reaches no proxy is named so, not the bucket.

A failure keeps one reason (:data:`REASONS`, the host check's own words, or
rclone's error), unmounts what it made, and the source is not tried again for
:data:`RETRY_SECONDS`; :func:`ensure` answers with the kept reason meanwhile.
One mount of a source at a time: a lock per source, and in a start of several
backend processes a file lock of the source's too, since rclone refuses a
second mount of a folder that holds one. A mounted source is looked at again
(a stat of its folder, on a thread too) once :data:`LOOK_SECONDS` have
passed: a dead mount (``ENOTCONN``), a mount that is gone, or one whose remote
no longer matches its manifest is mounted again.

At backend start, after a passed self-test (``bucket_mount_check.py``):
``mount/listmounts``. A mount of a source still in the catalog is admitted
again after its host check; every other but the self-test's is unmounted (a
source the operator removed, or one whose manifest names another bucket now).

Each call to the service tells ``bucket_mount_check`` whether it was
answered, so /monitor's line follows the service.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, NamedTuple, Optional

from utk_curio.backend.app.common import egress_policy, file_locks, shared_budgets
from utk_curio.backend.app.common.owner_only_file import ensure_private_dir
from utk_curio.backend.app.common.user_storage import curio_root
from utk_curio.backend.app.discovery.application import bucket_mount_check
from utk_curio.backend.app.discovery.application.catalog import DiscoveryCatalog
from utk_curio.backend.app.discovery.domain.bucket_mount import BucketMount, NotMountable, bucket_mount
from utk_curio.backend.app.discovery.domain.manifest import DiscoverySourceManifest
from utk_curio.backend.app.discovery.infrastructure import bucket_mounts
from utk_curio.backend.app.discovery.infrastructure.mount_proxy import REFUSALS_KEPT, MountProxy
from utk_curio.common import backend_processes

log = logging.getLogger(__name__)

#: How long the listing that proves a mount may take (``_check``): room for
#: rclone's tries of a request that fails. rclone lists in up to
#: ``--low-level-retries`` tries (3, ``scripts/bucket-mounts/service.sh``),
#: each of up to as many attempts of the S3 SDK, which back off up to 2 and
#: 4 s: up to 18 s against a proxy it cannot reach, where CI's bucket-mounts
#: job sees 3 to 9.4 s. Reads keep rclone's tries.
LIST_SECONDS = 30.0
#: How long a stat of a mounted folder may take, and the way out asked after
#: a listing that failed: a stat asks the bucket nothing, and Curio's proxy
#: hears the way out's first request at once.
STAT_SECONDS = 10.0
#: How long a source that failed to mount waits before it is tried again.
RETRY_SECONDS = 60.0
#: How long a mount found alive is taken as alive before it is looked at again.
LOOK_SECONDS = 5.0
#: How long a folder's listing, forgotten because a file in it was not found,
#: is not forgotten again: a row whose file left the bucket makes rclone list
#: its folder again at most this often.
FORGET_SECONDS = 30.0
#: The most folders an add has listed again before its files are read; a file
#: in another folder that reads as missing is looked for again once its
#: folder's listing is forgotten.
REFRESH_FOLDERS = 64
#: The deadline of that listing, in seconds: rclone lists the folders one
#: after another within one call.
REFRESH_SECONDS = 120.0
#: The forgotten folders remembered at most, for :data:`FORGET_SECONDS`.
_FORGOTTEN_KEPT = 1024

#: Why a source's bucket is not mounted, beside the host check's own words and
#: rclone's error.
REASONS = {
    "service": "the mount service is down",
    "timeout": f"the bucket's mount gave no answer in {LIST_SECONDS:g} s",
    "stat-timeout": f"the bucket's mount gave no answer in {STAT_SECONDS:g} s",
    "listing": "the bucket refuses listing",
    "not-propagated": "the mount did not reach this container",
    "proxy": f"the mount service cannot reach Curio's proxy on port {bucket_mounts.PROXY_PORT}",
    # Followed by the proxy's own words of why.
    "refused": "Curio's bucket mount proxy refused the requests to the bucket",
    "admission": "Curio could not let the bucket's host through its proxy",
}

#: The folder of the start's state that holds each source's lock in a start
#: of several backend processes, beside its budgets (``shared_budgets.FOLDER``),
#: which node code cannot reach: a node holding a source's lock would keep it
#: from mounting.
LOCKS = "bucket-mount-locks"

#: The /monitor problem (``bucket_mounts.PROBLEMS``) of a call that found the
#: service gone, by the rc client's kind of failure.
_GONE = {"unreachable": "no-service", "timeout": "no-answer"}


@dataclass(frozen=True)
class SourceMount:
    """What :func:`ensure` found for a source.

    ``state``: ``none`` when this deployment runs no mount service, and
    ``not-mountable`` when the source's bucket does not mount (``reason``
    says why); both read as they do without mounts. ``mounted``: the source's
    file ``relpath`` is ``folder / (tail + relpath)``. ``down``: it should
    mount and does not, for ``reason``.
    """

    state: str
    folder: Optional[Path] = None
    tail: str = ""
    reason: Optional[str] = None

    @property
    def mounted(self) -> bool:
        return self.state == "mounted"

    @property
    def in_place(self) -> bool:
        """Whether the source's files are read in place, through its mount:
        mounted, or down. Its copies cached before are not read then, and
        Cache files copies none."""
        return self.state in ("mounted", "down")


class _Failed(Exception):
    """A mount that failed: the kind, the reason people read, and what went
    wrong in more words, for the log."""

    def __init__(self, kind: str, reason: Optional[str] = None, detail: str = ""):
        self.kind = kind
        self.reason = reason or REASONS[kind]
        self.detail = detail
        super().__init__(self.reason)


class _Known(NamedTuple):
    """A source's mount this process holds: its remote, and when it was last
    found alive."""

    fs: str
    looked: float


class _Failure(NamedTuple):
    reason: str
    until: float


def fs_of(mount: BucketMount) -> str:
    """The connection string of *mount*'s remote."""
    return bucket_mounts.connection_string(
        "s3", bucket_mounts.s3_parameters(mount.endpoint, path_style=mount.path_style),
        bucket_mounts.remote_path(mount.bucket, mount.folder),
    )


def listed_fs_of(mount: BucketMount) -> str:
    """What ``mount/listmounts`` names *mount*'s remote by."""
    return bucket_mounts.listed_fs(
        "s3", bucket_mounts.s3_parameters(mount.endpoint, path_style=mount.path_style),
        bucket_mounts.remote_path(mount.bucket, mount.folder),
    )


def mount_point(name: str) -> str:
    """Where the service mounts the source mounted as *name*."""
    return f"{bucket_mounts.SERVICE_MOUNTS}/{name}"


class MountFolders:
    """How a mount's folder looks from this container. Tests give their own."""

    def look(self, folder: Path) -> str:
        """``mounted``; ``absent``, no mount there; or ``dead``, a stat that
        fails, as each does (``ENOTCONN``) once the service that mounted it
        is gone."""
        try:
            os.stat(folder)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "dead"
        return "mounted" if os.path.ismount(folder) else "absent"

    def list(self, folder: Path) -> bool:
        """List *folder* whole; False when it is no mount in this container.
        Raises ``OSError`` when the listing fails."""
        os.stat(folder)
        if not os.path.ismount(folder):
            return False
        with os.scandir(folder) as entries:
            count = sum(1 for _ in entries)
        log.debug("Bucket mounts: %s lists %d entries", folder, count)
        return True


class _MonitorLine:
    """Tells /monitor's line whether each call found the service."""

    @staticmethod
    def answered() -> None:
        bucket_mount_check.service_answered()

    @staticmethod
    def lost(problem: str, detail: str) -> None:
        bucket_mount_check.service_lost(problem, detail)


class BucketMountSources:
    """The sources' mounts of one mount service: the rc *client*, the folder
    its mounts show in here, and the *proxy* their hosts are admitted to.

    *folders*, *resolver*, *clock*, *monitor* and *self_test* are seams for
    tests: how folders look, the host check's resolver, the clock, what is
    told of the service, and why the self-test lets no source mount.
    *list_seconds* bounds a fresh mount's listing, and *stat_seconds* a stat
    of a mount's folder and the way out asked after a listing that failed.
    """

    def __init__(self, client, mounts_dir, *, proxy: MountProxy,
                 folders: Optional[MountFolders] = None, resolver=None,
                 clock: Callable[[], float] = time.monotonic,
                 list_seconds: float = LIST_SECONDS, stat_seconds: float = STAT_SECONDS,
                 retry_seconds: float = RETRY_SECONDS,
                 look_seconds: float = LOOK_SECONDS, forget_seconds: float = FORGET_SECONDS,
                 monitor=None, self_test: Optional[Callable[[], Optional[str]]] = None):
        self.client = client
        self.mounts_dir = Path(mounts_dir)
        self.proxy = proxy
        self.folders = folders or MountFolders()
        self._resolver = resolver
        self._clock = clock
        self.list_seconds = list_seconds
        self.stat_seconds = stat_seconds
        self.retry_seconds = retry_seconds
        self.look_seconds = look_seconds
        self.forget_seconds = forget_seconds
        self._monitor = monitor or _MonitorLine()
        self._self_test = self_test or bucket_mount_check.failed_self_test
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._known: dict[str, _Known] = {}
        self._failures: dict[str, _Failure] = {}
        self._stuck: dict[str, threading.Thread] = {}
        #: When each folder's listing, by mount and folder, was last forgotten.
        self._forgotten: dict[tuple[str, str], float] = {}

    @property
    def where(self) -> tuple[Path, str]:
        return self.mounts_dir, str(getattr(self.client, "socket_path", ""))

    # ── a source ───────────────────────────────────────────────────────────

    def ensure(self, manifest: DiscoverySourceManifest) -> SourceMount:
        """*manifest*'s bucket, mounted, or why not. Never raises for the
        service's answers."""
        try:
            mount = bucket_mount(manifest)
        except NotMountable as exc:
            return SourceMount("not-mountable", reason=str(exc))
        refused = self._self_test()
        if refused is not None:
            return SourceMount("down", tail=mount.tail, reason=refused)
        folder = self.mounts_dir / mount.name
        with self._lock_of(mount.name):
            failure = self._failures.get(mount.name)
            if failure is not None and self._clock() < failure.until:
                return SourceMount("down", tail=mount.tail, reason=failure.reason)
            try:
                self._keep_mounted(mount, folder)
            except _Failed as failed:
                return self._failed(mount, failed)
            self._failures.pop(mount.name, None)
        return SourceMount("mounted", folder=folder, tail=mount.tail)

    def _keep_mounted(self, mount: BucketMount, folder: Path) -> None:
        fs = fs_of(mount)
        known = self._known.get(mount.name)
        if known is not None and known.fs == fs and self._clock() - known.looked < self.look_seconds:
            return
        with self._held_across_processes(mount.name):
            if known is not None and known.fs == fs:
                seen = self._look(mount.name, folder)
                if seen == "mounted":
                    self._known[mount.name] = _Known(fs, self._clock())
                    return
                if seen == "hung":
                    raise _Failed("stat-timeout", detail=f"a stat of {folder} took over {self.stat_seconds:g} s")
                log.warning("Bucket mounts: the mount of %s is %s; it is mounted again", mount.name, seen)
            elif known is not None:
                log.info("Bucket mounts: %s's manifest names another bucket now; it is mounted again", mount.name)
            self._mount(mount, folder, fs)

    def _mount(self, mount: BucketMount, folder: Path, fs: str) -> None:
        try:
            egress_policy.public_addresses(mount.host, resolver=self._resolver)
        except egress_policy.EgressRefused as refused:
            raise _Failed("host", str(refused)) from None
        try:
            self.proxy.admit(mount.name, mount.host, mount.port)
        except OSError as exc:
            raise _Failed("admission", detail=f"the start's list of the hosts let through: {exc}") from None
        point = mount_point(mount.name)
        made = False
        try:
            listed = self._listed(point)
            if listed is not None:
                seen = self._look(mount.name, folder)
                if seen == "hung":
                    raise _Failed("stat-timeout", detail=f"a stat of {folder} took over {self.stat_seconds:g} s")
                if listed == listed_fs_of(mount) and seen == "mounted":
                    self.proxy.withdraw_others(mount.name, mount.host, mount.port)
                    self._check(mount, folder)
                    self._known[mount.name] = _Known(fs, self._clock())
                    log.info("Bucket mounts: %s was mounted already", mount.name)
                    return
                self._call("mount/unmount", {"mountPoint": point})
            # The folder holds no mount of another remote now, so no other
            # host the source was let through to before is reached for it,
            # whichever process let it through.
            self.proxy.withdraw_others(mount.name, mount.host, mount.port)
            self._call("operations/mkdir", {"fs": bucket_mounts.SERVICE_MOUNTS, "remote": mount.name})
            self._call("mount/mount", {"fs": fs, "mountPoint": point, **bucket_mounts.SOURCE_MOUNT_OPTIONS})
            made = True
            self._check(mount, folder)
        except _Failed:
            self._known.pop(mount.name, None)
            if made:
                self._unmount_quietly(point)
            self.proxy.withdraw(mount.name)
            raise
        self._known[mount.name] = _Known(fs, self._clock())
        log.info("Bucket mounts: mounted %s from %s", mount.name, fs)

    def _check(self, mount: BucketMount, folder: Path) -> None:
        """The mounted folder lists within the bound, and is a mount here. A
        listing that fails, or gives no answer, names Curio's proxy when it
        refused the bucket's host since the listing began: FUSE gives Curio
        EIO alone, and the proxy notes why, in a start of several backend
        processes for every process (``MountProxy.refusal_since``). Else it
        names the proxy when the service reaches no proxy at all
        (:meth:`_proxy_unreached`)."""
        began = time.time()
        outcome, value = self._bounded(mount.name, lambda: self.folders.list(folder), self.list_seconds)
        if outcome == "hung":
            failed = _Failed("timeout", detail=f"listing {folder} took over {self.list_seconds:g} s")
        elif outcome == "error":
            words = getattr(value, "strerror", None) or str(value)
            failed = _Failed("listing", detail=f"listing {folder}: {words}")
        elif value is False:
            raise _Failed("not-propagated", detail=f"{folder} is no mount in this container")
        else:
            return
        why = self.proxy.refusal_since(mount.host, mount.port, began)
        if why is not None:
            raise _Failed("refused", f"{REASONS['refused']}: {why}", detail=failed.detail)
        unreached = self._proxy_unreached()
        if unreached is not None:
            raise unreached
        raise failed

    def _proxy_unreached(self) -> Optional[_Failed]:
        """After a listing that failed or gave no answer: whether the service
        reaches Curio's proxy, its one way out, as the self-test asks
        (``bucket_mounts.reaches_proxy``), within a stat's bound. A ``proxy``
        failure when it does not, the service gone when nothing answers on
        its socket, and None when it reaches the proxy, so the listing's own
        failure stands. None too when the proxy does not listen in this
        process, which cannot tell: another backend process of a start of
        several runs it."""
        if not self.proxy.listening:
            return None
        try:
            reached, answered = bucket_mounts.reaches_proxy(self.client, self.proxy, timeout=self.stat_seconds)
        except bucket_mounts.RcError as error:
            self._monitor.lost(_GONE.get(error.kind, "no-service"), error.reason)
            return _Failed("service", detail=error.reason)
        return None if reached else _Failed("proxy", detail=answered)

    def _look(self, name: str, folder: Path) -> str:
        """``mounted``, ``absent``, ``dead`` or ``hung`` (no answer in a stat's bound)."""
        outcome, value = self._bounded(name, lambda: self.folders.look(folder), self.stat_seconds)
        if outcome == "hung":
            return "hung"
        if outcome == "error":
            return "dead"
        return value

    def _bounded(self, name: str, work: Callable[[], object], seconds: float) -> tuple[str, object]:
        """*work* on a thread of its own for at most *seconds*: ``("done",
        its value)``, ``("error", what it raised)`` or ``("hung", None)``.
        While a source's earlier thread is still stuck, it is hung at once,
        so a hung mount holds one thread, not one per call."""
        with self._lock:
            stuck = self._stuck.get(name)
            if stuck is not None:
                if stuck.is_alive():
                    return "hung", None
                del self._stuck[name]
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = work()
            except Exception as exc:  # noqa: BLE001 - the caller reports it as the mount's failure
                box["error"] = exc

        thread = threading.Thread(target=run, name=f"bucket-mount-look {name}", daemon=True)
        thread.start()
        thread.join(seconds)
        if thread.is_alive():
            with self._lock:
                self._stuck[name] = thread
            return "hung", None
        if "error" in box:
            return "error", box["error"]
        return "done", box.get("value")

    def _listed(self, point: str) -> Optional[str]:
        """What the service names its mount at *point* by, or None."""
        for entry in self._call("mount/listmounts").get("mountPoints") or []:
            if isinstance(entry, dict) and entry.get("MountPoint") == point:
                return str(entry.get("Fs") or "")
        return None

    def _call(self, method: str, params: Optional[dict] = None, *, timeout: Optional[float] = None) -> dict:
        try:
            if timeout is None:
                answer = self.client.call(method, params)
            else:
                answer = self.client.call(method, params, timeout=timeout)
        except bucket_mounts.RcError as error:
            problem = _GONE.get(error.kind)
            if problem is not None:
                self._monitor.lost(problem, error.reason)
                raise _Failed("service", detail=error.reason) from None
            self._monitor.answered()
            raise _Failed("rclone", error.reason) from None
        self._monitor.answered()
        return answer

    def _unmount_quietly(self, point: str) -> None:
        """Unmount what a failed mount made; its failure is the one reported."""
        try:
            self._call("mount/unmount", {"mountPoint": point})
        except _Failed as failed:
            log.warning("Bucket mounts: could not unmount %s after its mount failed: %s", point, failed.reason)

    def _failed(self, mount: BucketMount, failed: _Failed) -> SourceMount:
        self._failures[mount.name] = _Failure(failed.reason, self._clock() + self.retry_seconds)
        log.warning("Bucket mounts: %s is not mounted: %s%s", mount.name, failed.reason,
                    f" ({failed.detail})" if failed.detail else "")
        return SourceMount("down", tail=mount.tail, reason=failed.reason)

    def _lock_of(self, name: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(name, threading.Lock())

    @contextlib.contextmanager
    def _held_across_processes(self, name: str) -> Iterator[None]:
        """The source mounted as *name*, held by this process while it looks
        at, mounts or unmounts it, its thread lock (:meth:`_lock_of`) held
        already. In a start of several backend processes, also a file lock of
        the source's (:func:`_lock_file`), which every process takes: each
        process's own lock left two of them free to find no mount at once and
        both call ``mount/mount``, which rclone refuses for the second (the
        folder holds a mount), so that process kept the source down for a
        minute. A lock that cannot be taken is logged, and the source looked
        at with this process's lock alone."""
        if not shared_budgets.across_processes():
            yield
            return
        with contextlib.ExitStack() as held:
            try:
                held.enter_context(file_locks.interprocess_lock(_lock_file(name)))
            except OSError as exc:
                log.warning("Bucket mounts: backend process %d could not take %s's lock of the start: %s",
                            backend_processes.this_process(), name, exc)
            yield

    # ── a mounted source's listings ────────────────────────────────────────

    def forget(self, manifest: DiscoverySourceManifest, path: str) -> bool:
        """rclone forgets its listing of the folder that holds *path* (a
        file's path in *manifest*'s mount, ``tail + relpath``) and marks the
        listing above it stale, so the next look lists them again: a file
        uploaded, or a folder made, since rclone last listed them shows.

        False when nothing was forgotten: the source does not mount, that
        folder's listing was forgotten less than :data:`FORGET_SECONDS` ago,
        or the service refused (logged). A file at the mount's root marks the
        root's listing stale and drops none below it."""
        try:
            mount = bucket_mount(manifest)
        except NotMountable:
            return False
        folder = path.rpartition("/")[0]
        key = (mount.name, folder)
        with self._lock:
            now = self._clock()
            last = self._forgotten.get(key)
            if last is not None and now - last < self.forget_seconds:
                return False
            if len(self._forgotten) >= _FORGOTTEN_KEPT:
                for old in [k for k, when in self._forgotten.items() if now - when >= self.forget_seconds]:
                    del self._forgotten[old]
            self._forgotten[key] = now
        listed = listed_fs_of(mount)
        params = (bucket_mounts.forget_parameters(listed, dirs=[folder]) if folder
                  else bucket_mounts.forget_parameters(listed, files=[path]))
        try:
            self._call("vfs/forget", params)
        except _Failed as failed:
            log.warning("Bucket mounts: could not have %s's listing of %r read again: %s",
                        mount.name, folder or "/", failed.reason)
            return False
        return True

    def refresh(self, manifest: DiscoverySourceManifest, folders: Iterable[str]) -> None:
        """rclone lists *folders* of *manifest*'s mount again now (paths in
        the mount, ``""`` its root), after it has marked every listing above
        them stale, so the folders it walks through to reach them are listed
        again too: a file uploaded, or a folder made, since rclone last listed
        them shows. At most :data:`REFRESH_FOLDERS` folders, in one call of
        at most :data:`REFRESH_SECONDS`; a file elsewhere that reads as
        missing is looked for again after :meth:`forget`.

        Never raises: a folder rclone could not list, and a call that failed,
        are logged, and each file is looked for as it is read."""
        try:
            mount = bucket_mount(manifest)
        except NotMountable:
            return
        chosen = sorted(set(folders))[:REFRESH_FOLDERS]
        if not chosen:
            return
        listed = listed_fs_of(mount)
        # Each folder, and each above it, as a file of the folder holding it:
        # every listing from the root down to the one holding each folder is
        # stale, and the refresh reads each folder's own.
        above = sorted({"/".join(parts[:depth]) for parts in (folder.split("/") for folder in chosen if folder)
                        for depth in range(1, len(parts) + 1)})
        below_root = [folder for folder in chosen if folder]
        try:
            if above:
                self._call("vfs/forget", bucket_mounts.forget_parameters(listed, files=above))
            answer = self._call("vfs/refresh", bucket_mounts.refresh_parameters(listed, below_root),
                                timeout=REFRESH_SECONDS)
        except _Failed as failed:
            log.warning("Bucket mounts: could not have %s's folders listed again: %s", mount.name, failed.reason)
            return
        for folder, words in sorted(bucket_mounts.refresh_failures(answer).items()):
            log.info("Bucket mounts: %s could not list %r again: %s", mount.name, folder or "/", words)

    # ── at backend start ───────────────────────────────────────────────────

    def reconcile(self, manifests: Callable[[], Iterable[DiscoverySourceManifest]]) -> None:
        """The service's mounts as the backend starts: those of sources still
        in the catalog (*manifests*) admitted again after their host check,
        every other but the self-test's unmounted."""
        try:
            entries = self._call("mount/listmounts").get("mountPoints") or []
        except _Failed as failed:
            log.warning("Bucket mounts: the service's mounts could not be listed at start: %s", failed.reason)
            return
        prefix = bucket_mounts.SERVICE_MOUNTS + "/"
        found = []
        for entry in entries:
            point = entry.get("MountPoint") if isinstance(entry, dict) else None
            if not isinstance(point, str) or not point.startswith(prefix):
                continue
            name = point[len(prefix):]
            if name != bucket_mounts.SELFTEST_MOUNT:
                found.append((name, point, str(entry.get("Fs") or "")))
        if not found:
            return
        by_name = {manifest.dir_name: manifest for manifest in manifests()}
        for name, point, listed in found:
            with self._lock_of(name), self._held_across_processes(name):
                self._reconcile_one(name, point, listed, by_name.get(name))

    def _reconcile_one(self, name: str, point: str, listed: str,
                       manifest: Optional[DiscoverySourceManifest]) -> None:
        try:
            mount = bucket_mount(manifest) if manifest is not None else None
        except NotMountable:
            mount = None
        if mount is None:
            self._unmount_at_start(name, point, "no source of the catalog mounts there")
            return
        if listed != listed_fs_of(mount):
            self._unmount_at_start(name, point, "its source's manifest names another bucket now")
            return
        try:
            egress_policy.public_addresses(mount.host, resolver=self._resolver)
        except egress_policy.EgressRefused as refused:
            self._unmount_at_start(name, point, str(refused))
            self._failures[name] = _Failure(str(refused), self._clock() + self.retry_seconds)
            return
        self.proxy.admit(name, mount.host, mount.port)
        # Looked at by the next ensure before it is taken as alive.
        self._known[name] = _Known(fs_of(mount), -math.inf)
        log.info("Bucket mounts: %s, mounted before this start, is admitted again", name)

    def _unmount_at_start(self, name: str, point: str, why: str) -> None:
        try:
            self._call("mount/unmount", {"mountPoint": point})
        except _Failed as failed:
            log.warning("Bucket mounts: could not unmount %s (%s): %s", point, why, failed.reason)
        else:
            log.info("Bucket mounts: unmounted %s: %s", point, why)
        self.proxy.withdraw(name)
        self._known.pop(name, None)


def _lock_file(name: str) -> Path:
    """The file of the lock that holds the source mounted as *name* for one
    backend process of the start at a time: in :data:`LOCKS`, made ``0700``
    with the budgets' own folder. Raises ``OSError`` when it cannot be made."""
    root = curio_root() / shared_budgets.FOLDER
    ensure_private_dir(root)
    folder = root / LOCKS
    ensure_private_dir(folder)
    return folder / f"{name}.lock"


# ── The hosts a start of several processes lets through ─────────────────────

#: The start's document of the hosts its processes let through
#: (:class:`SharedAdmissions`), kept with its budgets.
ADMISSIONS = "bucket-mount-admissions"
#: Its one field: each host let through, as ``{host, port, source, process}``.
_ADMITTED = "admitted"


class SharedAdmissions:
    """The hosts the proxy lets through, in a start of several backend
    processes: one list for the start, which each process writes as it mounts
    and the proxy reads at each ``CONNECT`` (``MountProxy``'s *admissions*).

    The home process alone runs the proxy that listens (``server.py``), while
    a source is mounted in whichever process reads its files: a node's
    collection and a media read run in the process that owns the dataflow,
    any of them. A list in each process's memory let a host through only for
    the mounts home made. So the list is one document every process of the
    start reads and changes under its lock (``shared_budgets.State``, in
    ``.curio/budgets``, which node code cannot reach).

    Each entry is held by the process that let its host through, and
    :meth:`withdraw` takes this process's own alone: a mount that fails in one
    process leaves the host to another that still holds a mount of it. Once a
    source's folder holds a mount of another host's bucket, or none, its
    entries for any other host go, whichever process holds them
    (:meth:`withdraw_others`): one folder holds one mount. The document is the
    start's, so each start begins with none, as a process's memory does.
    """

    def __init__(self, state: Optional[shared_budgets.State] = None):
        self._state = state or shared_budgets.State(ADMISSIONS)

    def admit(self, name: str, host: str, port: int) -> None:
        """This process lets tunnels reach *host* at *port*, for the source
        mounted as *name*. Raises ``OSError`` when the list cannot be written."""
        entry = {"host": host, "port": port, "source": name, "process": backend_processes.this_process()}
        with self._state.held() as state:
            held = _entries(state)
            if entry not in held:
                state[_ADMITTED] = [*held, entry]

    def withdraw(self, name: str) -> None:
        """This process needs the host of the source mounted as *name* no
        more; what other processes hold stays. When the list cannot be
        written, that is logged, and this process's entry stays until the
        start ends."""
        here = backend_processes.this_process()
        try:
            with self._state.held() as state:
                held = _entries(state)
                kept = [entry for entry in held if (entry["source"], entry["process"]) != (name, here)]
                if kept != held:
                    state[_ADMITTED] = kept
        except OSError as exc:
            log.warning("Bucket mounts: backend process %d could not take %s's host off the hosts let through: %s",
                        here, name, exc)

    def withdraw_others(self, name: str, host: str, port: int) -> None:
        """The source mounted as *name* reaches *host* at *port* alone now:
        its folder holds a mount of that host's bucket, or none. Its entries
        for any other host and port go, whichever process holds them, since
        no mount reaches those for it any more. When the list cannot be
        written, that is logged, and those entries stay until the start
        ends."""
        try:
            with self._state.held() as state:
                held = _entries(state)
                kept = [entry for entry in held
                        if entry["source"] != name or (entry["host"], entry["port"]) == (host, port)]
                if kept != held:
                    state[_ADMITTED] = kept
        except OSError as exc:
            log.warning("Bucket mounts: backend process %d could not take %s's earlier hosts off the hosts let "
                        "through: %s", backend_processes.this_process(), name, exc)

    def admits(self, host: str, port: int) -> bool:
        """Whether a process of the start lets *host* at *port* through. A
        list that cannot be read lets nothing through, which is logged."""
        try:
            with self._state.held() as state:
                return any(entry["host"] == host and entry["port"] == port for entry in _entries(state))
        except OSError as exc:
            log.warning("Bucket mounts: the hosts let through could not be read, so %s port %d is refused: %s",
                        host, port, exc)
            return False


def _entries(state: dict) -> list[dict]:
    """The hosts let through that *state* holds, each entry as Curio writes
    one; anything else lets nothing through."""
    kept = state.get(_ADMITTED)
    return [
        entry for entry in (kept if isinstance(kept, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("host"), str) and isinstance(entry.get("port"), int)
        and isinstance(entry.get("source"), str) and isinstance(entry.get("process"), int)
    ]


# ── What the proxy of a start of several processes refused ──────────────────

#: The start's document of the proxy's refusals (:class:`SharedRefusals`),
#: kept with its budgets.
REFUSALS = "bucket-mount-refusals"
#: Its one field: the latest refusal of each host and port, as
#: ``{host, port, why, at}``, the latest last.
_REFUSED = "refused"


class SharedRefusals:
    """Curio's proxy's latest refusal of each host and port, in a start of
    several backend processes: one document for the start, which home's
    proxy writes as it refuses a ``CONNECT`` (``MountProxy``'s *refusals*)
    and any process reads once its mount's listing failed
    (``MountProxy.refusal_since``). FUSE gives that process EIO alone, and only
    the proxy, in home, knows it refused the bucket's host, and why.

    A note holds the host, its port, why and when (``time.time()``): never a
    path, which a ``CONNECT`` does not carry, and never the self-test's host,
    which the proxy does not note. At most ``mount_proxy.REFUSALS_KEPT`` hosts
    and ports, the latest. The document is the start's, so each start begins
    with none.
    """

    def __init__(self, state: Optional[shared_budgets.State] = None):
        self._state = state or shared_budgets.State(REFUSALS)

    def note(self, host: str, port: int, why: str, at: float) -> None:
        """The proxy refused *host* at *port* at *at*, for *why*. Raises
        ``OSError`` when the document cannot be written."""
        with self._state.held() as state:
            kept = [entry for entry in _refusals(state) if (entry["host"], entry["port"]) != (host, port)]
            state[_REFUSED] = [*kept, {"host": host, "port": port, "why": why, "at": at}][-REFUSALS_KEPT:]

    def since(self, host: str, port: int, since: float) -> Optional[str]:
        """Why the proxy refused *host* at *port* at *since* or later, or
        None; None too, logged, when the document cannot be read."""
        try:
            with self._state.held() as state:
                noted = [entry for entry in _refusals(state) if (entry["host"], entry["port"]) == (host, port)]
        except OSError as exc:
            log.warning("Bucket mounts: the proxy's refusals of %s port %d could not be read: %s", host, port, exc)
            return None
        return noted[-1]["why"] if noted and noted[-1]["at"] >= since else None


def _refusals(state: dict) -> list[dict]:
    """The refusals that *state* holds, each as Curio writes one."""
    kept = state.get(_REFUSED)
    return [
        entry for entry in (kept if isinstance(kept, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("host"), str) and isinstance(entry.get("port"), int)
        and isinstance(entry.get("why"), str) and isinstance(entry.get("at"), (int, float))
    ]


# ── The process's service ────────────────────────────────────────────────────

_LOCK = threading.Lock()
_proxy: Optional[MountProxy] = None
_sources: Optional[BucketMountSources] = None


def _the_proxy() -> MountProxy:
    """The process's proxy; the caller holds ``_LOCK``. In a start of several
    backend processes it lets through the hosts of the start's list
    (:class:`SharedAdmissions`), whichever process let them through, and
    notes its refusals for every process (:class:`SharedRefusals`); with one,
    in its memory."""
    global _proxy
    if _proxy is None:
        if shared_budgets.across_processes():
            _proxy = MountProxy(admissions=SharedAdmissions(), refusals=SharedRefusals())
        else:
            _proxy = MountProxy()
    return _proxy


def process_proxy() -> MountProxy:
    """The process's proxy: the one :func:`start_proxy` starts, which the
    self-test has the service reach (``bucket_mount_check``)."""
    with _LOCK:
        return _the_proxy()


def start_proxy(host: str) -> bool:
    """Start the proxy on *host*, where the backend listens, at
    ``bucket_mounts.PROXY_PORT``, when the flags name a mount service.
    Whether it listens."""
    if bucket_mounts.configured() is None:
        return False
    with _LOCK:
        proxy = _the_proxy()
    try:
        port = proxy.start(host, bucket_mounts.PROXY_PORT)
    except OSError as exc:
        detail = f"the bucket mount proxy could not listen on {host} port {bucket_mounts.PROXY_PORT}: {exc}"
        log.error("Bucket mounts: %s", detail)
        from utk_curio.backend.app.monitor import errors as monitor_errors

        monitor_errors.record("backend", summary="Bucket mounts reach no bucket: their proxy did not start",
                              detail=detail)
        return False
    log.info("Bucket mounts: the proxy listens on %s port %d", host, port)
    return True


def sources() -> Optional[BucketMountSources]:
    """The sources' mounts of the service the flags name, or None."""
    global _sources
    named = bucket_mounts.configured()
    if named is None:
        return None
    folder, socket_path = named
    with _LOCK:
        if _sources is None or _sources.where != (folder, str(socket_path)):
            _sources = BucketMountSources(bucket_mounts.RcClient(socket_path), folder, proxy=_the_proxy())
        return _sources


def ensure(manifest: DiscoverySourceManifest) -> SourceMount:
    """*manifest*'s bucket mounted, or why not (:class:`SourceMount`)."""
    the_sources = sources()
    if the_sources is None:
        return SourceMount("none")
    return the_sources.ensure(manifest)


def forget(manifest: DiscoverySourceManifest, path: str) -> bool:
    """rclone lists the folder holding *path* of *manifest*'s mount again when
    it next reads it (:meth:`BucketMountSources.forget`). Whether it will."""
    the_sources = sources()
    return the_sources.forget(manifest, path) if the_sources is not None else False


def refresh(manifest: DiscoverySourceManifest, folders: Iterable[str]) -> None:
    """rclone lists *folders* of *manifest*'s mount again now
    (:meth:`BucketMountSources.refresh`). Never raises."""
    the_sources = sources()
    if the_sources is not None:
        the_sources.refresh(manifest, folders)


def folders_of(mount: SourceMount, relpaths: Iterable[str]) -> set[str]:
    """The folders of a mounted source's files *relpaths*, as paths in its
    mount (``""`` its root): what an add has listed again (:func:`refresh`)."""
    return {(mount.tail + relpath).rpartition("/")[0] for relpath in relpaths}


def cache_refusal(found: SourceMount) -> Optional[str]:
    """Why Cache files copies nothing of a source read in place: its files
    are read from its bucket, which may be down now, with the reason. None
    for one that does not mount here, which keeps Cache files."""
    if found.state == "mounted":
        return "its files are read in place from the bucket"
    if found.state == "down":
        return f"its files are read in place from the bucket, which cannot be read now: {found.reason}"
    return None


class BucketReads:
    """How a bucket's provider reads it in place (``S3Storage``): the
    discovery service builds one for each source it builds a provider of.
    Nothing is asked of the mount service until a file is read:
    :meth:`state` mounts the bucket on demand (:func:`ensure`)."""

    def __init__(self, manifest: DiscoverySourceManifest):
        self.manifest = manifest

    def state(self) -> SourceMount:
        """The bucket's mount, or why there is none."""
        return ensure(self.manifest)

    def forget(self, path: str) -> bool:
        """rclone lists the folder holding *path*, a path in the mount, again
        when it next reads it (:func:`forget`). Whether it will."""
        return forget(self.manifest, path)


def reconcile_at_start() -> None:
    """The service's mounts, looked at as the backend starts. Never raises."""
    the_sources = sources()
    if the_sources is None:
        return
    try:
        the_sources.reconcile(lambda: DiscoveryCatalog().manifests())
    except Exception:  # noqa: BLE001 - a start never fails over this; the log says why
        log.exception("Bucket mounts: looking at the service's mounts at start failed")


def reset() -> None:
    """Stop the proxy and forget every source's mount. For tests only."""
    global _proxy, _sources
    with _LOCK:
        proxy, _proxy, _sources = _proxy, None, None
    if proxy is not None:
        proxy.stop()
