"""Isolated nodes' memory as a cgroup limit.

Each isolated run gets a cgroup of its own, a *place*, whose ``memory.max`` is
``--exec-memory-mb``: the memory the node's processes use, its child and
every process it starts, the page cache they are charged for included and the
GPU's memory not. At the budget the kernel stops all of them at once
(``memory.oom.group``), and the place's ``memory.events`` says it did, which
picks the node's message (``supervisor.describe_child_death``).

It needs Linux, root, and a container that may arrange the cgroups below its
own: Docker Engine 28 or newer with ``--security-opt writable-cgroups=true``
and a private cgroup namespace (``docker-compose.deploy.yml``). Root in such a
container can make cgroups below the container's own, move its processes
into them and set their limits. It cannot change the container's own limits,
which the host's ``nsdelegate`` keeps, and an unprivileged account, as
``curio-exec`` is, writes no cgroup file at all. Where any of that is missing,
:func:`unavailable` says why, and a child keeps the address-space cap
(``child._apply_rlimits``).

The layout, which the sandbox makes as it starts, before it serves
(:func:`lay_out`, ``lifecycle.lay_out_at_start``)::

    /sys/fs/cgroup                  the container's own cgroup
    /sys/fs/cgroup/curio            every process of the container
    /sys/fs/cgroup/nodes            root's, 0755
    /sys/fs/cgroup/nodes/<pid>/<k>  a zygote's places, one per run in flight

cgroup v2 hands a cgroup's controllers to its children only while no process
sits in it, so every process moves to ``curio`` first, and ``docker exec``
lands there too from then on. Every folder made here is ``0755`` whatever the
umask, so the execution account can make no cgroup.

A place is reused run after run (:class:`Places`): a cgroup removed while page
cache it was charged for lives stays behind, "dying", until that cache goes,
so a cgroup per run would leave one behind every run that read a file
(diagnostic run 42715453736, on kernels 5.15, 6.8 and 7.0).
"""

import contextlib
import errno
import os
import signal
import sys
import time

ROOT = "/sys/fs/cgroup"
#: Every process of the container, the servers and the zygotes among them.
SERVERS = "curio"
#: The zygotes' places, one folder per zygote.
NODES = "nodes"
#: What the places get from their parents. pids too, which no place limits:
#: RLIMIT_NPROC stays the child's.
CONTROLLERS = ("memory", "pids")

#: The node memory limits /version and /monitor name.
CGROUP = "cgroup"
ADDRESS_SPACE = "address space"

#: What a zygote asked for places prints on its stdout before it is ready:
#: the limit its children run under, as JSON (``zygote._make_places``).
MEMORY_LINE = "ZYGOTE_MEMORY"

#: The inode numbers of the host's own cgroup and pid namespaces
#: (PROC_CGROUP_INIT_INO, PROC_PID_INIT_INO).
HOST_CGROUP_NAMESPACE = 0xEFFFFFFB
HOST_PID_NAMESPACE = 0xEFFFFFFC

#: Why isolated nodes keep the address-space cap, by key: a closed list,
#: which /monitor shows. The sandbox log says more.
REASONS = {
    "no-linux": "this platform has no cgroups",
    "not-root": "the sandbox does not run as root",
    "no-cgroup2": "there is no cgroup v2 at /sys/fs/cgroup (cgroup v1, or none)",
    "host-namespace": "the container shares the host's cgroup namespace",
    "host-pid-namespace": "the container shares the host's process namespace",
    "read-only": "the container's cgroups are read-only (Docker's writable-cgroups option)",
    "outside": "the sandbox runs outside its cgroup namespace",
    "no-memory": "the memory controller is not the container's to hand out",
    "layout": "the container's cgroups could not be laid out (the sandbox log says why)",
    "places": "the zygote could not make its nodes' cgroups (the sandbox log says why)",
    "requested": "the address-space cap was asked for",
}

MIB = 1024 * 1024

#: How many times the layout moves the container's processes before it gives
#: up: a process can start in the root while the others move.
_LAYOUT_ATTEMPTS = 20

