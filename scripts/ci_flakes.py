#!/usr/bin/env python3
"""Which tests the flake hunt saw both pass and fail, over every runner's lanes.

The flake hunt (.github/workflows/flake-hunt.yml) runs the same tests on 10 or
more Curio stacks at once (scripts/ci_lanes.py). Its report job downloads every
runner's flake-lanes-<r> artifact into one folder and runs this, which:

* groups every attempt of every test (each lane and iteration's JUnit) by test;
* calls a test flaky when it passed at least once and failed at least once,
  and failing when it failed and never passed;
* adds the runners' health.csv up at each moment, for the most stacks that were
  healthy at the same time: the proof that the hunt ran them together;
* writes the run summary (Markdown), flakes.json, and one self-contained HTML
  page with each failure's lane, iteration, runner and message, and one
  screenshot per failing e2e test.

It exits 1 when any test failed even once, when one of the hunt's own checks
failed (a stack that never became healthy, an OOM kill, a run past its time
limit), when a runner left no results, or when fewer stacks were healthy at
once than were asked for.

    python scripts/ci_flakes.py inputs --out flake-report.html \\
        --summary "$GITHUB_STEP_SUMMARY" --json flakes.json
"""
from __future__ import annotations

import argparse
import bisect
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Appended, not put first: a test process that imports this keeps every other
# import as it was.
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import ci_lanes  # noqa: E402  (the lanes' layout and the hunt's own checks)
import ci_report  # noqa: E402  (the JUnit reader, the page's look, screenshots)

LANE_DIR = re.compile(r"^lane-(\d+)$")
ITER_DIR = re.compile(r"^iter-(\d+)$")
#: A runner's health sample older than this no longer counts at a moment.
STALE_S = 3 * ci_lanes.SAMPLE_S
LISTED_PLACES = 6
UNITS = {"b": 1, "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4,
         "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12}


@dataclass
class Attempt:
    status: str  # passed, failed, error, skipped or xfailed, as ci_report reads JUnit
    runner: int
    runner_name: str = ""
    lane: int | None = None
    iteration: int | None = None
    part: str = ""
    message: str = ""
    details: str = ""
    screenshot: str = ""

    @property
    def place(self) -> str:
        bits = []
        if self.lane is not None:
            bits.append(f"lane {self.lane}")
        if self.iteration is not None:
            bits.append(f"iteration {self.iteration}")
        where = ", ".join(bits) or f"runner {self.runner}"
        return f"{where} ({self.runner_name})" if self.runner_name else where


@dataclass
class Test:
    name: str
    harness: bool
    attempts: list = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for a in self.attempts if a.status == "passed")

    @property
    def failed(self) -> int:
        return sum(1 for a in self.attempts if a.status in ("failed", "error"))

    @property
    def ran(self) -> int:
        return self.passed + self.failed

    @property
    def verdict(self) -> str:
        if self.failed:
            return "flaky" if self.passed else "failing"
        return "passed" if self.passed else "skipped"

    def failures(self):
        return [a for a in self.attempts if a.status in ("failed", "error")]


@dataclass
class Runner:
    index: int
    name: str
    stacks: int
    healthy: int
    health: list  # (epoch, healthy) samples
    stats: dict


@dataclass
class Hunt:
    tests: dict = field(default_factory=dict)  # name -> Test
    runners: list = field(default_factory=list)
    expected_runners: int = 0
    requested: int = 0
    peak: int = 0
    peak_at: int | None = None
    thread_exhaustion: int = 0
    settings: dict = field(default_factory=dict)

    def listed(self, verdict, harness=False):
        found = [t for t in self.tests.values() if t.verdict == verdict and t.harness == harness]
        return sorted(found, key=lambda t: (-t.failed, t.name))

    @property
    def missing_runners(self) -> list:
        seen = {r.index for r in self.runners}
        return [i for i in range(1, self.expected_runners + 1) if i not in seen]

    @property
    def attempts(self) -> int:
        """Test runs that passed or failed, the hunt's own checks aside."""
        return sum(t.ran for t in self.tests.values() if not t.harness)

    @property
    def failed(self) -> bool:
        # No attempt at all is a hunt that tested nothing (a filter that
        # matched only WebGPU tests, say), never a clean one.
        return (any(t.failed for t in self.tests.values()) or bool(self.missing_runners)
                or self.peak < self.requested or not self.runners or not self.attempts)


