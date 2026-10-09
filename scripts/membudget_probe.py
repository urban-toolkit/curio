"""Probe for #376: why a forked, memory-capped child fails its first Arrow allocation.

Diagnostic only, on the diag/memory-budgets-376 branch. Runs inside the CI
stack's container. Starts a zygote per budget and environment the way the
``isolated`` fixture in test_isolation_linux.py does, and runs small nodes
that report the child's address space around one allocation.
"""
import json
import os
import shutil
import sys
import tempfile
import time

try:
    import pyseccomp  # noqa: F401

    HAS_PYSECCOMP = True
except Exception:
    HAS_PYSECCOMP = False

NODE = """
    import json, mmap, os, resource
    def status():
        out = {}
        with open('/proc/self/status') as h:
            for line in h:
                key, _, value = line.partition(':')
                if key in ('VmSize', 'VmPeak', 'VmRSS'):
                    out[key] = int(value.split()[0]) // 1024
                elif key == 'Threads':
                    out[key] = int(value)
        return out
    def maps():
        out = {}
        with open('/proc/self/maps') as h:
            for line in h:
                parts = line.split()
                lo, hi = (int(x, 16) for x in parts[0].split('-'))
                out[lo] = (hi - lo, parts[1], parts[5] if len(parts) > 5 else '')
        return out
    report = {'cap_mb': resource.getrlimit(resource.RLIMIT_AS)[0] // (1024 * 1024)}
    report['start'] = status()
    keep = None
    target = PAD_TARGET
    if target is not None:
        pad_mb = report['cap_mb'] - report['start']['VmSize'] - target
        report['pad_mb'] = pad_mb
        if pad_mb > 0:
            keep = mmap.mmap(-1, pad_mb * 1024 * 1024)
    report['before'] = status()
    before = maps()
    try:
ACTION
        report['ok'] = True
    except BaseException as exc:
        report['ok'] = False
        report['error'] = repr(exc)[:160]
    report['after'] = status()
    grown = []
    for lo, (size, perms, name) in maps().items():
        if before.get(lo, (None,))[0] != size:
            grown.append((size // 1024, perms, name[-50:]))
    grown.sort(reverse=True)
    report['new_maps_kb'] = grown[:5]
    import pyarrow as pa
    report['pool'] = pa.default_memory_pool().backend_name
    print('MEMBUDGET ' + json.dumps(report))
    return 0
"""

ACTIONS = {
    "frame": "        import pandas as pd\n        pd.DataFrame({'a': [1, 2, 3], 'b': ['x', 'y', 'z']})",
    "alloc-default": "        import pyarrow as pa\n        pa.allocate_buffer(64)",
    "alloc-system": "        import pyarrow as pa\n        pa.allocate_buffer(64, memory_pool=pa.system_memory_pool())",
    "alloc-jemalloc": "        import pyarrow as pa\n        pa.allocate_buffer(64, memory_pool=pa.jemalloc_memory_pool())",
    "alloc-mimalloc": "        import pyarrow as pa\n        pa.allocate_buffer(64, memory_pool=pa.mimalloc_memory_pool())",
}


def node(action, pad_target=None):
    return NODE.replace("ACTION", ACTIONS[action]).replace("PAD_TARGET", repr(pad_target))


def facts():
    import numpy
    import pandas as pd
    import pyarrow as pa

    print("python", sys.version.split()[0], "pandas", pd.__version__, "pyarrow", pa.__version__,
          "numpy", numpy.__version__, "cpus", os.cpu_count(), "seccomp", HAS_PYSECCOMP)
    print("arrow backends", pa.supported_memory_backends(),
          "default in this process", pa.default_memory_pool().backend_name)
    print("pandas infer_string", pd.get_option("future.infer_string"))
    for path in ("/proc/sys/vm/overcommit_memory", "/proc/sys/vm/max_map_count"):
        with open(path) as h:
            print(path, h.read().strip())
    with open("/proc/meminfo") as h:
        for line in h:
            if line.split(":")[0] in ("MemTotal", "MemAvailable", "CommitLimit", "Committed_AS"):
                print(line.strip())
    print("env", {k: v for k, v in os.environ.items()
                  if k.startswith(("ARROW", "MALLOC", "JE_", "MIMALLOC", "CURIO_EXEC"))})
    sys.stdout.flush()