#: How long a new zygote waits for a dead one's place to empty before it
#: removes the place, in seconds.
_CLEAR_WAIT_SECONDS = 2.0

#: What a zygote's command line holds, which tells its places from another
#: process's that reused its pid.
_ZYGOTE_MODULE = b"utk_curio.sandbox.isolation.zygote"


def _read(path):
    with open(path, encoding="ascii") as handle:
        return handle.read()


def _write(path, value):
    with open(path, "w", encoding="ascii") as handle:
        handle.write(str(value))


def _make(path):
    """Make the cgroup *path*, ``0755`` and root's whatever the umask."""
    with contextlib.suppress(FileExistsError):
        os.mkdir(path)
    os.chmod(path, 0o755)


def _enable(path, names):
    """Hand *names*, the controllers *path* has, to *path*'s children."""
    if names:
        _write(os.path.join(path, "cgroup.subtree_control"), " ".join("+" + name for name in names))


def _controllers(path):
    """The controllers of :data:`CONTROLLERS` that cgroup *path* has."""
    have = _read(os.path.join(path, "cgroup.controllers")).split()
    return [name for name in CONTROLLERS if name in have]


def counters(text):
    """A cgroup's keyed counters, as ``memory.events`` holds them."""
    found = {}
    for line in (text or "").splitlines():
        key, _, value = line.partition(" ")
        value = value.strip()
        if key and value.isdigit():
            found[key] = int(value)
    return found


def _events(path):
    try:
        return counters(_read(os.path.join(path, "memory.events")))
    except OSError:
        return {}


# ---------------------------------------------------------------------------
# Whether this container's cgroups can hold its nodes
# ---------------------------------------------------------------------------

def _mount_at(mountinfo, mount_point):
    """(filesystem type, mount options) of what is mounted at *mount_point*,
    the last mount there being the one seen, or None."""
    found = None
    for line in (mountinfo or "").splitlines():
        fields = line.split()
        if len(fields) < 7 or fields[4] != mount_point or "-" not in fields[6:]:
            continue
        dash = fields.index("-", 6)
        if dash + 1 < len(fields):
            found = (fields[dash + 1], fields[5].split(","))
    return found


def _own_cgroup(text):
    """This process's cgroup v2 path, from ``/proc/self/cgroup``, or None."""
    for line in (text or "").splitlines():
        if line.startswith("0::"):
            return line[3:].strip()
    return None


def _namespace(kind):
    try:
        return os.stat(f"/proc/self/ns/{kind}").st_ino
    except OSError:
        return None


def _safe_read(path):
    try:
        return _read(path)
    except OSError:
        return None


def unavailable(*, root=ROOT, platform=None, euid=None, mountinfo=None,
                cgroup_namespace=None, pid_namespace=None, own_cgroup=None,
                controllers=None):
    """Why isolated nodes cannot get a cgroup limit here, as a key of
    :data:`REASONS`, or None when they can. Writes nothing.

    Every input is read from this process when not handed in. Nothing may be
    written where this says no: a sandbox started as root outside a container,
    in the host's cgroup namespace, would move every process of the host.
    """
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux"):
        return "no-linux"
    if (os.geteuid() if euid is None else euid) != 0:
        return "not-root"
    if mountinfo is None:
        mountinfo = _safe_read("/proc/self/mountinfo")
    mount = _mount_at(mountinfo, root)
    if mount is None or mount[0] != "cgroup2":
        return "no-cgroup2"
    if (_namespace("cgroup") if cgroup_namespace is None else cgroup_namespace) in (None, HOST_CGROUP_NAMESPACE):
        return "host-namespace"
    if (_namespace("pid") if pid_namespace is None else pid_namespace) in (None, HOST_PID_NAMESPACE):
        return "host-pid-namespace"
    if "rw" not in mount[1]:
        return "read-only"
    if own_cgroup is None:
        own_cgroup = _own_cgroup(_safe_read("/proc/self/cgroup"))
    if own_cgroup is None or own_cgroup.startswith("/.."):
        return "outside"
    if controllers is None:
        controllers = _safe_read(os.path.join(root, "cgroup.controllers"))
    if "memory" not in (controllers or "").split():
        return "no-memory"
    return None


