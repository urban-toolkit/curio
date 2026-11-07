"""Check that test-isolated's stack runs node code on the job's library threads.

Torch, OpenBLAS and the other OpenMP libraries start a thread per CPU they see.
An arcade CPU runner shows all 192 CPUs of a machine its 44 runners share, so
on run 42230248452 example 28's training, at load 490 to 574, ran until the
sandbox stopped it at 300 s. The job hands its stack the runner's share,
``CURIO_CI_LIBRARY_THREADS``, as ``OMP_NUM_THREADS``. This runs a node in an
isolated child of that stack and fails unless the child got that count and
torch there uses no more. Torch may use fewer: its x86 build sizes its pool
through MKL, which counts physical cores, 2 on a 4-CPU hosted runner.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import urllib.request

NODE = """import json, os, sys, torch
print("THREADS " + json.dumps({
    "torch": torch.get_num_threads(), "omp": os.environ.get("OMP_NUM_THREADS"), "cpus": os.cpu_count(),
}), file=sys.stderr)
return 1
"""


def child_threads() -> dict:
    """What an isolated child of the stack sees, from its stderr."""
    request = urllib.request.Request(
        f"http://localhost:{os.environ['CURIO_E2E_SANDBOX_PORT']}/exec",
        data=json.dumps({
            "code": textwrap.indent(NODE, "    "),
            "file_path": "",
            "nodeType": "curio.builtin/python-computation",
            "dataType": "",
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Curio-Sandbox-Token": os.environ.get("CURIO_SANDBOX_TOKEN", ""),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
        answer = json.loads(response.read().decode("utf-8"))
    for line in (answer.get("stderr") or "").splitlines():
        if line.startswith("THREADS "):
            return json.loads(line[len("THREADS "):])
    raise SystemExit(f"::error::the isolated child reported nothing: {answer}")


def main() -> int:
    seen = child_threads()
    print(f"An isolated child sees {seen['cpus']} CPUs and OMP_NUM_THREADS={seen['omp']}; "
          f"torch uses {seen['torch']} threads.")
    wanted = os.environ.get("CURIO_CI_LIBRARY_THREADS")
    if not wanted:
        print("::error::the job handed its stack no library thread count (CURIO_CI_LIBRARY_THREADS)")
        return 1
    if seen["omp"] != wanted:
        print(f"::error::an isolated child got OMP_NUM_THREADS={seen['omp']}, not the job's {wanted}")
        return 1
    if seen["torch"] > int(wanted):
        print(f"::error::torch in an isolated child uses {seen['torch']} threads, more than the job's {wanted}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