def row(budget, extra, label, rep):
    before = rep["before"]["VmSize"]
    return (
        f"budget={budget:<5} env={','.join(f'{k}={v}' for k, v in extra.items()) or '-':<44} "
        f"node={label:<14} ok={str(rep['ok']):<5} pool={rep['pool']:<8} cap={rep['cap_mb']:<5} "
        f"free_before={rep['cap_mb'] - before:<5} pad={rep.get('pad_mb', '-')!s:<5} "
        f"vm={before}->{rep['after']['VmSize']} peak={rep['after']['VmPeak']} "
        f"threads={rep['after'].get('Threads')} new_kb={rep['new_maps_kb'][:3]} "
        f"err={rep.get('error', '')}"
    )


def run(budget, extra, nodes):
    workspace = tempfile.mkdtemp(prefix="membudget-")
    saved = dict(os.environ)
    os.environ.update({
        "CURIO_LAUNCH_CWD": workspace,
        "CURIO_SHARED_DATA": os.path.join(workspace, "data"),
        "CURIO_EXEC_SOCKET": os.path.join(workspace, "zygote.sock"),
        "CURIO_EXEC_TIMEOUT": "20",
        "CURIO_EXEC_MEMORY_MB": str(budget),
    })
    os.environ.update(extra)
    from utk_curio.sandbox.isolation import lifecycle, runner
    from utk_curio.sandbox.util.db import init_db, release_connection

    release_connection()
    init_db()
    started = time.time()
    try:
        config = runner.IsolationConfig.from_environment()
        lifecycle.ensure_running(config, exec_user=None, require_seccomp=HAS_PYSECCOMP)
        print(f"-- zygote budget={budget} env={extra} up in {time.time() - started:.1f}s")
        for label, code in nodes:
            result = runner.execute_isolated(
                code, "", "curio.builtin/computation-analysis", "",
                save_dataset=False, config=config,
            )
            lines = [line for line in result.get("stdout") or [] if line.startswith("MEMBUDGET ")]
            if lines:
                print(row(budget, extra, label, json.loads(lines[-1][len("MEMBUDGET "):])))
            else:
                print(f"budget={budget} env={extra} node={label} NO REPORT "
                      f"stderr={(result.get('stderr') or '')[-600:]!r}")
            sys.stdout.flush()
    except Exception as exc:  # noqa: BLE001 - a probe reports and goes on
        print(f"budget={budget} env={extra} zygote failed: {exc!r}")
    finally:
        lifecycle.shutdown()
        release_connection()
        os.environ.clear()
        os.environ.update(saved)
        shutil.rmtree(workspace, ignore_errors=True)


def main():
    facts()
    every = [(name, node(name)) for name in ACTIONS]
    print("== 1. budgets, default environment, each allocator first-used in a fresh child")
    for budget in (128, 192, 256, 384, 512, 768, 1024, 1536, 2048, 4096):
        run(budget, {}, every)

    print("== 2. the test's frame under each pool, chosen in the zygote's environment")
    frame = [("frame", node("frame"))]
    for budget in (128, 256, 1024):
        for extra in (
            {"ARROW_DEFAULT_MEMORY_POOL": "system"},
            {"ARROW_DEFAULT_MEMORY_POOL": "jemalloc"},
            {"ARROW_DEFAULT_MEMORY_POOL": "mimalloc", "MIMALLOC_SHOW_ERRORS": "1"},
            {"JE_ARROW_MALLOC_CONF": "retain:false"},
            {"JE_ARROW_MALLOC_CONF": "background_thread:false"},
            {"MIMALLOC_ARENA_RESERVE": "0", "MIMALLOC_SHOW_ERRORS": "1"},
        ):
            run(budget, extra, frame)

    print("== 3. headroom sweep at a 4096 MB budget: pad the child down to N MB free first")
    sweep = []
    for target in (32, 64, 96, 128, 160, 192, 224, 256, 320, 384, 512, 640, 768, 896,
                   960, 1008, 1024, 1040, 1072, 1152, 1280, 1536, 2048, 3072):
        sweep.append((f"frame@{target}", node("frame", target)))
    run(4096, {}, sweep)
    run(4096, {"ARROW_DEFAULT_MEMORY_POOL": "system"}, sweep)
    print("== done")


if __name__ == "__main__":
    main()