# ---------------------------------------------------------------- inputs


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:300]
    return ""


def runner_dirs(root: Path) -> list:
    if not root.is_dir():
        return []  # no runner uploaded anything: a hunt with no results fails
    found = [root] if (root / "runner.json").is_file() else []
    found += [p for p in sorted(root.iterdir()) if p.is_dir() and (p / "runner.json").is_file()]
    return found


def read_health(path: Path) -> list:
    samples = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return samples
    for line in lines[1:]:
        bits = line.split(",")
        try:
            samples.append((int(bits[0]), int(bits[1])))
        except (IndexError, ValueError):
            continue  # a half-written last line from a killed sampler
    return sorted(samples)


def peak_together(series) -> tuple:
    """The most stacks healthy at one moment over every runner, and when.

    Each runner samples on its own clock tick, so at every sample time each
    runner counts with its latest sample, if that is recent enough.
    """
    times = [[t for t, _ in s] for s in series]
    best, when = 0, None
    for moment in sorted({t for s in series for t, _ in s}):
        total = 0
        for samples, stamps in zip(series, times):
            at = bisect.bisect_right(stamps, moment) - 1
            if at >= 0 and moment - stamps[at] <= STALE_S:
                total += samples[at][1]
        if total > best:
            best, when = total, moment
    return best, when


def to_bytes(text: str) -> float:
    match = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", text or "")
    if not match:
        return 0.0
    return float(match[1]) * UNITS.get(match[2].lower(), 0)


def read_stats(path: Path) -> dict:
    """Peaks from a lanes job's docker-stats.log (see ci_lanes.sample_stats)."""
    peak_memory, peak_pids, peak_load, cpus = 0.0, 0, 0.0, 0
    sample = 0.0

    def close():
        nonlocal peak_memory
        peak_memory = max(peak_memory, sample)

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        bits = line.split("|")
        if bits[0] == "TIME":
            close()
            sample = 0.0
        elif bits[0] == "HOST" and len(bits) >= 5:
            try:
                peak_load = max(peak_load, float(bits[1]))
                cpus = int(bits[4])
            except ValueError:
                pass
        elif bits[0].startswith(ci_lanes.PROJECT_PREFIX) and len(bits) >= 4:
            sample += to_bytes(bits[2].split("/")[0])
            try:
                peak_pids = max(peak_pids, int(bits[3]))
            except ValueError:
                pass
    close()
    return {"peak_memory_gib": round(peak_memory / 1024 ** 3, 1), "peak_pids": peak_pids,
            "peak_load": peak_load, "cpus": cpus}


def collect(root: Path, requested: int | None = None) -> Hunt:
    hunt = Hunt()
    for folder in runner_dirs(root):
        info = json.loads((folder / "runner.json").read_text(encoding="utf-8"))
        index, name = int(info.get("runner") or 0), info.get("runner_name") or ""
        lanes = info.get("lanes") or []
        parts = {lane["g"]: lane.get("parts") or [] for lane in lanes}
        hunt.expected_runners = max(hunt.expected_runners, int(info.get("runners") or 0))
        hunt.settings = hunt.settings or {key: info.get(key) for key in
                                          ("runners", "stacks", "iterations", "suite", "tests", "workflows", "image")}
        hunt.runners.append(Runner(index=index, name=name, stacks=int(info.get("stacks") or len(lanes)),
                                   healthy=sum(1 for lane in lanes if lane.get("healthy")),
                                   health=read_health(folder / "health.csv"),
                                   stats=read_stats(folder / "docker-stats.log")))
        for path in sorted(folder.rglob("*.xml")):
            if path.name != "junit.xml" and not path.name.startswith("harness"):
                continue
            lane = iteration = None
            for piece in path.relative_to(folder).parts[:-1]:
                if match := LANE_DIR.match(piece):
                    lane = int(match[1])
                elif match := ITER_DIR.match(piece):
                    iteration = int(match[1])
            lane_parts = parts.get(lane) or []
            part = lane_parts[iteration - 1] if iteration and len(lane_parts) >= iteration else ""
            shots = ci_report.read_failures(str(path.parent / "failures")) if path.name == "junit.xml" else {}
            for case in ci_report.read_junit(str(path), str(path)).cases:
                screenshot = ""
                if case.status in ("failed", "error"):
                    for nodeid in ci_report.candidate_nodeids(*case.key):
                        if ci_report.failure_folder(nodeid) in shots:
                            screenshot = shots[ci_report.failure_folder(nodeid)]
                            break
                test = hunt.tests.setdefault(case.name, Test(case.name, case.key[0] == ci_lanes.HARNESS))
                test.attempts.append(Attempt(status=case.status, runner=index, runner_name=name, lane=lane,
                                             iteration=iteration, part=part, message=case.message,
                                             details=case.details, screenshot=screenshot))
        for path in folder.glob("lane-*/iter-*/run.json"):
            try:
                hunt.thread_exhaustion += int(json.loads(path.read_text(encoding="utf-8")).get("thread_exhaustion") or 0)
            except (OSError, ValueError):
                pass
    hunt.runners.sort(key=lambda r: r.index)
    hunt.requested = requested if requested is not None else (
        (hunt.settings.get("runners") or 0) * (hunt.settings.get("stacks") or 0))
    hunt.peak, hunt.peak_at = peak_together([r.health for r in hunt.runners])
    return hunt


