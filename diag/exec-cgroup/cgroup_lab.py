"""What a container may do with cgroups, for Curio's isolated nodes (a diagnostic).

Runs inside a container started for the probe. It writes nothing unless its
cgroup and pid namespaces are its own, not the host's, and /sys/fs/cgroup is a
read-write cgroup2 mount: then every write lands inside the container's own
cgroup. Each step prints one line, ``RESULT <json>``.

Layout it makes, as Curio would: every process of the container moves to
``/server``, the namespace root enables memory and pids for its children, and
each node runs in ``/nodes/<name>`` with its own memory.max.
"""

import argparse
import json
import os
import subprocess
import sys
import time

CG = "/sys/fs/cgroup"
SERVER = f"{CG}/server"
NODES = f"{CG}/nodes"
# The initial namespaces' inode numbers (PROC_CGROUP_INIT_INO, PROC_PID_INIT_INO).
INIT_CGROUP_NS = 0xEFFFFFFB
INIT_PID_NS = 0xEFFFFFFC
NOBODY = 65534
INTERFACE_FILES = (
    "memory.max", "memory.high", "memory.peak", "memory.reclaim", "memory.oom.group",
    "memory.swap.max", "memory.events", "memory.events.local", "cgroup.kill", "pids.max",
    "cgroup.freeze",
)


def emit(step, **data):
    print("RESULT " + json.dumps({"step": step, **data}, default=str), flush=True)


def read(path):
    try:
        with open(path) as handle:
            return handle.read().strip()
    except OSError as exc:
        return f"<errno {exc.errno} ({exc.strerror})>"


def write(path, value):
    try:
        with open(path, "w") as handle:
            handle.write(value)
        return "ok"
    except OSError as exc:
        return f"errno {exc.errno} ({exc.strerror})"


def keyed(text):
    out = {}
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        value = value.strip()
        if value.lstrip("-").isdigit():
            out[key] = int(value)
    return out


def ns_inode(kind):
    try:
        return os.stat(f"/proc/self/ns/{kind}").st_ino
    except OSError:
        return None


def cgroup_mount():
    with open("/proc/self/mountinfo") as handle:
        for line in handle:
            fields = line.split()
            if fields[4] == CG:
                dash = fields.index("-")
                return {"root": fields[3], "options": fields[5], "type": fields[dash + 1],
                        "super": fields[dash + 3]}
    return None


def unsafe():
    """Why this process must not write cgroups here, or None."""
    if ns_inode("cgroup") in (None, INIT_CGROUP_NS):
        return "the cgroup namespace is the host's"
    if ns_inode("pid") in (None, INIT_PID_NS):
        return "the pid namespace is the host's"
    mount = cgroup_mount()
    if not mount or mount["type"] != "cgroup2":
        return "no cgroup2 mount at /sys/fs/cgroup"
    if "rw" not in mount["options"].split(","):
        return "the cgroup mount is read-only"
    if read("/proc/self/cgroup").startswith("0::/.."):
        return "this process is outside its namespace's root"
    return None


def meminfo():
    out = {}
    with open("/proc/meminfo") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
                out[key + "_GiB"] = round(int(value.split()[0]) / 2**20, 1)
    return out


def usage(path):
    stat = keyed(read(f"{path}/memory.stat"))
    return {
        "events": keyed(read(f"{path}/memory.events")),
        "events.local": keyed(read(f"{path}/memory.events.local")),
        "peak": read(f"{path}/memory.peak"),
        "current": read(f"{path}/memory.current"),
        "anon": stat.get("anon"), "file": stat.get("file"), "shmem": stat.get("shmem"),
        "kernel": stat.get("kernel"), "file_mapped": stat.get("file_mapped"),
    }


def node(name, *, memory_max=None):
    """A node's cgroup: its memory.max, no swap, and the whole group killed on OOM."""
    path = f"{NODES}/{name}"
    if os.path.isdir(path):
        remove(path)
    os.mkdir(path)
    settings = {}
    if memory_max is not None:
        settings["memory.max"] = write(f"{path}/memory.max", str(memory_max))
    if os.path.exists(f"{path}/memory.swap.max"):
        settings["memory.swap.max"] = write(f"{path}/memory.swap.max", "0")
    settings["memory.oom.group"] = write(f"{path}/memory.oom.group", "1")
    return path, settings


