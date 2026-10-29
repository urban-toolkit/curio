"""Turn a run's samples into numbers a reader can act on.

Two outputs: ``report.json`` for later comparison between runs, and a markdown
summary for the CI step summary. Both answer the same three questions -- what
broke, how slow did it get, and how close to a resource ceiling did the stack
come -- for the users' dataflow runs and for their tabs of the shared
dataflows: how long an update took to be in every other tab, and the backend's
threads, memory and doc files on disk.
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


MIB = 1024 * 1024


def distribution(values: list[float], scale: float = 1.0, digits: int = 1) -> dict | None:
    """The count, total, p50, p95 and max of *values* times *scale*. None for
    no values, which a reader must not take for zeros."""
    if not values:
        return None
    scaled = [value * scale for value in values]
    return {
        "count": len(scaled),
        "total": round(sum(scaled), digits),
        "p50": round(percentile(scaled, 50), digits),
        "p95": round(percentile(scaled, 95), digits),
        "max": round(max(scaled), digits),
    }


def socket_summary(rooms: list[dict]) -> dict | None:
    """What a tier's tabs did, from each room's ``sockets.Room.outcome``: the
    updates they sent, how long each took to be in every other tab of its room
    (``sync_ms``; None when no room had a second tab), the updates that never
    were (``unsynced``), the rooms whose tabs ended with different docs, and
    the size of the doc a tab joining at the end would download. None for a
    tier with no rooms."""
    if not rooms:
        return None
    seconds = [value for room in rooms for value in room["sync_seconds"]]
    state = [room["doc_state_bytes"] for room in rooms if room.get("doc_state_bytes") is not None]
    return {
        "rooms": len(rooms),
        "tabs": sum(room["tabs"] for room in rooms),
        "transports": sorted({name for room in rooms for name in room["transports"]}),
        "updates": sum(room["updates"] for room in rooms),
        "keystrokes": sum(room["keystrokes"] for room in rooms),
        "drags": sum(room["drags"] for room in rooms),
        "deliveries": sum(room["deliveries"] for room in rooms),
        "sync_ms": distribution(seconds, 1000.0),
        "unsynced": sum(room["unsynced"] for room in rooms),
        "diverged_rooms": sum(1 for room in rooms if room["diverged"]),
        "doc_state_bytes": {"max": max(state), "total": sum(state)} if state else None,
        "per_room": [
            {
                "room": room["room"], "project_id": room["project_id"], "tabs": room["tabs"],
                "doc_ids": room["doc_ids"], "updates": room["updates"],
                "sync_ms": distribution(room["sync_seconds"], 1000.0),
                "unsynced": room["unsynced"], "diverged": room["diverged"],
                "doc_state_bytes": room.get("doc_state_bytes"),
            }
            for room in rooms
        ],
    }


def cpu_track(readings: list, seconds_key: str, at_key: str) -> dict | None:
    """A process's CPU over the *readings* that carry its CPU seconds
    (*seconds_key*) and the moment each was read (*at_key*): the seconds it
    ran, user plus system, from the first to the last; the cores that kept
    busy over that span; and the most over one step between two readings of
    at least half a second (about the sampler's second). None with fewer than
    two such readings, which a reader must not take for an idle process."""
    points = sorted(
        (reading[at_key], reading[seconds_key]) for reading in readings
        if reading and isinstance(reading.get(seconds_key), (int, float))
        and isinstance(reading.get(at_key), (int, float))
    )
    if len(points) < 2 or points[-1][0] <= points[0][0]:
        return None
    (first_at, first), (last_at, last) = points[0], points[-1]
    steps = [(b_cpu - a_cpu) / (b_at - a_at)
             for (a_at, a_cpu), (b_at, b_cpu) in zip(points, points[1:]) if b_at - a_at >= 0.5]
    return {
        "seconds": round(last - first, 1),
        "over_s": round(last_at - first_at, 1),
        "cores_busy": round((last - first) / (last_at - first_at), 2),
        "peak_cores_busy": round(max(steps), 2) if steps else None,
    }


def harness_summary(start: dict | None, samples: list[dict], end: dict | None) -> dict:
    """The harness's CPU over a tier (``backend_probe.reading_now``), its
    processes together, which drive every user's dataflow calls and tab: beside
    the backend's, it says which side was busy."""
    return {"cpu": cpu_track([start, *samples, end], "harness_cpu_seconds", "harness_at")}


def backend_summary(start: dict | None, samples: list[dict], end: dict | None,
                    every_s: float, problem: str | None = None) -> dict:
    """The backend's threads, resident memory and CPU over a tier, from the
    probe (``backend_probe.py``): the reading before the tier, the highest of
    all readings, those taken while it ran (every *every_s* seconds) included,
    and the reading after it; and the CPU it ran over the tier
    (:func:`cpu_track`). Not measured, with *problem* as the reason, when the
    probe read nothing; a missing reading is None, never a zero."""
    readings = [reading for reading in (start, *samples, end) if reading and "threads" in reading]
    if not readings:
        return {"measured": False, "problem": problem or "the probe read nothing"}
    start = start if start and "threads" in start else None
    end = end if end and "threads" in end else None

    def track(key: str, scale: float, digits: int | None) -> dict:
        def value(reading):
            number = (reading or {}).get(key)
            if not isinstance(number, (int, float)):
                return None
            return round(number * scale, digits) if digits else int(number * scale)

        values = [v for v in (value(reading) for reading in readings) if v is not None]
        return {"start": value(start), "peak": max(values) if values else None, "end": value(end)}

    return {
        "measured": True,
        "pid": (end or start or readings[-1]).get("pid"),
        "threads": track("threads", 1, None),
        "rss_mib": track("rss_bytes", 1 / MIB, 1),
        "cpu": cpu_track(readings, "cpu_seconds", "at"),
        "samples": sum(1 for sample in samples if sample and "threads" in sample),
        "every_s": every_s,
        "problem": problem,
    }


def doc_files_summary(listing: dict | None, problem: str | None = None) -> dict:
    """A tier's shared dataflows' doc logs on disk, as the probe listed them
    (``backend_probe.doc_files``): for each doc, each day's checkpoint
    (``.bin``) and its updates (``.updates``). Not measured, with *problem*
    as the reason, when the probe listed nothing."""
    if listing is None:
        return {"measured": False, "problem": problem or "the probe listed no files"}
    files = [{"project_id": project_id, **segment}
             for project_id in sorted(listing) for segment in listing[project_id]]

    def sizes(key: str) -> dict:
        values = [entry[key] for entry in files if isinstance(entry.get(key), int)]
        return {"total": sum(values), "max": max(values) if values else 0}

    return {
        "measured": True,
        "dataflows": len(listing),
        "without_log": sorted(project_id for project_id, segments in listing.items() if not segments),
        "docs": len({(entry["project_id"], entry["doc"]) for entry in files}),
        "segments": len(files),
        "bin_bytes": sizes("bin_bytes"),
        "updates_bytes": sizes("updates_bytes"),
        "files": files,
    }


def tier_summary(tier: int, results: list[UserResult], seconds: float,
                 profile: str = "burst", exec_lock: dict | None = None,
                 sockets: dict | None = None, backend: dict | None = None,
                 doc_files: dict | None = None, harness: dict | None = None) -> dict:
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
        "sockets": sockets,
        "backend": backend,
        "doc_files": doc_files,
        "harness": harness,
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
                **({"tab": r.tab} if r.tab else {}),
            }
            for r in sorted(results, key=lambda r: -r.seconds)
        ],
    }