# ---------------------------------------------------------------- output


def clock(epoch) -> str:
    if epoch is None:
        return "never"
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%H:%M:%S UTC")


def by_message(test: Test) -> list:
    """Failed attempts grouped by their message's first line, most common first."""
    groups = {}
    for attempt in test.failures():
        groups.setdefault(first_line(attempt.message) or "(no message)", []).append(attempt)
    return sorted(groups.items(), key=lambda item: -len(item[1]))


def places(attempts) -> str:
    shown = [a.place for a in attempts[:LISTED_PLACES]]
    more = len(attempts) - len(shown)
    return "; ".join(shown) + (f"; and {more} more" if more > 0 else "")


def selection(settings: dict) -> str:
    if settings.get("tests") or settings.get("workflows"):
        bits = []
        if settings.get("tests"):
            bits.append(f"-k {settings['tests']}")
        if settings.get("workflows"):
            bits.append(f"workflows {settings['workflows']}")
        return f"the same tests on every lane ({', '.join(bits)})"
    if settings.get("suite") == "sandbox":
        return "the whole suite on every lane"
    return "the suite split over the lanes, a different part each iteration"


def overview(hunt: Hunt) -> list:
    """(label, value) rows shared by the summary and the page."""
    s = hunt.settings
    tests = [t for t in hunt.tests.values() if not t.harness and t.ran]
    attempts = sum(t.ran for t in tests)
    tries = sorted({t.ran for t in tests})
    each = (f"{tries[0]} each" if len(tries) == 1 else f"{tries[0]} to {tries[-1]} each") if tries else "none"
    rows = [
        ("Stacks asked for", f"{hunt.requested} ({s.get('runners')} runners x {s.get('stacks')} stacks)"),
        ("Most healthy at once", f"{hunt.peak}, at {clock(hunt.peak_at)}"),
        ("Suite", f"{s.get('suite')}, {s.get('iterations')} iterations, {selection(s)}"),
        ("Tests", f"{len(tests)} ran, {attempts} attempts ({each})"),
        ("Flaky / failing", f"{len(hunt.listed('flaky'))} / {len(hunt.listed('failing'))}"),
    ]
    for runner in hunt.runners:
        st = runner.stats
        rows.append((f"Runner {runner.index}" + (f" ({runner.name})" if runner.name else ""),
                     f"{runner.healthy} of {runner.stacks} stacks healthy; peak {st['peak_memory_gib']} GiB "
                     f"in lane containers, {st['peak_pids']} processes in one, load {st['peak_load']:g}"
                     + (f" on {st['cpus']} CPUs" if st["cpus"] else "")))
    rows.append(('"can\'t start new thread" in container logs', str(hunt.thread_exhaustion)))
    return rows


