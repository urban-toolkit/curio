#!/usr/bin/env python3
"""Price parallelising the e2e suite, from a serial run's junit XML.

Read-only. Answers the one question that decides whether ``--parallel`` is worth
building: what share of the wall clock does ``test_workflows.py`` actually own?

The plan splits the suite into two phases against one stack, because the other
test files truncate ``user``/``project``/``user_session`` globally between every
test and would delete a workflow test's logged-in user mid-run:

    phase A   test_workflows.py            parallel, N workers, --dist loadgroup
    phase B   everything else              serial

so ``total(N) = makespan_A(N) + total_B`` and phase B is the Amdahl floor.

Usage:
    python -m pytest tests/test_frontend/ --junitxml=e2e-timings.xml   # serial
    python scripts/e2e_shard_plan.py e2e-timings.xml
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
import xml.etree.ElementTree as ET

# Workflows whose nodes drive hardware WebGPU. Grouping them together forces
# loadgroup to run them on one worker, so at most one WebGPU Chromium exists at
# a time -- the free mitigation for GPU contention, priced below.
_GPU_RE = re.compile(r"autk|autark", re.IGNORECASE)

_PARAM_RE = re.compile(r"\[(.+)\]$")


def _module_and_param(classname: str, name: str) -> tuple[str, str | None]:
    """('test_workflows', 'Vega.json') for a parametrized TestWorkflowCanvas case."""
    module = ""
    for part in classname.split("."):
        if part.startswith("test_"):
            module = part
    m = _PARAM_RE.search(name)
    return module, (m.group(1) if m else None)


def _group_key(classname: str, name: str) -> tuple[str, str]:
    """(phase, group). Phase 'A' is test_workflows.py; 'B' is everything else."""
    module, param = _module_and_param(classname, name)
    if module == "test_workflows" and param:
        return "A", f"wf-{param}"
    return "B", module or "unknown"


def load(path: str) -> list[tuple[str, str, str, float]]:
    """[(phase, group, nodeid, seconds)] for every non-skipped testcase."""
    rows = []
    for case in ET.parse(path).getroot().iter("testcase"):
        # A skipped case contributes no wall clock and would deflate a group.
        if case.find("skipped") is not None:
            continue
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        phase, group = _group_key(classname, name)
        rows.append((phase, group, f"{classname}::{name}", float(case.get("time") or 0.0)))
    return rows


def lpt_makespan(weights: list[float], workers: int) -> float:
    """Longest-processing-time bin packing. Groups are atomic; xdist hands the
    next group to whichever worker frees up first, which is what LPT models."""
    if workers <= 1:
        return sum(weights)
    loads = [0.0] * workers
    for w in sorted(weights, reverse=True):
        i = min(range(workers), key=lambda k: loads[k])
        loads[i] += w
    return max(loads)


def _fmt(seconds: float) -> str:
    return f"{int(seconds) // 60:d}m{int(seconds) % 60:02d}s"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("junit_xml")
    ap.add_argument("--max-workers", type=int, default=8)
    ap.add_argument("--top", type=int, default=15, help="groups to list (default 15)")
    args = ap.parse_args(argv)

    rows = load(args.junit_xml)
    if not rows:
        print(f"no non-skipped testcases in {args.junit_xml}", file=sys.stderr)
        return 1

    groups: dict[tuple[str, str], float] = collections.defaultdict(float)
    counts: dict[tuple[str, str], int] = collections.defaultdict(int)
    for phase, group, _nodeid, secs in rows:
        groups[(phase, group)] += secs
        counts[(phase, group)] += 1

    a = {g: t for (p, g), t in groups.items() if p == "A"}
    b = {g: t for (p, g), t in groups.items() if p == "B"}
    total_a, total_b = sum(a.values()), sum(b.values())
    total = total_a + total_b

    print(f"\n=== {args.junit_xml} ===")
    print(f"{len(rows)} tests ran, {_fmt(total)} of measured test time\n")
    print(f"  phase A  test_workflows.py        {_fmt(total_a):>8}  "
          f"{total_a / total:5.1%}  {sum(counts[k] for k in groups if k[0]=='A'):3d} tests  "
          f"{len(a)} groups")
    print(f"  phase B  everything else          {_fmt(total_b):>8}  "
          f"{total_b / total:5.1%}  {sum(counts[k] for k in groups if k[0]=='B'):3d} tests  "
          f"{len(b)} files")

    print(f"\n--- phase A groups, slowest {args.top} ---")
    for group, secs in sorted(a.items(), key=lambda kv: -kv[1])[: args.top]:
        gpu = " [GPU]" if _GPU_RE.search(group) else ""
        print(f"  {_fmt(secs):>8}  {counts[('A', group)]}t  {group}{gpu}")

    print(f"\n--- phase B files, slowest {args.top} ---")
    for group, secs in sorted(b.items(), key=lambda kv: -kv[1])[: args.top]:
        print(f"  {_fmt(secs):>8}  {counts[('B', group)]}t  {group}")

    # Two groupings: per-workflow (max parallelism, N WebGPU Chromiums at once)
    # and AUTK-collapsed (one WebGPU Chromium at a time, longer critical path).
    per_wf = list(a.values())
    gpu_total = sum(t for g, t in a.items() if _GPU_RE.search(g))
    collapsed = [t for g, t in a.items() if not _GPU_RE.search(g)]
    if gpu_total:
        collapsed.append(gpu_total)

    print(f"\n--- projected total = makespan(phase A) + {_fmt(total_b)} serial phase B ---")
    print(f"{'N':>3}  {'per-workflow groups':>24}  {'AUTK collapsed to one group':>29}")
    print(f"{'':>3}  {'makespan   total  speedup':>24}  {'makespan   total  speedup':>29}")
    for n in range(1, args.max_workers + 1):
        m1 = lpt_makespan(per_wf, n)
        m2 = lpt_makespan(collapsed, n)
        print(f"{n:>3}  {_fmt(m1):>8} {_fmt(m1 + total_b):>7} {total / (m1 + total_b):6.2f}x"
              f"  {_fmt(m2):>11} {_fmt(m2 + total_b):>7} {total / (m2 + total_b):6.2f}x")

    print(f"\n  phase A serial floor (longest group): "
          f"per-workflow {_fmt(max(per_wf))}, AUTK-collapsed {_fmt(max(collapsed))}")
    if gpu_total:
        print(f"  AUTK/GPU workflows total {_fmt(gpu_total)} "
              f"({gpu_total / total_a:.1%} of phase A) across "
              f"{sum(1 for g in a if _GPU_RE.search(g))} workflows")
    print("\n  Gate: 4 workers must buy >= 2.00x overall, or re-scope to making the "
          "slowest\n  workflows faster instead of adding workers.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
