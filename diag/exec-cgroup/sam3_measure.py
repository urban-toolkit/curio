"""Run sam3_node.py in a node cgroup and sample the cgroup's memory (a diagnostic).

    python3 sam3_measure.py <label> <memory.max in MB, 0 for none> [--rlimit-as-mb N] [--cold]

--cold first drops the walk's and the weights' pages from the page cache
(posix_fadvise DONTNEED, which leaves pages another process maps), so the node
reads them as a first run reads a bucket mount and fetched weights.
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cgroup_lab as lab  # noqa: E402


def drop_from_cache(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
    finally:
        os.close(fd)


def weights_folder(root):
    for folder, _dirs, files in os.walk(root):
        if "model.safetensors" in files and "config.json" in files:
            return folder
    raise SystemExit(f"no SAM 3 weights under {root}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("memory_max_mb", type=int)
    parser.add_argument("--rlimit-as-mb", type=int, default=0)
    parser.add_argument("--cold", action="store_true")
    args = parser.parse_args()
    why = lab.unsafe()
    if why or not os.path.isdir(lab.NODES):
        lab.emit("sam3", label=args.label, skipped=why or "setup has not made /nodes")
        return
    weights = weights_folder("/model-weights")
    video = "/video/video.mp4"
    if args.cold:
        for path in (video, os.path.join(weights, "model.safetensors")):
            drop_from_cache(path)
    path, settings = lab.node("sam3-" + args.label,
                              memory_max=(args.memory_max_mb << 20) if args.memory_max_mb else None)
    env = dict(os.environ, DIAG_VIDEO=video, DIAG_WEIGHTS=weights,
               DIAG_PACKAGE_SOURCES=os.environ.get("DIAG_PACKAGE_SOURCES",
                                                   "/app/packages/model.curio.sam3@1/sources"),
               DIAG_RLIMIT_AS_MB=str(args.rlimit_as_mb or ""))
    peaks = {}
    stop = threading.Event()

    def sample():
        while not stop.is_set():
            stat = lab.keyed(lab.read(f"{path}/memory.stat"))
            current = lab.read(f"{path}/memory.current")
            values = dict(stat, current=int(current) if current.isdigit() else 0)
            for key in ("current", "anon", "file", "shmem", "kernel", "file_mapped", "sock"):
                peaks[key] = max(peaks.get(key, 0), values.get(key, 0))
            stop.wait(0.2)

    sampler = threading.Thread(target=sample, daemon=True)
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-u", os.path.join(os.path.dirname(__file__), "sam3_node.py")],
                            preexec_fn=lab.join_then(path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env, cwd="/tmp")
    sampler.start()
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        print(f"[{args.label}] {line}", flush=True)
        tail = (tail + [line])[-60:]
    proc.wait()
    stop.set()
    sampler.join()
    data = {
        "label": args.label, "memory_max_mb": args.memory_max_mb, "rlimit_as_mb": args.rlimit_as_mb,
        "cold": args.cold, "settings": settings, "returncode": proc.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "usage": lab.usage(path),
        "sampled_peaks_GiB": {key: round(value / 2**30, 3) for key, value in peaks.items()},
        "tail": [line for line in tail if line.startswith(("DONE", "FAILED", "MARK"))][-12:],
    }
    data["remove"] = lab.remove(path)
    lab.emit("sam3", **data)


if __name__ == "__main__":
    main()
