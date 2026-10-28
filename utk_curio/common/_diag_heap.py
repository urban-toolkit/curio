"""Diagnostic only, branch diag/repeat-pass-memory: what a server process
holds, every CURIO_DIAG_HEAP_EVERY seconds (default 120), as JSON lines in
CURIO_DIAG_HEAP_DIR/<role>-<pid>.jsonl. Off unless CURIO_DIAG_HEAP_DIR is set."""

import collections
import ctypes
import gc
import json
import os
import re
import sys
import threading
import time


class _Mallinfo2(ctypes.Structure):
    _fields_ = [(name, ctypes.c_size_t) for name in (
        "arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks",
        "uordblks", "fordblks", "keepcost")]


def _mallinfo():
    try:
        call = ctypes.CDLL(None).mallinfo2
    except (AttributeError, OSError):
        return None
    call.restype = _Mallinfo2
    info = call()
    return {name: getattr(info, name) for name, _ in _Mallinfo2._fields_}


def _status():
    out = {}
    try:
        text = open("/proc/self/status").read()
    except OSError:
        return out
    for key in ("VmRSS", "RssAnon", "RssFile", "RssShmem", "Threads"):
        match = re.search(rf"^{key}:\s+(\d+)", text, re.MULTILINE)
        if match:
            out[key] = int(match.group(1))
    return out


def _sample(role):
    record = {"t": int(time.time()), "role": role, "pid": os.getpid(),
              "status": _status(), "malloc": _mallinfo(),
              "blocks": sys.getallocatedblocks(), "modules": len(sys.modules)}
    names = collections.Counter(re.sub(r"\d+", "N", t.name) for t in threading.enumerate())
    record["threads"] = names.most_common(12)
    arrow = sys.modules.get("pyarrow")
    if arrow is not None:
        try:
            record["arrow"] = arrow.total_allocated_bytes()
            record["arrow_pool"] = arrow.default_memory_pool().backend_name
        except Exception:  # noqa: BLE001
            pass
    started = time.perf_counter()
    counts = collections.Counter()
    for obj in gc.get_objects():
        kind = type(obj)
        counts[f"{kind.__module__}.{kind.__qualname__}"] += 1
    record["types"] = counts.most_common(40)
    record["objects"] = sum(counts.values())
    record["census_s"] = round(time.perf_counter() - started, 3)
    return record


def start_if_asked(role):
    folder = os.environ.get("CURIO_DIAG_HEAP_DIR")
    if not folder:
        return
    every = float(os.environ.get("CURIO_DIAG_HEAP_EVERY") or 120)
    port = os.environ.get("BACKEND_PORT" if role == "backend" else "SANDBOX_PORT", "")
    path = os.path.join(folder, f"{role}{port}-{os.getpid()}.jsonl")

    def loop():
        os.makedirs(folder, exist_ok=True)
        while True:
            try:
                line = json.dumps(_sample(role), separators=(",", ":"))
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except Exception as exc:  # noqa: BLE001
                print(f"[diag-heap] {exc}", file=sys.stderr, flush=True)
            time.sleep(every)

    threading.Thread(target=loop, name="diag-heap", daemon=True).start()