def headline(hunt: Hunt) -> str:
    if not hunt.failed:
        return f"No test failed in {hunt.attempts} attempts."
    bits = [] if hunt.attempts else ["no test ran"]
    for verdict, word in (("flaky", "flaky"), ("failing", "failing")):
        count = len(hunt.listed(verdict))
        if count:
            bits.append(f"{count} {word} test{'s' if count != 1 else ''}")
    checks = [t for t in hunt.tests.values() if t.harness and t.failed]
    if checks:
        bits.append(f"{len(checks)} failed check{'s' if len(checks) != 1 else ''} of the hunt itself")
    if hunt.missing_runners:
        bits.append("runner " + ", ".join(map(str, hunt.missing_runners)) + " left no results")
    if hunt.peak < hunt.requested:
        bits.append(f"only {hunt.peak} of {hunt.requested} stacks were healthy at once")
    text = "; ".join(bits) or "no results"
    return text[0].upper() + text[1:] + "."


def md(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_summary(hunt: Hunt) -> str:
    out = ["## Flake hunt", "", f"**{'Failed' if hunt.failed else 'Passed'}.** {md(headline(hunt))}", "",
           "| | |", "|---|---|"]
    out += [f"| {md(label)} | {md(value)} |" for label, value in overview(hunt)]
    for verdict, title in (("flaky", "Flaky: passed and failed"), ("failing", "Failed in every attempt")):
        tests = hunt.listed(verdict)
        if not tests:
            continue
        out += ["", f"### {title}", "", "| Test | Failed | Of | Where it failed | First message |",
                "|---|---|---|---|---|"]
        for test in tests:
            message, _ = by_message(test)[0]
            out.append(f"| `{md(test.name)}` | {test.failed} | {test.ran} | {md(places(test.failures()))} "
                       f"| {md(message)} |")
    checks = [t for t in hunt.tests.values() if t.harness and t.failed]
    if checks:
        out += ["", "### The hunt's own checks that failed", "", "| Check | Failed | Of | Where | Message |",
                "|---|---|---|---|---|"]
        for test in sorted(checks, key=lambda t: t.name):
            message, _ = by_message(test)[0]
            out.append(f"| {md(test.name)} | {test.failed} | {test.ran} | {md(places(test.failures()))} "
                       f"| {md(message)} |")
    out += ["", "A test that passed every attempt ran only as many times as the Tests row says: "
                "a few clean tries, not proof that it never fails.", ""]
    return "\n".join(out)


def render_json(hunt: Hunt) -> dict:
    return {
        "failed": hunt.failed,
        "requested": hunt.requested,
        "peak": hunt.peak,
        "peak_at": hunt.peak_at,
        "settings": hunt.settings,
        "missing_runners": hunt.missing_runners,
        "thread_exhaustion": hunt.thread_exhaustion,
        "runners": [{"runner": r.index, "name": r.name, "stacks": r.stacks, "healthy": r.healthy, **r.stats}
                    for r in hunt.runners],
        "tests": [{
            "name": t.name, "harness": t.harness, "verdict": t.verdict, "passed": t.passed, "failed": t.failed,
            "failures": [{"runner": a.runner, "runner_name": a.runner_name, "lane": a.lane,
                          "iteration": a.iteration, "part": a.part, "status": a.status,
                          "message": first_line(a.message)} for a in t.failures()],
        } for t in sorted(hunt.tests.values(), key=lambda t: t.name)],
    }


def verdict_badge(verdict: str) -> str:
    """ci_report's badge, in the colour of the CI report's status that reads the same."""
    look = {"flaky": "unclear", "failing": "failed"}.get(verdict, verdict)
    return ci_report.badge(look, verdict)


def screenshot_of(test: Test):
    return next((a for a in test.failures() if a.screenshot), None)


def render_test(page, test: Test) -> str:
    esc = ci_report.esc
    out = [f'<article class="case"><h4>{verdict_badge(test.verdict)} '
           f'<span class="test-id">{esc(test.name)}</span> '
           f'<span class="muted">failed {test.failed} of {test.ran}</span></h4>']
    for message, attempts in by_message(test):
        out.append(f'<pre class="message">{esc(message)}</pre>'
                   f'<p class="muted">{len(attempts)}x: {esc(places(attempts))}</p>')
    first = test.failures()[0] if test.failures() else None
    if first and first.details:
        out.append(f"<details><summary>Trace of the first failure ({esc(first.place)})</summary>"
                   f"<pre>{esc(ci_report.clip(first.details))}</pre></details>")
    shot = screenshot_of(test)
    if shot:
        out.append(ci_report._screenshot(page, shot.screenshot, f"At the moment of failure, {shot.place}"))
    return "".join(out) + "</article>"


def render_page(hunt: Hunt, max_image_mb: int, workers: int) -> str:
    esc = ci_report.esc
    meta = ci_report.run_meta(os.environ)
    # One screenshot per failing test, flaky ones first: the page's image
    # budget goes to them before the always-failing ones.
    shots = [screenshot_of(t).screenshot for verdict in ("flaky", "failing")
             for t in hunt.listed(verdict) if screenshot_of(t)]
    page = SimpleNamespace(images=ci_report.budget_images(ci_report.encode_images(shots, workers), shots,
                                                          max_image_mb), image_mb=max_image_mb)
    state = "failed" if hunt.failed else "passed"
    run = f'<a href="{esc(meta["run_url"])}">Run {esc(meta["run_id"])}</a> · ' if meta["run_url"] else ""
    rows = "".join(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>" for label, value in overview(hunt))
    sections = []
    for verdict, title in (("flaky", "Flaky: passed and failed"), ("failing", "Failed in every attempt")):
        tests = hunt.listed(verdict)
        if tests:
            sections.append(f'<section><h2>{esc(title)} ({len(tests)})</h2><div class="suite">'
                            + "".join(render_test(page, t) for t in tests) + "</div></section>")
    checks = sorted((t for t in hunt.tests.values() if t.harness), key=lambda t: t.name)
    if checks:
        sections.append("<section><h2>The hunt's own checks</h2><div class=\"suite\">" + "".join(
            render_test(page, t) if t.failed else
            f'<article class="case"><h4>{ci_report.badge("passed")} <span class="test-id">{esc(t.name)}</span> '
            f'<span class="muted">{t.ran} of {t.ran}</span></h4></article>' for t in checks) + "</div></section>")
    every = sorted((t for t in hunt.tests.values() if not t.harness), key=lambda t: (t.verdict != "flaky",
                                                                                      t.verdict != "failing", t.name))
    table = "".join(f'<tr><td class="test-id">{esc(t.name)}</td><td>{verdict_badge(t.verdict)}</td>'
                    f'<td class="num">{t.passed}</td><td class="num">{t.failed}</td></tr>' for t in every)
    sections.append(f"<section><h2>Every test ({len(every)})</h2><details><summary>Attempts per test</summary>"
                    '<div class="table-wrap"><table><thead><tr><th>Test</th><th>Verdict</th>'
                    f'<th class="num">Passed</th><th class="num">Failed</th></tr></thead><tbody>{table}'
                    "</tbody></table></div></details></section>")
    return "\n".join([
        "<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Flake hunt</title>", f"<style>{ci_report.CSS}</style>", "</head>", "<body>",
        f'<header class="top"><div class="title-row"><h1>Flake hunt</h1>{ci_report.badge(state)}</div>'
        f'<p class="meta">{run}{esc(meta["ref"])} · {esc(meta["generated"])}</p></header>',
        "<main>", f"<p>{esc(headline(hunt))}</p>",
        f'<div class="table-wrap"><table><tbody>{rows}</tbody></table></div>',
        *sections, "</main>", ci_report.VIEWER, f"<script>{ci_report.JS}</script>", "</body>", "</html>",
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("inputs", help="the folder the flake-lanes-* artifacts were downloaded into")
    parser.add_argument("--requested", type=int, help="stacks asked for (default: runners x stacks)")
    parser.add_argument("--out", required=True, metavar="PATH", help="the HTML page")
    parser.add_argument("--summary", metavar="PATH", help="append the Markdown summary here")
    parser.add_argument("--json", metavar="PATH")
    parser.add_argument("--max-image-mb", type=int, default=150)
    parser.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 4))
    args = parser.parse_args(argv)

    hunt = collect(Path(args.inputs), args.requested)
    Path(args.out).write_text(render_page(hunt, args.max_image_mb, args.workers), encoding="utf-8")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(render_summary(hunt))
    if args.json:
        Path(args.json).write_text(json.dumps(render_json(hunt), indent=2), encoding="utf-8")
    print(headline(hunt))
    return 1 if hunt.failed else 0


if __name__ == "__main__":
    sys.exit(main())
