"""Diagnostic only: what glibc's thresholds cost allocation-heavy node code.

Allocates and touches numpy temporaries of 256 KiB to 2 MiB in a loop, the
sizes a fixed mmap threshold moves off the heap, then runs a pandas groupby
and merge on a million rows. Prints one JSON line of seconds. The thresholds
come from the environment this process starts with.
"""

import json
import os
import threading
import time

import numpy as np
import pandas as pd


def temporaries(kib, reps):
    n = kib * 1024 // 8
    started = time.perf_counter()
    total = 0.0
    for _ in range(reps):
        block = np.empty(n)
        block.fill(1.0)
        total += float(block[::512].sum())
    return time.perf_counter() - started


def threaded(kib, reps, threads=4):
    done = []

    def work():
        done.append(temporaries(kib, reps))

    started = time.perf_counter()
    workers = [threading.Thread(target=work) for _ in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return time.perf_counter() - started


def frames():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"k": rng.integers(0, 1000, 1_000_000), "v": rng.random(1_000_000)})
    started = time.perf_counter()
    for _ in range(15):
        means = df.groupby("k")["v"].mean().rename("m")
        merged = df.merge(means, left_on="k", right_index=True)
        merged["d"] = merged["v"] - merged["m"]
    return time.perf_counter() - started


def main():
    out = {"env": {k: os.environ.get(k) for k in (
        "MALLOC_ARENA_MAX", "MALLOC_MMAP_THRESHOLD_", "MALLOC_TRIM_THRESHOLD_")}}
    for kib in (256, 512, 1024, 2048):
        out[f"numpy_{kib}k"] = round(temporaries(kib, 6000), 3)
    out["numpy_1024k_4threads"] = round(threaded(1024, 1500), 3)
    out["pandas"] = round(frames(), 3)
    print("BENCH " + json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