def remove(path, timeout=15):
    """cgroup.kill, wait until nothing is left in it, then rmdir."""
    out = {}
    if os.path.exists(f"{path}/cgroup.kill"):
        out["kill"] = write(f"{path}/cgroup.kill", "1")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and "populated 1" in read(f"{path}/cgroup.events"):
        time.sleep(0.05)
    try:
        os.rmdir(path)
        out["rmdir"] = "ok"
    except OSError as exc:
        out["rmdir"] = f"errno {exc.errno} ({exc.strerror})"
    return out


def join_then(path, uid=None):
    """What a forked child does first: join *path* while still root, then drop."""
    def join():
        with open(f"{path}/cgroup.procs", "w") as handle:
            handle.write("0")
        if uid is not None:
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
    return join


def spawn(path, code, *, uid=None, env=None):
    return subprocess.Popen([sys.executable, "-c", code], preexec_fn=join_then(path, uid),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def facts(args):
    status = {}
    with open("/proc/self/status") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            if key in ("Seccomp", "NoNewPrivs", "CapEff"):
                status[key] = value.strip()
    data = {
        "uid": os.getuid(),
        "kernel": os.uname().release,
        "cpus": os.cpu_count(),
        "proc_self_cgroup": read("/proc/self/cgroup"),
        "cgroupns_is_host": ns_inode("cgroup") == INIT_CGROUP_NS,
        "pidns_is_host": ns_inode("pid") == INIT_PID_NS,
        "mount": cgroup_mount(),
        "apparmor": read("/proc/self/attr/current"),
        "status": status,
        "controllers": read(f"{CG}/cgroup.controllers"),
        "subtree_control": read(f"{CG}/cgroup.subtree_control"),
        "procs": read(f"{CG}/cgroup.procs").split(),
        "memory.max": read(f"{CG}/memory.max"),
        "memory.swap.max": read(f"{CG}/memory.swap.max"),
        "pids.max": read(f"{CG}/pids.max"),
        "memory.current": read(f"{CG}/memory.current"),
        "interface_files": [name for name in INTERFACE_FILES if os.path.exists(f"{CG}/{name}")],
        "meminfo": meminfo(),
        "unsafe_to_write": unsafe(),
    }
    if args.try_write:
        # Only in the container's own namespaces; on a read-only mount the
        # attempt itself is the answer.
        why = unsafe()
        if why not in (None, "the cgroup mount is read-only"):
            data["mkdir"] = f"not tried: {why}"
        else:
            probe = f"{CG}/diag-mkdir-probe"
            try:
                os.mkdir(probe)
                data["mkdir"] = "ok"
                os.rmdir(probe)
            except OSError as exc:
                data["mkdir"] = f"errno {exc.errno} ({exc.strerror})"
    emit("facts", **data)


def setup(args):
    """Every process to /server, then memory and pids for the root's children."""
    os.makedirs(SERVER, exist_ok=True)
    moved, failed = [], {}
    for _ in range(50):
        pids = [pid for pid in read(f"{CG}/cgroup.procs").split() if pid.isdigit()]
        if not pids:
            break
        for pid in pids:
            outcome = write(f"{SERVER}/cgroup.procs", pid)
            if outcome == "ok":
                moved.append(pid)
            else:
                failed[pid] = outcome
    wanted = [name for name in ("memory", "pids") if name in read(f"{CG}/cgroup.controllers").split()]
    enable_root = write(f"{CG}/cgroup.subtree_control", " ".join("+" + name for name in wanted))
    os.makedirs(NODES, exist_ok=True)
    enable_nodes = write(f"{NODES}/cgroup.subtree_control", " ".join("+" + name for name in wanted))
    emit("setup", moved=moved, failed=failed, left_in_root=read(f"{CG}/cgroup.procs").split(),
         enable_root=enable_root, root_subtree_control=read(f"{CG}/cgroup.subtree_control"),
         enable_nodes=enable_nodes, nodes_controllers=read(f"{NODES}/cgroup.controllers"),
         nodes_subtree_control=read(f"{NODES}/cgroup.subtree_control"),
         server_procs=read(f"{SERVER}/cgroup.procs").split(),
         self_cgroup=read("/proc/self/cgroup"))


NONROOT_CODE = r'''
import json, os
def w(path, value):
    try:
        with open(path, "w") as handle:
            handle.write(value)
        return "ok"
    except OSError as exc:
        return f"errno {exc.errno} ({exc.strerror})"
own = [line for line in open("/proc/self/cgroup").read().splitlines() if line.startswith("0::")][0][3:]
mine = "/sys/fs/cgroup" + own
out = {
    "uid": os.getuid(), "cgroup": own,
    "own memory.max": w(mine + "/memory.max", "max"),
    "own memory.oom.group": w(mine + "/memory.oom.group", "0"),
    "own cgroup.procs": w(mine + "/cgroup.procs", "0"),
    "server cgroup.procs (leave)": w("/sys/fs/cgroup/server/cgroup.procs", "0"),
    "nodes cgroup.procs (leave)": w("/sys/fs/cgroup/nodes/cgroup.procs", "0"),
    "root cgroup.procs (leave)": w("/sys/fs/cgroup/cgroup.procs", "0"),
    "own cgroup.kill": w(mine + "/cgroup.kill", "0"),
}
try:
    os.mkdir("/sys/fs/cgroup/nodes/escape")
    out["mkdir in nodes"] = "ok"
except OSError as exc:
    out["mkdir in nodes"] = f"errno {exc.errno} ({exc.strerror})"
print(json.dumps(out))
'''


def checks(args):
    """What container root may write at its namespace's root, and what a node's account may."""
    data = {}
    # The container's own limits, rewritten with the values they hold: nothing
    # changes even where the write is allowed, and an allowed write means root
    # in the container could raise them.
    for name in ("memory.max", "pids.max", "memory.swap.max", "memory.high"):
        current = read(f"{CG}/{name}")
        data[f"root {name} = {current}, rewritten"] = (
            current if current.startswith("<") else write(f"{CG}/{name}", current))
    path, settings = node("nonroot")
    proc = spawn(path, NONROOT_CODE, uid=NOBODY)
    out, err = proc.communicate(timeout=60)
    data["node settings"] = settings
    data["as nobody in its node cgroup"] = json.loads(out) if out.strip() else {"stderr": err[-800:]}
    data["nonroot remove"] = remove(path)
    if os.path.isdir(f"{NODES}/escape"):
        data["escape remove"] = remove(f"{NODES}/escape")
    path, settings = node("rootwrites", memory_max=64 << 20)
    data["root in a node: settings"] = settings
    data["root in a node: memory.reclaim"] = (
        write(f"{path}/memory.reclaim", "1M") if os.path.exists(f"{path}/memory.reclaim") else "absent")
    data["root in a node: memory.peak reset"] = write(f"{path}/memory.peak", "reset")
    data["rootwrites remove"] = remove(path)
    emit("checks", **data)


OOM_CODE = r'''
import subprocess, time
helper = subprocess.Popen(["sleep", "120"])
print("helper", helper.pid, flush=True)
time.sleep(0.5)
block = b"\x01" * %d
print("allocated and not killed", flush=True)
'''


def oom(args):
    """A node over its budget: is it, and only it, killed, and does memory.events say so?"""
    budget = args.budget_mb << 20
    sibling_path, _ = node("sibling", memory_max=budget)
    sibling = spawn(sibling_path, "import time; time.sleep(300)")
    path, settings = node("oom", memory_max=budget)
    started = time.monotonic()
    proc = spawn(path, OOM_CODE % (budget * 4))
    try:
        out, err = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    data = {
        "budget_mb": args.budget_mb, "settings": settings, "returncode": proc.returncode,
        "stdout": out[-300:], "stderr": err[-300:], "seconds": round(time.monotonic() - started, 2),
        "usage": usage(path), "procs_left": read(f"{path}/cgroup.procs").split(),
        "sibling_alive": sibling.poll() is None,
        "nodes events": keyed(read(f"{NODES}/memory.events")),
        "root events": keyed(read(f"{CG}/memory.events")),
        "root events.local": keyed(read(f"{CG}/memory.events.local")),
        "server events.local": keyed(read(f"{SERVER}/memory.events.local")),
    }
    data["remove"] = remove(path)
    sibling.kill()
    sibling.wait()
    data["sibling remove"] = remove(sibling_path)
    emit("oom", **data)


def dying(args):
    """Page cache a node made, after its cgroup goes: does a dying cgroup stay behind?"""
    size = args.mb << 20
    target = "/var/tmp/diag-cgroup-cache.bin"
    before = keyed(read(f"{NODES}/cgroup.stat"))
    path, _ = node("cache")
    code = (
        "import os\n"
        f"with open({target!r}, 'wb') as handle:\n"
        f"    handle.write(b'\\x01' * {size})\n"
        "    handle.flush()\n"
        "    os.fsync(handle.fileno())\n"
        f"with open({target!r}, 'rb') as handle:\n"
        "    while handle.read(1 << 24):\n"
        "        pass\n"
    )
    proc = spawn(path, code)
    out, err = proc.communicate(timeout=300)
    in_node = usage(path)
    removed = remove(path)
    samples = []
    start = time.monotonic()
    for mark in (0, 2, 10):
        while time.monotonic() - start < mark:
            time.sleep(0.1)
        samples.append({
            "t": mark,
            "nodes cgroup.stat": keyed(read(f"{NODES}/cgroup.stat")),
            "nodes file": keyed(read(f"{NODES}/memory.stat")).get("file"),
            "root file": keyed(read(f"{CG}/memory.stat")).get("file"),
        })
    os.unlink(target)
    time.sleep(2)
    unlinked = {
        "nodes cgroup.stat": keyed(read(f"{NODES}/cgroup.stat")),
        "nodes file": keyed(read(f"{NODES}/memory.stat")).get("file"),
    }
    emit("dying", mb=args.mb, returncode=proc.returncode, stderr=err[-300:], in_node=in_node,
         removed=removed, before=before, after_rmdir=samples, after_unlink=unlinked)


GPU_CODE = r'''
import ctypes, json, resource
out = {}
if %(rlimit_gib)d:
    with open("/proc/self/statm") as handle:
        size = int(handle.read().split()[0]) * 4096
    resource.setrlimit(resource.RLIMIT_AS, (size + (%(rlimit_gib)d << 30),) * 2)
    out["rlimit_as_gib"] = round((size + (%(rlimit_gib)d << 30)) / 2**30, 2)
cu = ctypes.CDLL("libcuda.so.1")
cu.cuMemAlloc_v2.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]
cu.cuMemGetInfo_v2.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
def call(name, *args):
    result = getattr(cu, name)(*args)
    out[name] = result
    return result == 0
dev = ctypes.c_int()
ctx = ctypes.c_void_p()
free = ctypes.c_size_t()
total = ctypes.c_size_t()
if (call("cuInit", 0) and call("cuDeviceGet", ctypes.byref(dev), 0)
        and call("cuDevicePrimaryCtxRetain", ctypes.byref(ctx), dev) and call("cuCtxSetCurrent", ctx)
        and call("cuMemGetInfo_v2", ctypes.byref(free), ctypes.byref(total))):
    want = min(%(gib)d << 30, free.value // 2)
    out.update(free_gib=round(free.value / 2**30, 2), total_gib=round(total.value / 2**30, 2),
               asked_gib=round(want / 2**30, 2))
    pointer = ctypes.c_uint64()
    out["cuMemAlloc_v2"] = cu.cuMemAlloc_v2(ctypes.byref(pointer), want)
with open("/proc/self/status") as handle:
    out["status"] = {line.split(":")[0]: line.split(":")[1].strip() for line in handle
                     if line.startswith(("VmPeak", "VmSize", "VmHWM", "VmRSS"))}
print(json.dumps(out))
'''


def gpu(args):
    """CUDA in a node capped at 1 GiB: does device memory count? Then under RLIMIT_AS instead."""
    data = {}
    for label, cap, rlimit in (("cgroup 1 GiB", 1 << 30, 0), ("RLIMIT_AS +4 GiB, no cgroup cap", None, 4)):
        path, settings = node("gpu", memory_max=cap)
        proc = spawn(path, GPU_CODE % {"gib": args.gib, "rlimit_gib": rlimit})
        try:
            out, err = proc.communicate(timeout=180)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
        try:
            seen = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            seen = {"stdout": out[-500:], "stderr": err[-800:]}
        data[label] = {"settings": settings, "returncode": proc.returncode, "seen": seen,
                       "usage": usage(path), "remove": remove(path)}
    emit("gpu", **data)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("facts").add_argument("--try-write", action="store_true")
    sub.add_parser("setup")
    sub.add_parser("checks")
    sub.add_parser("oom").add_argument("--budget-mb", type=int, default=128)
    sub.add_parser("dying").add_argument("--mb", type=int, default=256)
    sub.add_parser("gpu").add_argument("--gib", type=int, default=4)
    args = parser.parse_args()
    if args.command != "facts":
        why = unsafe()
        if why is None and args.command != "setup" and not os.path.isdir(NODES):
            why = "setup has not made /nodes"
        if why:
            emit(args.command, skipped=why)
            return
    {"facts": facts, "setup": setup, "checks": checks, "oom": oom, "dying": dying, "gpu": gpu}[args.command](args)


if __name__ == "__main__":
    main()