_predicted = []


def predicted():
    """:func:`unavailable` for this process, asked once: what /version says
    in a process that laid nothing out, as the unit suites' app. The sandbox
    server lays out as it starts (``lifecycle.lay_out_at_start``) and says
    the outcome."""
    if not _predicted:
        _predicted.append(unavailable())
    return _predicted[0]


# ---------------------------------------------------------------------------
# The container's layout
# ---------------------------------------------------------------------------

def _move_every_process(root, servers):
    """Move every process in *root* to *servers*, again until none is left."""
    for _ in range(_LAYOUT_ATTEMPTS):
        pids = _read(os.path.join(root, "cgroup.procs")).split()
        if not pids:
            return
        for pid in pids:
            try:
                _write(os.path.join(servers, "cgroup.procs"), pid)
            except OSError as exc:
                # A process that exited meanwhile is not there to move.
                if exc.errno != errno.ESRCH:
                    raise


def lay_out(root=ROOT):
    """Move every process of the container to ``curio``, hand memory and pids
    to the root's children, and make ``nodes``. Raises OSError.

    Made once, as the sandbox starts (``lifecycle.lay_out_at_start``), and
    harmless again: a zygote started in a process that laid nothing out, as
    in the tests, finds it made. Only where :func:`unavailable` says nothing
    against it.
    """
    servers = os.path.join(root, SERVERS)
    nodes = os.path.join(root, NODES)
    _make(servers)
    wanted = _controllers(root)
    for attempt in range(_LAYOUT_ATTEMPTS):
        _move_every_process(root, servers)
        try:
            _enable(root, wanted)
            break
        except OSError as exc:
            # A process that started in the root after the move: once more.
            if exc.errno != errno.EBUSY or attempt == _LAYOUT_ATTEMPTS - 1:
                raise
    _make(nodes)
    _enable(nodes, _controllers(nodes))


def join(place):
    """Move this process into the cgroup *place*: what a child does first."""
    _write(os.path.join(place, "cgroup.procs"), "0")


# ---------------------------------------------------------------------------
# A zygote's places
# ---------------------------------------------------------------------------

class Place:
    """One run's cgroup, reused by the runs after it."""

    def __init__(self, path, memory_bytes):
        self.path = path
        self.memory_bytes = memory_bytes
        # The place's memory.peak, reset when its run began, where the kernel
        # resets it for one reader (6.12 and later).
        self.peak_fd = None
        self._ooms_before = 0

    def make(self):
        """The cgroup, at its budget: no swap, and every process in it
        stopped together when one is."""
        _make(self.path)
        _write(os.path.join(self.path, "memory.max"), self.memory_bytes)
        swap = os.path.join(self.path, "memory.swap.max")
        if os.path.exists(swap):
            _write(swap, 0)
        _write(os.path.join(self.path, "memory.oom.group"), 1)

    def hold(self, memory_bytes):
        """Set the place's budget to *memory_bytes*, the next run's."""
        if memory_bytes != self.memory_bytes:
            _write(os.path.join(self.path, "memory.max"), memory_bytes)
            self.memory_bytes = memory_bytes

    def begin(self):
        """Note where the place's counters stand as a run begins: the place is
        reused, and its counters count every run it held."""
        self._ooms_before = _events(self.path).get("oom", 0)
        self.peak_fd = _reset_peak(self.path)

    def kill(self):
        """Stop every process in the place: ``cgroup.kill`` (Linux 5.14), else
        each one of ``cgroup.procs``."""
        with contextlib.suppress(OSError):
            _write(os.path.join(self.path, "cgroup.kill"), 1)
            return
        with contextlib.suppress(OSError):
            for pid in _read(os.path.join(self.path, "cgroup.procs")).split():
                with contextlib.suppress(OSError):
                    os.kill(int(pid), signal.SIGKILL)

    def populated(self):
        """Whether a process is still in the place."""
        try:
            return "populated 1" in _read(os.path.join(self.path, "cgroup.events")).splitlines()
        except OSError:
            return False

    def outcome(self):
        """What the place says of the run that just ended: whether it reached
        its budget, and its peak where the kernel can say it."""
        return {
            "limit": CGROUP,
            "budget_hit": _events(self.path).get("oom", 0) > self._ooms_before,
            "peak_bytes": _read_peak(self.peak_fd),
        }

    def end(self):
        """The run is over: its reader of the peak goes."""
        if self.peak_fd is not None:
            with contextlib.suppress(OSError):
                os.close(self.peak_fd)
            self.peak_fd = None