def peak_container_stats(stats_log: str | None) -> dict | None:
    """Peak memory, PID count and CPU from a ``docker stats`` sample log.

    The log is written by the CI job (one ``docker stats --no-stream`` line per
    sample, plus a ``HOST`` line carrying the load average and core count).
    Absent or unreadable, this is simply left out of the report: the run's own
    numbers do not depend on it.

    Docker reports CPU as a percentage of ONE core, so 800% is eight cores
    busy, and the useful reading is that number against the host's core count.
    That comparison is the point of collecting it: a tier that saturates a
    lock rather than the machine shows up here as a nearly idle host, and no
    amount of extra execution parallelism would change it.

    Reads both the current four-field format and the three-field one that
    every run before this wrote, so old logs still parse.
    """
    if not stats_log or not os.path.exists(stats_log):
        return None
    peak_mib = 0.0
    peak_pids = 0
    peak_cpu = 0.0
    cpu_samples = []
    peak_load = 0.0
    host_cores = None
    units = {"kib": 1 / 1024, "mib": 1.0, "gib": 1024.0}
    try:
        with open(stats_log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                if parts[0] == "HOST":
                    # HOST|load1|load5|load15|cores
                    try:
                        peak_load = max(peak_load, float(parts[1]))
                    except ValueError:
                        pass
                    if len(parts) >= 5:
                        try:
                            host_cores = int(parts[4])
                        except ValueError:
                            pass
                    continue
                if len(parts) >= 4 and parts[1].endswith("%"):
                    try:
                        cpu = float(parts[1][:-1])
                        peak_cpu = max(peak_cpu, cpu)
                        cpu_samples.append(cpu)
                    except ValueError:
                        pass
                    parts = [parts[0]] + parts[2:]  # fall through as name|mem|pids
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
    stats = {"peak_memory_mib": round(peak_mib, 1), "peak_pids": peak_pids}
    if cpu_samples:
        stats["peak_cpu_percent"] = round(peak_cpu, 1)
        stats["mean_cpu_percent"] = round(sum(cpu_samples) / len(cpu_samples), 1)
        # The reading that matters: cores actually busy, against cores present.
        stats["peak_cores_busy"] = round(peak_cpu / 100, 1)
    if peak_load:
        stats["peak_host_load"] = round(peak_load, 2)
    if host_cores:
        stats["host_cores"] = host_cores
    return stats


def build_report(run_id: str, backend_url: str, tiers: list[dict],
                 stats_log: str | None = None, profile: str = "burst",
                 room_size: int | None = None) -> dict:
    report = {
        "run_id": run_id,
        "backend_url": backend_url,
        "profile": profile,
        "room_size": room_size,
        "tiers": tiers,
        "failed": any(t["failure_count"] for t in tiers),
    }
    peaks = peak_container_stats(stats_log)
    if peaks:
        report["container_peaks"] = peaks
    return report


def _kib(size: int) -> str:
    return f"{size / 1024:.1f} KiB"


def _three(track: dict, unit: str = "") -> str:
    """A start / peak / end track, a missing reading as a dash."""
    return " / ".join("-" if track.get(key) is None else f"{track[key]}" for key in ("start", "peak", "end")) + unit


def _tabs_table(tiers: list[dict]) -> list[str]:
    if not any(tier.get("sockets") for tier in tiers):
        return []
    lines = ["", "Tabs: each user's tab of its room's shared dataflow, typing in a "
                 "node's code and dragging the node. Sync is an update's time "
                 "from its tab to every other tab of the room; the doc is what "
                 "a tab joining at the end downloads.", ""]
    lines.append("| Tier | Rooms | Tabs | Updates | Sync p50 | Sync p95 | Sync max "
                 "| Doc a tab downloads | Unsynced | Diverged rooms |")
    lines.append("| ---: | ----: | ---: | ------: | -------: | -------: | -------: "
                 "| ------------------: | -------: | -------------: |")
    for tier in tiers:
        tabs = tier.get("sockets")
        if not tabs:
            continue
        sync = tabs.get("sync_ms")
        cells = [f"{sync[key]} ms" for key in ("p50", "p95", "max")] if sync else ["no other tab"] * 3
        state = tabs.get("doc_state_bytes")
        cells.append(f"{_kib(state['max'])} at most" if state else "-")
        lines.append(
            f"| {tier['tier']} | {tabs['rooms']} | {tabs['tabs']} | {tabs['updates']} "
            f"| {' | '.join(cells)} | {tabs['unsynced']} | {tabs['diverged_rooms']} |"
        )
    return lines


def _backend_table(tiers: list[dict]) -> list[str]:
    if not any(tier.get("backend") or tier.get("doc_files") for tier in tiers):
        return []
    every = next((tier["backend"].get("every_s") for tier in tiers
                  if (tier.get("backend") or {}).get("measured")), None)
    lines = ["", "The backend's process before each tier, at its peak "
                 + (f"(read every {every:g} s) " if every else "")
                 + "and after it; and the tier's doc logs on disk, each day's "
                 "checkpoint (`.bin`) and updates (`.updates`).", ""]
    lines.append("| Tier | Threads | RSS (MiB) | Doc logs | `.bin` | `.updates` |")
    lines.append("| ---: | ------: | --------: | -------: | -----: | ---------: |")
    for tier in tiers:
        backend = tier.get("backend") or {}
        files = tier.get("doc_files") or {}
        if backend.get("measured"):
            process = [_three(backend["threads"]), _three(backend["rss_mib"])]
        else:
            process = [f"not measured: {backend.get('problem') or 'no probe'}", "-"]
        if files.get("measured"):
            logs = [f"{files['docs']}", _kib(files["bin_bytes"]["total"]), _kib(files["updates_bytes"]["total"])]
        else:
            logs = [f"not measured: {files.get('problem') or 'no probe'}", "-", "-"]
        lines.append(f"| {tier['tier']} | {' | '.join(process + logs)} |")
    return lines


def _cpu_cells(track: dict | None, missing: str) -> list[str]:
    """A CPU track's seconds, and its cores busy over the tier and at the peak."""
    if not track:
        return [missing, "-"]
    peak = "-" if track.get("peak_cores_busy") is None else track["peak_cores_busy"]
    return [f"{track['seconds']} s", f"{track['cores_busy']} / {peak}"]


def _cpu_table(tiers: list[dict]) -> list[str]:
    if not any((tier.get("backend") or {}).get("cpu") or (tier.get("harness") or {}).get("cpu")
               for tier in tiers):
        return []
    lines = ["", "CPU over each tier, user plus system: the seconds the backend's process "
                 "and the harness's processes (every user's calls and tab) ran, and the cores that "
                 "kept busy over the tier and at most over one reading.", ""]
    lines.append("| Tier | Backend CPU | Backend cores (tier / peak) | Harness CPU | Harness cores (tier / peak) |")
    lines.append("| ---: | ----------: | --------------------------: | ----------: | --------------------------: |")
    for tier in tiers:
        backend = tier.get("backend") or {}
        missing = "not measured" if not backend.get("measured") else "-"
        cells = (_cpu_cells(backend.get("cpu"), missing)
                 + _cpu_cells((tier.get("harness") or {}).get("cpu"), "not measured"))
        lines.append(f"| {tier['tier']} | {' | '.join(cells)} |")
    return lines


def markdown(report: dict) -> str:
    # Artifacts are fetched the way the canvas fetches them, as Arrow, and the
    # tabs connect over the transport named here. Said here because a report
    # outlives the run that made it, and a reader comparing this against an
    # older one needs to know the wire changed.
    transports = sorted({
        name for tier in report["tiers"]
        for name in ((tier.get("sockets") or {}).get("transports") or [])
    })
    wire = "arrow artifacts" + (f", tabs over {' and '.join(transports)}" if transports else "")
    lines = [f"## Stress run `{report['run_id']}` "
             f"({report.get('profile', 'burst')} profile, {wire})", ""]
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
        peak_line = (f"Container peak: {peaks['peak_memory_mib']} MiB, "
                     f"{peaks['peak_pids']} PIDs")
        if "peak_cores_busy" in peaks:
            peak_line += (f", {peaks['peak_cpu_percent']}% CPU "
                          f"({peaks['peak_cores_busy']} cores busy at peak, "
                          f"{peaks['mean_cpu_percent']}% mean)")
        if "peak_host_load" in peaks:
            cores = peaks.get("host_cores")
            peak_line += (f". Host load peaked at {peaks['peak_host_load']}"
                          + (f" on {cores} cores" if cores else ""))
        lines += ["", peak_line + "."]
    lines += _tabs_table(report["tiers"])
    lines += _backend_table(report["tiers"])
    lines += _cpu_table(report["tiers"])

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
