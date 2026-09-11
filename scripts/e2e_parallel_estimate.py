#!/usr/bin/env python3
"""Estimate the parallel-e2e speedup from STRATIFIED SAMPLE runs.

The full serial suite takes ~2.5h on a Windows dev box, so the Stage 1 gate is
priced from two sample runs instead:

    phase A  test_workflows.py, a few whole workflow groups (4 tests each)
    phase B  a few whole files, chosen to cover both strata

Phase B is stratified because its per-test cost is bimodal: test_examples,
test_example_docs_parity and test_agent_runs_e2e never touch a browser (zero
`page` references) and are ~an order of magnitude cheaper than the rest, so
scaling phase B by test count alone badly overestimates it.

Extrapolation, stated plainly:
    total_A = mean(non-GPU group) * n_nonGPU_groups + mean(GPU group) * n_GPU_groups
    total_B = mean(structural per-test) * n_structural + mean(browser per-test) * n_browser

The makespan is computed on a synthetic population built by TILING the measured
group times (not by using their mean), so real variance is preserved rather than
flattened into an optimistic perfectly-balanced set.

Usage:
    python scripts/e2e_parallel_estimate.py e2e-A-sample.xml e2e-B-sample.xml
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_shard_plan import _GPU_RE, _fmt, _module_and_param, lpt_makespan  # noqa: E402

#: Phase B files with zero `page`/`app_frontend`/`workflow_page` references.
#: Measured, not guessed: grep over test_frontend/*.py.
STRUCTURAL_MODULES = {
    "test_example_docs_parity",
    "test_examples",
    "test_agent_runs_e2e",
}


def _cases(path: str):
    """(module, param, seconds) per non-skipped testcase."""
    for case in ET.parse(path).getroot().iter("testcase"):
        if case.find("skipped") is not None:
            continue
        module, param = _module_and_param(case.get("classname") or "", case.get("name") or "")
        yield module, param, float(case.get("time") or 0.0)


def _tile(values: list[float], n: int) -> list[float]:
    """n weights drawn cyclically from `values`, preserving its variance."""
    if not values:
        return []
    return [values[i % len(values)] for i in range(n)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase_a_xml")
    ap.add_argument("phase_b_xml")
    # Population, measured from --collect-only. Defaults are this repo's numbers.
    ap.add_argument("--groups-nongpu", type=int, default=21,
                    help="running non-AUTK workflow groups (default 21)")
    ap.add_argument("--groups-gpu", type=int, default=9,
                    help="running AUTK/WebGPU workflow groups (default 9)")
    ap.add_argument("--phaseb-structural", type=int, default=91,
                    help="phase B tests in browser-free modules (default 91)")
    ap.add_argument("--phaseb-browser", type=int, default=192,
                    help="phase B tests that drive a browser (default 192)")
    ap.add_argument("--max-workers", type=int, default=8)
    args = ap.parse_args(argv)

    # ---- phase A: group the sample by workflow ----
    groups: dict[str, float] = collections.defaultdict(float)
    gcount: dict[str, int] = collections.defaultdict(int)
    for module, param, secs in _cases(args.phase_a_xml):
        if not param:
            continue
        groups[param] += secs
        gcount[param] += 1

    gpu = {g: t for g, t in groups.items() if _GPU_RE.search(g)}
    nongpu = {g: t for g, t in groups.items() if not _GPU_RE.search(g)}
    if not gpu or not nongpu:
        print("sample must include at least one AUTK and one non-AUTK workflow",
              file=sys.stderr)
        return 1

    mean_gpu = sum(gpu.values()) / len(gpu)
    mean_nongpu = sum(nongpu.values()) / len(nongpu)
    total_a = mean_nongpu * args.groups_nongpu + mean_gpu * args.groups_gpu

    # ---- phase B: split the sample into the two strata ----
    struct, browser = [], []
    for module, _param, secs in _cases(args.phase_b_xml):
        (struct if module in STRUCTURAL_MODULES else browser).append(secs)
    if not struct or not browser:
        print("phase B sample must cover both strata", file=sys.stderr)
        return 1

    mean_struct = sum(struct) / len(struct)
    mean_browser = sum(browser) / len(browser)
    total_b = mean_struct * args.phaseb_structural + mean_browser * args.phaseb_browser
    total = total_a + total_b

    print("\n=== measured sample ===")
    print(f"phase A  {len(groups)} workflow groups, {sum(gcount.values())} tests")
    for g, t in sorted(groups.items(), key=lambda kv: -kv[1]):
        print(f"    {_fmt(t):>8}  {gcount[g]}t  {g}{'  [GPU]' if _GPU_RE.search(g) else ''}")
    print(f"    mean non-AUTK group {_fmt(mean_nongpu)}   mean AUTK group {_fmt(mean_gpu)}")
    print(f"phase B  {len(struct)} structural tests (mean {mean_struct:5.1f}s), "
          f"{len(browser)} browser tests (mean {mean_browser:5.1f}s)")

    print("\n=== extrapolated population ===")
    print(f"phase A  {args.groups_nongpu} non-AUTK + {args.groups_gpu} AUTK groups"
          f"  -> {_fmt(total_a)}  ({total_a / total:.1%})")
    print(f"phase B  {args.phaseb_structural} structural + {args.phaseb_browser} browser"
          f"  -> {_fmt(total_b)}  ({total_b / total:.1%})")
    print(f"serial total (est.)  {_fmt(total)}")

    per_wf = _tile(sorted(nongpu.values()), args.groups_nongpu) + \
        _tile(sorted(gpu.values()), args.groups_gpu)
    gpu_sum = sum(_tile(sorted(gpu.values()), args.groups_gpu))
    collapsed = _tile(sorted(nongpu.values()), args.groups_nongpu) + [gpu_sum]

    print(f"\n=== projected total = makespan(phase A) + {_fmt(total_b)} serial phase B ===")
    print(f"{'N':>3}  {'per-workflow groups':>25}  {'AUTK collapsed (1 GPU browser)':>32}")
    print(f"{'':>3}  {'makespan   total  speedup':>25}  {'makespan   total  speedup':>32}")
    verdict4 = None
    for n in range(1, args.max_workers + 1):
        m1, m2 = lpt_makespan(per_wf, n), lpt_makespan(collapsed, n)
        s1, s2 = total / (m1 + total_b), total / (m2 + total_b)
        if n == 4:
            verdict4 = (s1, s2)
        print(f"{n:>3}  {_fmt(m1):>9} {_fmt(m1 + total_b):>7} {s1:6.2f}x"
              f"  {_fmt(m2):>14} {_fmt(m2 + total_b):>7} {s2:6.2f}x")

    print(f"\nphase A serial floor: largest group {_fmt(max(per_wf))}; "
          f"AUTK collapsed {_fmt(gpu_sum)}")
    print(f"phase B is the Amdahl floor at {_fmt(total_b)} -- no worker count beats it.")
    print(f"\nGATE (>= 2.00x at N=4): per-workflow {verdict4[0]:.2f}x "
          f"{'PASS' if verdict4[0] >= 2 else 'FAIL'}"
          f"   AUTK-collapsed {verdict4[1]:.2f}x "
          f"{'PASS' if verdict4[1] >= 2 else 'FAIL'}")
    print("\nAssumptions: unmeasured groups take their stratum's measured mean; "
          "makespan\ntiles measured times to preserve variance; phase B scales "
          "per-test within stratum.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