def _reset_peak(path):
    """A reader of *path*'s ``memory.peak`` reset to what is in use now, or
    None. Kernel 6.12 resets it for the reader that writes to it; 6.8 refuses
    the write, and 5.15 has no such file."""
    try:
        fd = os.open(os.path.join(path, "memory.peak"), os.O_RDWR | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        os.write(fd, b"reset")
    except OSError:
        os.close(fd)
        return None
    return fd


def _read_peak(fd):
    if fd is None:
        return None
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 64).decode("ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return int(text) if text.isdigit() else None


def _is_zygote(pid):
    """Whether *pid* is a zygote that runs: a process whose command line
    names the zygote's module."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return _ZYGOTE_MODULE in handle.read()
    except FileNotFoundError:
        return False
    except OSError:
        # It runs, and this cannot read what it is: leave its places.
        return True


def _wait_empty(place, seconds):
    deadline = time.monotonic() + seconds
    while place.populated() and time.monotonic() < deadline:
        time.sleep(0.02)


def clear_dead(nodes, *, keep):
    """Remove the places of zygotes that have exited, each one's processes
    stopped first; *keep* is the pid of the zygote that asks."""
    try:
        names = os.listdir(nodes)
    except OSError:
        return
    for name in names:
        if not name.isdigit() or int(name) == keep or _is_zygote(int(name)):
            continue
        folder = os.path.join(nodes, name)
        try:
            places = [entry for entry in os.listdir(folder) if os.path.isdir(os.path.join(folder, entry))]
        except OSError:
            continue
        for entry in places:
            place = Place(os.path.join(folder, entry), 0)
            place.kill()
            _wait_empty(place, _CLEAR_WAIT_SECONDS)
            with contextlib.suppress(OSError):
                os.rmdir(place.path)
        with contextlib.suppress(OSError):
            os.rmdir(folder)


class Places:
    """One zygote's places, ``nodes/<its pid>/<k>``: made as runs need them,
    each taken again once nothing is left in it."""

    def __init__(self, memory_mb, *, root=ROOT, owner=None):
        self.memory_bytes = int(memory_mb) * MIB
        self.owner = os.getpid() if owner is None else owner
        nodes = os.path.join(root, NODES)
        clear_dead(nodes, keep=self.owner)
        self.folder = os.path.join(nodes, str(self.owner))
        _make(self.folder)
        _enable(self.folder, _controllers(self.folder))
        self._places = []
        self._free = []

    def take(self, memory_mb=None):
        """A place for the next run, emptied of the runs before it, at the
        run's budget, *memory_mb*, else this zygote's."""
        memory_bytes = int(memory_mb) * MIB if memory_mb else self.memory_bytes
        for place in self._free:
            if not place.populated():
                place.hold(memory_bytes)
                self._free.remove(place)
                place.begin()
                return place
        place = Place(os.path.join(self.folder, str(len(self._places))), memory_bytes)
        place.make()
        self._places.append(place)
        place.begin()
        return place

    def give_back(self, place):
        """*place*'s run is over; the next run may take it once it is empty."""
        place.end()
        if place not in self._free:
            self._free.append(place)

    def descriptors(self):
        """The readers of the places' peaks this zygote holds, which a child
        it forks closes."""
        return [place.peak_fd for place in self._places if place.peak_fd is not None]
