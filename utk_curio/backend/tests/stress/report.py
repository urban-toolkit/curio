"""Turn a run's samples into numbers a reader can act on.

Two outputs: ``report.json`` for later comparison between runs, and a markdown
summary for the CI step summary. Both answer the same three questions -- what
broke, how slow did it get, and how close to a resource ceiling did the stack
come.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from .driver import FAILURE_KINDS, UserResult


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Empty input gives 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(round(pct / 100.0 * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def endpoint_stats(results: list[UserResult]) -> dict[str, dict]:
    by_endpoint: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    for result in results:
        for sample in result.samples:
            by_endpoint.setdefault(sample.endpoint, []).append(sample.seconds)
            if not sample.ok:
                errors[sample.endpoint] = errors.get(sample.endpoint, 0) + 1
    return {
        endpoint: {
            "calls": len(times),
            "errors": errors.get(endpoint, 0),
            "p50_s": round(percentile(times, 50), 2),
            "p95_s": round(percentile(times, 95), 2),
            "max_s": round(max(times), 2),
        }
        for endpoint, times in sorted(by_endpoint.items())
    }


def exec_lock_delta(before: dict | None, after: dict | None) -> dict | None:
    """What one tier cost on the sandbox's execution lock.

    The counters are cumulative since the sandbox started, so a tier's own
    contention is the difference between a reading taken before it and one
    taken after. Returns None when either reading is missing rather than
    inventing a zero, which would read as "no contention".
    """
    if not before or not after:
        return None
    labels = {}
    for label, end in (after.get("labels") or {}).items():
        start = (before.get("labels") or {}).get(label) or {}
        acquisitions = end["acquisitions"] - start.get("acquisitions", 0)
        if acquisitions <= 0:
            continue
        waited = end["wait_seconds"] - start.get("wait_seconds", 0.0)
        labels[label] = {
            "acquisitions": acquisitions,
            "wait_seconds": round(waited, 1),
            "held_seconds": round(
                end["held_seconds"] - start.get("held_seconds", 0.0), 1
            ),
            "mean_wait_seconds": round(waited / acquisitions, 2),
            # Not a delta: the peak is a high-water mark, so the run's largest
            # single wait is the honest number to carry here.
            "max_wait_seconds": round(end["max_wait_seconds"], 1),
        }
    if not labels:
        return None
    return {
        "labels": labels,
        "total_wait_seconds": round(
            sum(e["wait_seconds"] for e in labels.values()), 1
        ),
        "total_held_seconds": round(
            sum(e["held_seconds"] for e in labels.values()), 1
        ),
    }


def tier_summary(tier: int, results: list[UserResult], seconds: float,
                 profile: str = "burst", exec_lock: dict | None = None) -> dict:
    failures = [(r, s) for r in results for s in r.failures]
    kinds = {kind: 0 for kind in FAILURE_KINDS}
    for _, sample in failures:
        kinds[sample.kind] = kinds.get(sample.kind, 0) + 1
    durations = [r.seconds for r in results]
    return {
        "tier": tier,
        "profile": profile,
        "users": len(results),
        "completed": sum(1 for r in results if r.completed),
        "wall_seconds": round(seconds, 1),
        "failure_count": len(failures),
        "failures_by_kind": {k: v for k, v in kinds.items() if v},
        "user_seconds": {
            "p50": round(percentile(durations, 50), 1),
            "p95": round(percentile(durations, 95), 1),
            "max": round(max(durations), 1) if durations else 0.0,
        },
        "endpoints": endpoint_stats(results),
        "exec_lock": exec_lock,
        "failures": [
            {
                "user": result.user,
                "example": result.example,
                "node_id": sample.node_id,
                "endpoint": sample.endpoint,
                "kind": sample.kind,
                "status": sample.status,
                "detail": (sample.error or "")[:2000],
            }
            for result, sample in failures
        ],
        "users_detail": [
            {
                "user": r.user, "example": r.example, "completed": r.completed,
                "seconds": round(r.seconds, 1), "calls": len(r.samples),
            }
            for r in sorted(results, key=lambda r: -r.seconds)
        ],
    }


def peak_container_stats(stats_log: str | None) -> dict | None:
    """Peak memory and PID count from a ``docker stats`` sample log.

    The log is written by the CI job (one ``docker stats --no-stream`` line per
    sample). Absent or unreadable, this is simply left out of the report: the
    run's own numbers do not depend on it.
    """
    if not stats_log or not os.path.exists(stats_log):
        return None
    peak_mib = 0.0
    peak_pids = 0
    units = {"kib": 1 / 1024, "mib": 1.0, "gib": 1024.0}
    try:
        with open(stats_log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                raw_mem = parts[1].split("/")[0].strip().lower()
                for unit, factor in units.items():
                    if raw_mem.endswith(unit):
                        try:
                            peak_mib = max(peak_mib, float(raw_mem[: -len(unit)]) * factor)
                        except ValueError:
                            pass
                        break
                try:
                    peak_pids = max(peak_pids, int(parts[2]))
                except ValueError:
                    pass
    except OSError:
        return None
    if peak_mib == 0.0 and peak_pids == 0:
        return None
    return {"peak_memory_mib": round(peak_mib, 1), "peak_pids": peak_pids}


def build_report(run_id: str, backend_url: str, tiers: list[dict],
                 stats_log: str | None = None, profile: str = "burst") -> dict:
    report = {
        "run_id": run_id,
        "backend_url": backend_url,
        "profile": profile,
        "tiers": tiers,
        "failed": any(t["failure_count"] for t in tiers),
    }
    peaks = peak_container_stats(stats_log)
    if peaks:
        report["container_peaks"] = peaks
    return report


def markdown(report: dict) -> str:
    lines = [f"## Stress run `{report['run_id']}` ({report.get('profile', 'burst')} profile)", ""]
    lines.append("| Tier | Users | Completed | Wall | Failures | User p95 |")
    lines.append("| ---: | ----: | --------: | ---: | -------: | -------: |")
    for tier in report["tiers"]:
        mark = "" if tier["failure_count"] == 0 else " :x:"
        lines.append(
            f"| {tier['tier']} | {tier['users']} | {tier['completed']} "
            f"| {tier['wall_seconds']}s | {tier['failure_count']}{mark} "
            f"| {tier['user_seconds']['p95']}s |"
        )
    peaks = report.get("container_peaks")
    if peaks:
        lines += ["", f"Container peak: {peaks['peak_memory_mib']} MiB, "
                      f"{peaks['peak_pids']} PIDs."]

    for tier in report["tiers"]:
        lines += ["", f"### {tier['tier']} users", ""]
        lines.append("| Endpoint | Calls | Errors | p50 | p95 | max |")
        lines.append("| -------- | ----: | -----: | --: | --: | --: |")
        for endpoint, stat in tier["endpoints"].items():
            lines.append(
                f"| `{endpoint}` | {stat['calls']} | {stat['errors']} "
                f"| {stat['p50_s']}s | {stat['p95_s']}s | {stat['max_s']}s |"
            )
        lock = tier.get("exec_lock")
        if lock:
            lines += ["", "Execution lock, this tier:", ""]
            lines.append("| Call site | Acquisitions | Waited | Held | Mean wait | Max wait |")
            lines.append("| --------- | -----------: | -----: | ---: | --------: | -------: |")
            for label, stat in sorted(
                lock["labels"].items(), key=lambda kv: -kv[1]["wait_seconds"]
            ):
                lines.append(
                    f"| `{label}` | {stat['acquisitions']} "
                    f"| {stat['wait_seconds']}s | {stat['held_seconds']}s "
                    f"| {stat['mean_wait_seconds']}s | {stat['max_wait_seconds']}s |"
                )
        if tier["failures"]:
            lines += ["", "<details><summary>"
                          f"{len(tier['failures'])} failure(s)</summary>", ""]
            for failure in tier["failures"][:50]:
                detail = failure["detail"].replace("\n", " ")[:300]
                lines.append(
                    f"- `{failure['user']}` {failure['example']} "
                    f"node `{failure['node_id']}` at `{failure['endpoint']}` "
                    f"({failure['kind']}): {detail}"
                )
            if len(tier["failures"]) > 50:
                lines.append(f"- ... and {len(tier['failures']) - 50} more "
                             "(see report.json)")
            lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def write_outputs(report: dict, out_dir: str) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "report.json")
    md_path = os.path.join(out_dir, "summary.md")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(markdown(report))

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(markdown(report))
    return json_path, md_path


def raw_samples(results: list[UserResult]) -> list[dict]:
    """Every sample, for a run someone wants to re-analyse later."""
    return [
        {"user": r.user, "example": r.example, **asdict(s)}
        for r in results for s in r.samples
    ]
