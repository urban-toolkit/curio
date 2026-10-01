#!/usr/bin/env python3
"""Build one self-contained HTML page from a CI job's test results.

A CI run has a dozen suites and about 240 screenshot comparisons, and the only
ways to read them were the job log and a zipped Allure site that has to be
served before it opens. This writes a single HTML file with everything inline,
images included. Uploaded with ``actions/upload-artifact`` and
``archive: false``, GitHub serves it straight into the browser from the run's
artifact list.

Every input is optional, because a step that never ran leaves no file:

    --junit LABEL=PATH   pytest JUnit XML (repeatable)
    --jest LABEL=PATH    Jest's --json output (repeatable)
    --tsc LABEL=PATH     tsc output, written with --pretty false (repeatable)
    --comparisons DIR    an e2e run's CURIO_E2E_COMPARE_DIR: one folder per
                         screenshot comparison (see
                         utk_curio/backend/tests/test_frontend/comparisons.py)
    --failures DIR       an e2e run's CURIO_E2E_FAILURE_DIR, for the screenshot
                         each failed test left behind
    --jobs PATH          GitHub's jobs API response for this run attempt
    --all-jobs           report on every job in --jobs rather than this one: the
                         page the run's ci-report job builds from every runner

With Pillow importable every image is transcoded to lossless WebP, identical
pixel for pixel at about half the size of the PNG; without it the recorded
PNGs are embedded as they are.

Usage::

    python scripts/ci_report.py --junit "End-to-end tests=e2e.xml" \\
        --comparisons .curio/compare --failures .curio/playwright/failures \\
        --out report.html
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import re
import sys
import traceback
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

ANSI = re.compile(r"(?:\x1b|#x1B)\[[0-9;?]*[ -/]*[@-~]")
# diagnostics.failure_dir's sanitizer: how a failed e2e test's folder is named.
UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")
TSC_ERROR = re.compile(
    r"^(?:(?P<file>[^\s(][^(]*)\((?P<line>\d+),(?P<col>\d+)\): )?"
    r"error (?P<code>TS\d+): (?P<message>.*)$"
)
# xdist's --dist loadgroup appends "@<group>" to every node id.
XDIST_GROUP = re.compile(r"@[^\[\]@]*$")
# npm's own lines around a script, which say nothing about tsc's result.
NPM_CHATTER = re.compile(r"^(>|npm (notice|warn)\b)", re.IGNORECASE)

TRACE_KEEP = 6000  # characters kept from each end of a long trace
MAX_LISTED = 200  # failures listed per suite
STATUS_RANK = {"passed": 0, "xfailed": 1, "skipped": 2, "error": 3, "failed": 4}

# "reminted" and "unchanged" come only from a --remint-baselines run: the first
# replaced its baseline, the second kept it. "minted" is a baseline this run
# wrote where there was none, so it is new and needs a look like a re-mint.
COMPARISON_GROUP = {
    "failed": "over", "capture-error": "capture", "missing": "missing",
    "passed": "within", "minted": "minted",
    "reminted": "reminted", "unchanged": "unchanged",
}
COMPARISON_LABEL = {
    "failed": "Over budget", "capture-error": "Capture failed",
    "missing": "No baseline", "passed": "Within budget", "minted": "Minted",
    "reminted": "Re-minted", "unchanged": "Unchanged",
}
GROUP_ORDER = ("reminted", "minted", "over", "capture", "missing", "within", "unchanged")
GROUP_LABEL = {
    "reminted": "Re-minted", "minted": "Minted", "over": "Over budget",
    "capture": "Capture failed", "missing": "No baseline", "within": "Within budget",
    "unchanged": "Unchanged",
}


@dataclass
class Case:
    name: str
    status: str = "passed"
    seconds: float = 0.0
    message: str = ""
    details: str = ""
    kind: str = ""  # "crash" or "collection" for those pytest errors
    key: tuple = ()  # (classname, name), pytest only
    screenshot: str = ""
    comparisons: list = field(default_factory=list)


@dataclass
class Suite:
    label: str
    kind: str  # pytest, jest or tsc
    path: str
    found: bool = False
    cases: list = field(default_factory=list)
    seconds: float | None = None
    failure_note: str = ""
    problem: str = ""  # the input could not be read
    tsc_errors: list = field(default_factory=list)
    raw_tail: str = ""

    def count(self, *statuses):
        return sum(1 for case in self.cases if case.status in statuses)

    @property
    def status(self):
        if self.problem:
            return "unreadable"
        if not self.found:
            return "missing"
        if self.kind == "tsc":
            if self.tsc_errors:
                return "failed"
            return "unclear" if self.raw_tail else "passed"
        if self.count("failed", "error") or self.failure_note:
            return "failed"
        return "passed"


@dataclass
class Report:
    meta: dict
    job: dict | None = None
    suites: list = field(default_factory=list)
    comparisons: list = field(default_factory=list)
    stray_screenshots: dict = field(default_factory=dict)
    images: dict = field(default_factory=dict)  # path -> data URI, or None past the budget
    image_mb: int = 0
    jobs_given: bool = False
    # Every job of the run, when the page reports on the run rather than one job.
    all_jobs: list | None = None
    # Interaction frames in before/after pairs, see build_pairs.
    pairs: list = field(default_factory=list)
    problems: list = field(default_factory=list)


# ---------------------------------------------------------------- inputs


def clean(text):
    return ANSI.sub("", text or "").replace("\r\n", "\n")


def clip(text, keep=TRACE_KEEP):
    if len(text) <= 2 * keep + 200:
        return text
    return (f"{text[:keep]}\n\n[... {len(text) - 2 * keep:,} characters left out ...]"
            f"\n\n{text[-keep:]}")


def display_name(classname, name):
    return f"{classname}::{XDIST_GROUP.sub('', name)}" if classname else XDIST_GROUP.sub("", name)


def junit_key(nodeid):
    """The (classname, name) pytest's junitxml writes for *nodeid*.

    Same steps as its ``mangle_test_address``: the file path becomes a dotted
    module, ``.py`` goes, and parametrize ids stay on the last name.
    """
    path, bracket, params = nodeid.partition("[")
    names = path.split("::")
    names[0] = re.sub(r"\.py$", "", names[0].replace("/", "."))
    names[-1] += bracket + params
    return ".".join(names[:-1]), names[-1]


def candidate_nodeids(classname, name):
    """Every node id a JUnit (classname, name) can have come from.

    The dotted classname hides where the file path ends and the classes
    begin, so try each split; only one of them names a real failure folder.
    """
    parts = classname.split(".") if classname else []
    for k in range(len(parts), 0, -1):
        yield "::".join(["/".join(parts[:k]) + ".py", *parts[k:], name])


def failure_folder(nodeid):
    return UNSAFE.sub("_", nodeid).strip("_")[:180]


def read_junit(label, path):
    suite = Suite(label, "pytest", path)
    if not os.path.isfile(path):
        return suite
    suite.found = True
    root = ET.parse(path).getroot()
    cases = {}
    for element in root.iter("testcase"):
        key = (element.get("classname") or "", element.get("name") or "")
        case = _junit_case(element, key)
        # A test that fails and then errors in teardown is written twice.
        cases[key] = _merge(cases[key], case) if key in cases else case
    suite.cases = list(cases.values())
    times = [float(s.get("time")) for s in root.iter("testsuite") if s.get("time")]
    suite.seconds = sum(times) if times else sum(case.seconds for case in suite.cases)
    return suite


def _junit_case(element, key):
    case = Case(name=display_name(*key), seconds=_float(element.get("time")), key=key)
    for tag in ("failure", "error", "skipped"):
        found = element.find(tag)
        if found is None:
            continue
        case.message = clean(found.get("message") or "").strip()
        case.details = clean(found.text or "").strip()
        if tag == "failure":
            case.status = "failed"
        elif tag == "error":
            case.status = "error"
            if re.search(r"worker '?[\w-]+'? crashed", case.message):
                case.kind = "crash"
            elif case.message == "collection failure":
                case.kind = "collection"
        else:
            case.status = "xfailed" if found.get("type") == "pytest.xfail" else "skipped"
        break
    return case


def _merge(first, second):
    worse = first if STATUS_RANK[first.status] >= STATUS_RANK[second.status] else second
    return Case(
        name=first.name,
        status=worse.status,
        seconds=first.seconds + second.seconds,
        message="\n\n".join(m for m in (first.message, second.message) if m),
        details="\n\n".join(d for d in (first.details, second.details) if d),
        kind=worse.kind,
        key=first.key,
    )


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def read_jest(label, path):
    suite = Suite(label, "jest", path)
    if not os.path.isfile(path):
        return suite
    suite.found = True
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    ends = []
    for result in data.get("testResults") or []:
        file_name = _short_path(result.get("name") or "")
        failed_here = False
        for assertion in result.get("assertionResults") or []:
            raw = assertion.get("status")
            status = {"passed": "passed", "focused": "passed", "failed": "failed"}.get(raw, "skipped")
            failed_here = failed_here or status == "failed"
            messages = clean("\n\n".join(assertion.get("failureMessages") or [])).strip()
            title = " > ".join([*(assertion.get("ancestorTitles") or []), assertion.get("title") or ""])
            suite.cases.append(Case(
                name=f"{file_name} > {title}",
                status=status,
                seconds=(assertion.get("duration") or 0) / 1000,
                message=messages.split("\n", 1)[0] if messages else (raw if status == "skipped" else ""),
                details=messages,
            ))
        if result.get("status") == "failed" and not failed_here:
            # The file failed outside any test: it did not compile, or threw
            # while importing, so Jest has no assertion to report it under.
            message = clean(result.get("message") or "").strip() or "Test suite failed to run"
            suite.cases.append(Case(name=file_name, status="error",
                                    message=message.split("\n", 1)[0], details=message))
        if result.get("endTime"):
            ends.append(result["endTime"])
    if data.get("startTime") and ends:
        suite.seconds = (max(ends) - data["startTime"]) / 1000
    if data.get("success") is False and not suite.count("failed", "error"):
        suite.failure_note = ("Jest reported a failure without a failing test, for example "
                              "an open handle or a coverage threshold.")
    return suite


def _short_path(path):
    marker = "/urban-workflows/"
    return path.split(marker, 1)[1] if marker in path else path


def read_tsc(label, path):
    suite = Suite(label, "tsc", path)
    if not os.path.isfile(path):
        return suite
    suite.found = True
    with open(path, encoding="utf-8", errors="replace") as handle:
        text = clean(handle.read())
    unexpected = False
    for line in text.splitlines():
        match = TSC_ERROR.match(line)
        if match:
            suite.tsc_errors.append(match.groupdict())
        elif line[:1].isspace() and line.strip() and suite.tsc_errors:
            suite.tsc_errors[-1]["message"] += "\n" + line.strip()
        elif line.strip() and not NPM_CHATTER.match(line):
            unexpected = True
    if unexpected and not suite.tsc_errors:
        suite.raw_tail = "\n".join(text.splitlines()[-40:])
    return suite


def read_comparisons(root):
    found = []
    if not root or not os.path.isdir(root):
        return found
    for entry in sorted(os.listdir(root)):
        folder = os.path.join(root, entry)
        try:
            with open(os.path.join(folder, "record.json"), encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue  # no record.json: the run died while writing it
        record["images"] = {
            kind: os.path.join(folder, name)
            for kind, name in (record.get("images") or {}).items()
            if os.path.isfile(os.path.join(folder, name))
        }
        found.append(record)
    found.sort(key=_comparison_order)
    return found


def _comparison_order(record):
    group = COMPARISON_GROUP.get(record.get("status"), "within")
    if group in ("reminted", "unchanged"):
        closeness = record.get("ratio") or 0  # biggest change first
    else:
        budget = record.get("max_diff_ratio") or 0
        closeness = (record.get("ratio") or 0) / budget if budget else 0
    return GROUP_ORDER.index(group), -closeness, record.get("baseline") or ""


# ---------------------------------------------------------------- interaction pairs

#: What "What changed" marks: more than this in some channel, the rule the
#: interaction steps in test_workflows count a highlight by.
PAIR_CHANGE_THRESHOLD = 40
PAIR_ROLES = ("source", "target")
PAIR_PHASES = ("before", "after")
PAIR_FADE = 0.2  # as comparisons.FADE: how much of the after frame shows under the red


def pair_frame(record):
    """The image a pair shows for *record*: its baseline as this run leaves it.

    A re-mint wrote this run's capture over the baseline, and a missing
    baseline has only the capture that would become one. Every other record's
    baseline is the file as committed, or as a mint just wrote it.
    """
    images = record.get("images") or {}
    if record.get("status") in ("reminted", "missing"):
        return images.get("created")
    return images.get("expected") or images.get("created")


def build_pairs(records):
    """Interaction frames by step, one row per node with its before and after record."""
    steps = {}
    for record in records:
        meta = record.get("interaction")
        if not isinstance(meta, dict):
            continue
        key = (meta.get("workflow") or "", meta.get("step") or "")
        step = steps.setdefault(key, {
            "workflow": key[0], "step": key[1], "gesture": meta.get("gesture") or "",
            "source": meta.get("source") or "", "target": meta.get("target") or "",
            "rows": {},
        })
        role = meta.get("role") or ""
        row = step["rows"].setdefault(role, {"role": role, "node": meta.get("node") or ""})
        row[meta.get("phase") or ""] = record
    pairs = []
    for key in sorted(steps):
        step = steps[key]
        rows = [step["rows"][role] for role in PAIR_ROLES if role in step["rows"]]
        rows += [row for role, row in step["rows"].items() if role not in PAIR_ROLES]
        pairs.append({**step, "rows": rows})
    return pairs


def change_image(before_path, after_path, threshold=PAIR_CHANGE_THRESHOLD):
    """The after frame faded, with every pixel that differs from before in red.

    Returns ``(data URI, changed pixels, total pixels)``, or None without Pillow.
    """
    try:
        from PIL import Image, ImageChops, features
    except Exception:
        return None
    with Image.open(before_path) as b, Image.open(after_path) as a:
        before, after = b.convert("RGB"), a.convert("RGB")
    size = (max(before.width, after.width), max(before.height, after.height))
    before, after = before.resize(size), after.resize(size)
    over = ImageChops.difference(before, after).point(lambda v: 255 if v > threshold else 0)
    red, green, blue = over.split()
    mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    backdrop = after.convert("L").point(lambda v: int(255 - (255 - v) * PAIR_FADE)).convert("RGB")
    marked = Image.composite(Image.new("RGB", size, (255, 0, 0)), backdrop, mask)
    buf = io.BytesIO()
    webp = bool(features.check("webp"))
    marked.save(buf, "WEBP" if webp else "PNG", **({"lossless": True} if webp else {}))
    return (_data_uri("image/webp" if webp else "image/png", buf.getvalue()),
            mask.histogram()[255], size[0] * size[1])


def add_pair_changes(pairs):
    """Give each row with both frames its before-to-after ``change``."""
    for pair in pairs:
        for row in pair["rows"]:
            frames = [pair_frame(row[p]) if p in row else None for p in PAIR_PHASES]
            if all(frames):
                row["change"] = change_image(*frames)


def read_failures(root):
    if not root or not os.path.isdir(root):
        return {}
    shots = {}
    for entry in sorted(os.listdir(root)):
        path = os.path.join(root, entry, "screenshot.png")
        if os.path.isfile(path):
            shots[entry] = path
    return shots


def read_job(path, job_name):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        jobs = (json.load(handle) or {}).get("jobs") or []
    return (next((j for j in jobs if j.get("name") == job_name), None)
            or next((j for j in jobs if j.get("status") == "in_progress"), None))


def read_jobs(path):
    """Every job in a jobs API response, in the order GitHub lists them."""
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return (json.load(handle) or {}).get("jobs") or []


def run_meta(environ):
    server = environ.get("GITHUB_SERVER_URL") or "https://github.com"
    repo = environ.get("GITHUB_REPOSITORY") or ""
    run_id = environ.get("GITHUB_RUN_ID") or ""
    return {
        "server": server,
        "repo": repo,
        "run_id": run_id,
        "run_url": f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "",
        "attempt": environ.get("GITHUB_RUN_ATTEMPT") or "",
        "event": environ.get("GITHUB_EVENT_NAME") or "",
        "ref": environ.get("PR_HEAD_REF") or environ.get("GITHUB_REF_NAME") or "",
        "sha": environ.get("PR_HEAD_SHA") or environ.get("GITHUB_SHA") or "",
        "pr_number": environ.get("PR_NUMBER") or "",
        "pr_title": environ.get("PR_TITLE") or "",
        "job": environ.get("GITHUB_JOB") or "",
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


# ---------------------------------------------------------------- images


def encode_images(paths, workers):
    """Every image as a data URI, transcoded to lossless WebP when Pillow can."""
    try:
        from PIL import Image, features
        webp = bool(features.check("webp"))
    except Exception:
        Image, webp = None, False

    def one(path):
        if webp:
            try:
                with Image.open(path) as img:
                    alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
                    buf = io.BytesIO()
                    img.convert("RGBA" if alpha else "RGB").save(buf, "WEBP", lossless=True)
                return _data_uri("image/webp", buf.getvalue())
            except Exception:
                pass  # not an image Pillow reads; embed the bytes as they are
        try:
            with open(path, "rb") as handle:
                return _data_uri("image/png" if path.lower().endswith(".png") else
                                 "application/octet-stream", handle.read())
        except OSError:
            return None  # one unreadable file costs its own image, not the page's

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        # Pillow releases the GIL while encoding, so threads do scale here.
        return dict(zip(paths, pool.map(one, paths)))


def _data_uri(mime, data):
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def budget_images(encoded, ordered, max_mb):
    """Keep images in page-priority order until the budget runs out."""
    limit, used, kept = max_mb * 1024 * 1024, 0, {}
    for path in ordered:
        uri = encoded.get(path)
        if uri is None or used + len(uri) > limit:
            kept[path] = None
            continue
        kept[path] = uri
        used += len(uri)
    return kept


# ---------------------------------------------------------------- build


def build(args, environ=os.environ):
    report = Report(meta=run_meta(environ), image_mb=args.max_image_mb, jobs_given=bool(args.jobs))

    def guarded(what, fn, fallback):
        try:
            return fn()
        except Exception:
            report.problems.append((what, traceback.format_exc()))
            return fallback

    report.job = guarded("jobs", lambda: read_job(args.jobs, args.job_name or report.meta["job"]), None)
    if getattr(args, "all_jobs", False):
        report.all_jobs = guarded("jobs", lambda: read_jobs(args.jobs), None)
    for kind, reader, entries in (("pytest", read_junit, args.junit), ("jest", read_jest, args.jest),
                                  ("tsc", read_tsc, args.tsc)):
        for label, path in entries or []:
            try:
                report.suites.append(reader(label, path))
            except Exception:
                report.suites.append(Suite(label, kind, path, found=True,
                                           problem=traceback.format_exc()))
    report.comparisons = guarded("comparisons", lambda: read_comparisons(args.comparisons), [])
    shots = guarded("failures", lambda: read_failures(args.failures), {})

    by_key = {case.key: case for suite in report.suites for case in suite.cases if case.key}
    for index, record in enumerate(report.comparisons, 1):
        record["anchor"] = f"cmp-{index}"
        case = by_key.get(junit_key(record.get("nodeid") or ""))
        record["test_status"] = case.status if case else None
        if case:
            case.comparisons.append(record)
    for suite in report.suites:
        for case in suite.cases:
            if case.key and case.status in ("failed", "error"):
                for nodeid in candidate_nodeids(*case.key):
                    folder = failure_folder(nodeid)
                    if folder in shots:
                        case.screenshot = shots.pop(folder)
                        break
    report.stray_screenshots = shots
    report.pairs = guarded("interaction pairs", lambda: build_pairs(report.comparisons), [])
    guarded("interaction changes", lambda: add_pair_changes(report.pairs), None)

    ordered = [case.screenshot for suite in report.suites for case in suite.cases if case.screenshot]
    ordered += list(shots.values())
    # A pair shows a kept baseline too, which the comparison cards leave out.
    ordered += [pair_frame(row[phase]) for pair in report.pairs for row in pair["rows"]
                for phase in PAIR_PHASES if phase in row and pair_frame(row[phase])]
    for record in report.comparisons:
        if record.get("status") == "unchanged":
            continue  # listed without images: a re-mint kept these baselines
        ordered += [record["images"][kind] for kind in ("expected", "created", "diff")
                    if kind in record["images"]]
    ordered = list(dict.fromkeys(ordered))
    encoded = guarded("images", lambda: encode_images(ordered, args.workers), {})
    report.images = budget_images(encoded, ordered, args.max_image_mb)
    return report


# ---------------------------------------------------------------- render


def esc(value):
    return html.escape(str(value), quote=True)


def duration(seconds):
    if seconds is None:
        return ""
    seconds = float(seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def percent(value):
    return f"{value:.2%}" if value is not None else "?"


def badge(status, text=None):
    return f'<span class="badge {esc(status)}">{esc(text or status)}</span>'


def _iso(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def overall(report):
    if report.all_jobs is not None:
        step_failed = any(j.get("conclusion") == "failure" for j in report.all_jobs)
    else:
        step_failed = any(s.get("conclusion") == "failure"
                          for s in (report.job or {}).get("steps") or [])
    if step_failed or any(s.status in ("failed", "unreadable") for s in report.suites):
        return "failed"
    if any(r.get("status") in ("failed", "capture-error", "missing") for r in report.comparisons):
        return "failed"
    if not report.suites and not report.comparisons:
        return "unclear"
    return "passed"


def render(report):
    meta = report.meta
    title = "CI report"
    if meta["pr_number"]:
        title += f": PR #{meta['pr_number']}"
    elif meta["ref"]:
        title += f": {meta['ref']}"
    sections = [
        *([("Jobs" if report.all_jobs is not None else "Steps", "steps",
            render_jobs if report.all_jobs is not None else render_steps)]
          if report.jobs_given else []),
        ("Test suites", "suites", render_suites),
        *([("Interaction pairs", "interactions", render_pairs)] if report.pairs else []),
        ("Screenshot comparisons", "comparisons", render_comparisons),
    ]
    body = []
    for heading, anchor, fn in sections:
        try:
            body.append(fn(report))
        except Exception:
            body.append(f'<section id="{anchor}"><h2>{esc(heading)}</h2>'
                        f'<pre class="problem">{esc(traceback.format_exc())}</pre></section>')
    return "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)}</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        render_header(report, title),
        "<main>",
        render_problems(report),
        *body,
        "</main>",
        render_footer(report),
        VIEWER,
        f"<script>{JS}</script>",
        "</body>",
        "</html>",
    ])


def render_header(report, title):
    meta = report.meta
    bits = []
    if meta["run_url"]:
        attempt = f" (attempt {meta['attempt']})" if meta["attempt"] else ""
        bits.append(f'<a href="{esc(meta["run_url"])}">Run {esc(meta["run_id"])}{esc(attempt)}</a>')
    if meta["job"]:
        bits.append(f"job {esc(meta['job'])}")
    if meta["event"]:
        bits.append(esc(meta["event"]))
    if meta["pr_number"] and meta["repo"]:
        url = f"{meta['server']}/{meta['repo']}/pull/{meta['pr_number']}"
        bits.append(f'<a href="{esc(url)}">#{esc(meta["pr_number"])} {esc(meta["pr_title"])}</a>')
    if meta["ref"]:
        bits.append(f"<code>{esc(meta['ref'])}</code>")
    if meta["sha"]:
        short = meta["sha"][:8]
        url = f"{meta['server']}/{meta['repo']}/commit/{meta['sha']}" if meta["repo"] else ""
        bits.append(f'<a href="{esc(url)}"><code>{esc(short)}</code></a>' if url
                    else f"<code>{esc(short)}</code>")
    bits.append(esc(meta["generated"]))
    state = overall(report)
    word = {"passed": "Passed", "failed": "Failed", "unclear": "No results"}[state]
    links = ([("Jobs" if report.all_jobs is not None else "Steps", "steps")]
             if report.jobs_given else [])
    links += [("Test suites", "suites")]
    if report.pairs:
        links.append((f"Interaction pairs ({len(report.pairs)})", "interactions"))
    links.append((f"Screenshot comparisons ({len(report.comparisons)})", "comparisons"))
    nav = " ".join(f'<a href="#{a}">{esc(t)}</a>' for t, a in links)
    return (f'<header class="top"><div class="title-row"><h1>{esc(title)}</h1>'
            f"{badge(state, word)}</div>"
            f'<p class="meta">{" · ".join(bits)}</p><nav>{nav}</nav></header>')


def render_problems(report):
    if not report.problems:
        return ""
    items = "".join(f"<details><summary>Could not read {esc(what)}</summary>"
                    f'<pre class="problem">{esc(trace)}</pre></details>'
                    for what, trace in report.problems)
    return f'<section class="problems">{items}</section>'


def render_steps(report):
    job = report.job
    if not job:
        return ('<section id="steps"><h2>Steps</h2><p class="muted">No step list: the jobs '
                "API response for this job was missing or could not be read.</p></section>")
    rows, failed = [], 0
    for step in job.get("steps") or []:
        if step.get("status") != "completed":
            continue  # this step, and the ones queued after it
        conclusion = step.get("conclusion") or "unknown"
        failed += conclusion == "failure"
        start, end = _iso(step.get("started_at")), _iso(step.get("completed_at"))
        took = duration((end - start).total_seconds()) if start and end else ""
        name = esc(step.get("name") or "")
        if job.get("html_url") and step.get("number") is not None:
            name = f'<a href="{esc(job["html_url"])}#step:{int(step["number"])}:1">{name}</a>'
        rows.append(f'<tr class="{esc(conclusion)}"><td>{name}</td>'
                    f"<td>{badge(conclusion)}</td><td class=\"num\">{esc(took)}</td></tr>")
    summary = (f"{failed} of {len(rows)} completed steps failed" if failed
               else f"All {len(rows)} completed steps succeeded")
    table = ('<div class="table-wrap"><table class="steps"><thead><tr><th>Step</th><th>Result</th>'
             f'<th class="num">Time</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    open_attr = " open" if failed else ""
    return (f'<section id="steps"><h2>Steps</h2><details class="steps-box"{open_attr}>'
            f"<summary>{esc(summary)}</summary>{table}</details></section>")


def render_jobs(report):
    """Every job of the run, with the failed steps of the ones that failed."""
    rows, failed, done = [], 0, 0
    for job in report.all_jobs or []:
        if job.get("status") != "completed":
            continue  # this job, still building the page, and anything queued
        done += 1
        conclusion = job.get("conclusion") or "unknown"
        failed += conclusion == "failure"
        start, end = _iso(job.get("started_at")), _iso(job.get("completed_at"))
        took = duration((end - start).total_seconds()) if start and end else ""
        name = esc(job.get("name") or "")
        if job.get("html_url"):
            name = f'<a href="{esc(job["html_url"])}">{name}</a>'
        broke = [s for s in job.get("steps") or [] if s.get("conclusion") == "failure"]
        if broke:
            steps = ", ".join(
                f'<a href="{esc(job["html_url"])}#step:{int(s["number"])}:1">{esc(s.get("name") or "")}</a>'
                if job.get("html_url") and s.get("number") is not None else esc(s.get("name") or "")
                for s in broke)
            name += f'<div class="muted">failed: {steps}</div>'
        rows.append(f'<tr class="{esc(conclusion)}"><td>{name}</td>'
                    f"<td>{badge(conclusion)}</td><td class=\"num\">{esc(took)}</td></tr>")
    if not done:
        return ('<section id="steps"><h2>Jobs</h2><p class="muted">No job list: the jobs '
                "API response for this run was missing or could not be read.</p></section>")
    summary = f"{failed} of {done} jobs failed" if failed else f"All {done} completed jobs succeeded"
    table = ('<div class="table-wrap"><table class="steps"><thead><tr><th>Job</th><th>Result</th>'
             f'<th class="num">Time</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    open_attr = " open" if failed else ""
    return (f'<section id="steps"><h2>Jobs</h2><details class="steps-box"{open_attr}>'
            f"<summary>{esc(summary)}</summary>{table}</details></section>")


def suite_numbers(suite):
    if suite.kind == "tsc":
        return None
    return {
        "passed": suite.count("passed"),
        "failed": suite.count("failed"),
        "errors": suite.count("error"),
        "skipped": suite.count("skipped", "xfailed"),
    }


SUITE_WORD = {"passed": "passed", "failed": "failed", "missing": "did not run",
              "unreadable": "unreadable", "unclear": "unclear"}


def render_suites(report):
    if not report.suites:
        return '<section id="suites"><h2>Test suites</h2><p class="muted">No suites were given.</p></section>'
    rows, details = [], []
    for index, suite in enumerate(report.suites, 1):
        anchor = f"suite-{index}"
        numbers = suite_numbers(suite)
        if numbers is None:
            cells = f'<td class="num" colspan="4">{len(suite.tsc_errors)} errors</td>' if suite.found else '<td colspan="4"></td>'
        elif suite.found and not suite.problem:
            cells = "".join(f'<td class="num">{numbers[k]}</td>' for k in ("passed", "failed", "errors", "skipped"))
        else:
            cells = '<td colspan="4"></td>'
        rows.append(f'<tr><td><a href="#{anchor}">{esc(suite.label)}</a></td>'
                    f"<td>{badge(suite.status, SUITE_WORD[suite.status])}</td>{cells}"
                    f'<td class="num">{esc(duration(suite.seconds))}</td></tr>')
        details.append(render_suite(report, suite, anchor))
    table = ('<div class="table-wrap"><table class="suites"><thead><tr><th>Suite</th><th>Result</th>'
             '<th class="num">Passed</th><th class="num">Failed</th><th class="num">Errors</th>'
             '<th class="num">Skipped</th><th class="num">Time</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    stray = ""
    if report.stray_screenshots:
        figures = "".join(_screenshot(report, path, name) for name, path in report.stray_screenshots.items())
        stray = (f'<section class="suite"><h3>Failure screenshots without a matching test</h3>'
                 f"{figures}</section>")
    return f'<section id="suites"><h2>Test suites</h2>{table}{"".join(details)}{stray}</section>'


def render_suite(report, suite, anchor):
    head = f'<section class="suite" id="{anchor}"><h3>{esc(suite.label)} {badge(suite.status, SUITE_WORD[suite.status])}</h3>'
    if suite.problem:
        return f'{head}<pre class="problem">{esc(suite.problem)}</pre></section>'
    if not suite.found:
        return f'{head}<p class="muted">No results at <code>{esc(suite.path)}</code>: the step did not run or stopped before writing them.</p></section>'
    if suite.kind == "tsc":
        return head + render_tsc(suite) + "</section>"
    numbers = suite_numbers(suite)
    parts = [head, f'<p class="muted">{numbers["passed"]} passed, {numbers["failed"]} failed, '
             f'{numbers["errors"]} errors, {numbers["skipped"]} skipped'
             f'{", in " + esc(duration(suite.seconds)) if suite.seconds else ""}.</p>']
    if suite.failure_note:
        parts.append(f'<p class="note">{esc(suite.failure_note)}</p>')
    bad = [case for case in suite.cases if case.status in ("failed", "error")]
    for case in bad[:MAX_LISTED]:
        parts.append(render_case(report, case))
    if len(bad) > MAX_LISTED:
        parts.append(f'<p class="note">{len(bad) - MAX_LISTED} more failures are in the job log.</p>')
    skipped = Counter(case.message or "(no reason given)" for case in suite.cases
                      if case.status in ("skipped", "xfailed"))
    if skipped:
        items = "".join(f"<li><span class=\"num\">{n}</span> {esc(reason)}</li>"
                        for reason, n in skipped.most_common(50))
        parts.append(f'<details class="skips"><summary>Skip reasons</summary><ul>{items}</ul></details>')
    return "".join(parts) + "</section>"


def render_case(report, case):
    label = {"crash": "worker crashed", "collection": "collection failed"}.get(case.kind, case.status)
    parts = [f'<article class="case"><h4>{badge(case.status, label)} <span class="test-id">{esc(case.name)}</span></h4>']
    if case.message:
        parts.append(f'<pre class="message">{esc(clip(case.message, 2000))}</pre>')
    if case.details and case.details != case.message:
        parts.append(f"<details><summary>Trace</summary><pre>{esc(clip(case.details))}</pre></details>")
    if case.comparisons:
        links = ", ".join(
            f'<a href="#{esc(r["anchor"])}">{esc(r.get("baseline") or "?")}</a> '
            f'({esc(COMPARISON_LABEL.get(r.get("status"), r.get("status")).lower())})'
            for r in case.comparisons)
        parts.append(f'<p class="muted">Screenshot comparisons: {links}</p>')
    if case.screenshot:
        parts.append(_screenshot(report, case.screenshot, "Screenshot at the moment of failure"))
    return "".join(parts) + "</article>"


def _screenshot(report, path, caption):
    uri = report.images.get(path)
    if not uri:
        return (f'<p class="note">{esc(caption)}: left out, unreadable or past the page\'s '
                f'{report.image_mb} MB image budget.</p>')
    return (f'<figure class="failure-shot"><button type="button" class="shot" aria-label="Open at original size">'
            f'<img src="{uri}" alt="{esc(caption)}" loading="lazy" decoding="async" data-caption="{esc(caption)}">'
            f"</button><figcaption>{esc(caption)}</figcaption></figure>")


def render_tsc(suite):
    if suite.tsc_errors:
        rows = "".join(
            f'<tr><td><code>{esc(e.get("file") or "(project)")}'
            f'{":" + esc(e["line"]) + ":" + esc(e["col"]) if e.get("line") else ""}</code></td>'
            f'<td><code>{esc(e["code"])}</code></td><td><pre>{esc(e["message"])}</pre></td></tr>'
            for e in suite.tsc_errors[:MAX_LISTED])
        return ('<div class="table-wrap"><table class="tsc"><thead><tr><th>Where</th><th>Code</th>'
                f"<th>Message</th></tr></thead><tbody>{rows}</tbody></table></div>")
    if suite.raw_tail:
        return ('<p class="note">No tsc error line was found, but the output has more than the npm '
                f'banner. Its last lines:</p><pre>{esc(suite.raw_tail)}</pre>')
    return '<p class="muted">No type errors.</p>'


def _figure(uri, caption, full):
    if not uri:
        return (f'<figure class="empty"><div class="placeholder">{esc(full)}</div>'
                f"<figcaption>{esc(caption)}</figcaption></figure>")
    return (f'<figure><button type="button" class="shot" aria-label="Open {esc(caption.lower())} at original size">'
            f'<img src="{uri}" alt="{esc(full)}" loading="lazy" decoding="async" data-caption="{esc(full)}">'
            f"</button><figcaption>{esc(caption)}</figcaption></figure>")


def render_pairs(report):
    """Each interaction step's nodes before and after it, for a person to judge."""
    cards = []
    for pair in report.pairs:
        rows = []
        for row in pair["rows"]:
            node = row.get("node") or "?"
            figures, states = [], []
            for phase in PAIR_PHASES:
                record = row.get(phase)
                if record is None:
                    figures.append(_figure(None, phase.capitalize(), "not captured"))
                    continue
                path = pair_frame(record)
                full = f"{phase.capitalize()}: {record.get('baseline') or node}"
                figures.append(_figure(report.images.get(path) if path else None,
                                       phase.capitalize(), full if path else "nothing was captured"))
                status = record.get("status") or "passed"
                word = esc(COMPARISON_LABEL.get(status, status).lower())
                states.append(f'{phase} <a href="#{esc(record.get("anchor") or "")}">{word}</a>'
                              if status != "unchanged" else f"{phase} {word}")
            change = row.get("change")
            if change:
                uri, changed, total = change
                caption = f"What changed: {changed:,} pixels ({changed / total:.2%})" if total else "What changed"
                figures.append(_figure(uri, caption, f"{caption}, {node}"))
            else:
                figures.append(_figure(None, "What changed", "needs both frames"))
            label = {"source": "Source", "target": "Target"}.get(row.get("role"), row.get("role") or "?")
            rows.append(f'<div class="pair-row"><h4>{esc(label)} <code>{esc(node)}</code>'
                        f'<span class="muted">{", ".join(states)}</span></h4>'
                        f'<div class="trio">{"".join(figures)}</div></div>')
        gesture = pair.get("gesture") or "gesture"
        cards.append(
            f'<article class="card pair"><header class="card-head">{badge("interaction", gesture)}'
            f'<h3>{esc(pair["workflow"])}: {esc(pair["step"])}</h3></header>'
            f'<p class="test">A {esc(gesture)} on <code>{esc(pair.get("source"))}</code>, '
            f'which lights up <code>{esc(pair.get("target"))}</code>.</p>{"".join(rows)}</article>')
    intro = ('<p class="note">Each row is one node of an interaction step, framed together '
             "with the other node, before and after the gesture. The frames are the baselines "
             "as this run leaves them, so on a mint or re-mint run they are the new ones. "
             f"What changed marks in red every pixel that differs by more than {PAIR_CHANGE_THRESHOLD} "
             "in a channel between the two.</p>")
    return (f'<section id="interactions"><h2>Interaction pairs</h2>{intro}'
            f'<div class="cards">{"".join(cards)}</div></section>')


def render_comparisons(report):
    records = report.comparisons
    if not records:
        return ('<section id="comparisons"><h2>Screenshot comparisons</h2><p class="muted">'
                "No comparisons were recorded.</p></section>")
    shown = [r for r in records if r.get("status") != "unchanged"]
    kept = [r for r in records if r.get("status") == "unchanged"]
    counts = Counter(COMPARISON_GROUP.get(r.get("status"), "within") for r in shown)
    chips = [f'<button type="button" class="chip" data-group="all" aria-pressed="true">All '
             f'<span class="num">{len(shown)}</span></button>']
    chips += [f'<button type="button" class="chip {g}" data-group="{g}" aria-pressed="false">'
              f'{GROUP_LABEL[g]} <span class="num">{counts[g]}</span></button>'
              for g in GROUP_ORDER if counts[g]]
    # Across the groups: every node framed on its own, whatever became of it.
    closeups = sum(1 for r in shown if r.get("closeup"))
    if closeups:
        chips.append('<button type="button" class="chip closeup" data-group="closeup" '
                     f'aria-pressed="false">Close-ups <span class="num">{closeups}</span></button>')
    interactions = sum(1 for r in shown if r.get("interaction"))
    if interactions:
        chips.append('<button type="button" class="chip interaction" data-group="interaction" '
                     f'aria-pressed="false">Interactions <span class="num">{interactions}</span></button>')
    volatile = ('<span class="swatch volatile"></span> different, inside text a run writes '
                'fresh every time (not counted by a re-mint) '
                if any(r.get("volatile_pixels") for r in records) else "")
    legend = ('<p class="legend"><span class="swatch counted"></span> counted against the budget '
              '<span class="swatch within"></span> different, but within the per-channel tolerance '
              f'{volatile}<span class="swatch same"></span> the same (expected image, faded)</p>')
    tools = (f'<div class="tools">{"".join(chips)}<input id="cmp-search" type="search" '
             'placeholder="Filter by baseline or test" aria-label="Filter comparisons"></div>')
    intro = render_remint_intro(records) if counts["reminted"] or kept else ""
    if counts["minted"]:
        intro += render_minted_intro(records)
    cards = "".join(render_comparison(report, r) for r in shown)
    return (f'<section id="comparisons"><h2>Screenshot comparisons</h2>{intro}{tools}{legend}'
            f'<div class="cards">{cards}</div>{render_unchanged(kept)}</section>')


def _remint_floor(records):
    return next((r["remint_min_ratio"] for r in records if r.get("remint_min_ratio") is not None), None)


def render_remint_intro(records):
    reminted = sum(1 for r in records if r.get("status") == "reminted")
    kept = sum(1 for r in records if r.get("status") == "unchanged")
    floor = _remint_floor(records)
    rule = (f"more than {percent(floor)} of its pixels changed" if floor is not None
            else "its pixels changed")
    forced = sum(1 for r in records if r.get("status") == "reminted" and r.get("forced"))
    requested = (f" {forced} of them were requested by name, so they were replaced whatever "
                 "changed." if forced else "")
    return (f'<p class="note">A re-mint run: {reminted} baselines were replaced by what this run '
            f"captured and {kept} were kept. A baseline is replaced when {rule}, not counting "
            "text a run writes fresh every time (file names, ids, dates, times and the app "
            f"version).{requested} Each re-minted card shows the baseline it replaced; the "
            "replacements are in this run's <code>reminted-baselines</code> artifact.</p>")


def render_minted_intro(records):
    minted = sum(1 for r in records if r.get("status") == "minted")
    return (f'<p class="note">{minted} baselines did not exist, so this run wrote them from what '
            "it captured. Each Minted card shows the new baseline; nothing checked it against "
            "an older one.</p>")


def render_unchanged(records):
    if not records:
        return ""
    rows = "".join(
        f"<tr><td><code>{esc(r.get('baseline') or '?')}</code></td>"
        f'<td class="num">{percent(r.get("ratio"))}</td>'
        f'<td class="num">{percent(r.get("remint_ratio"))}</td></tr>'
        for r in sorted(records, key=lambda r: -(r.get("remint_ratio") or 0)))
    return (f'<details class="unchanged" id="unchanged"><summary>{len(records)} baselines '
            "kept as committed</summary><div class=\"table-wrap\"><table><thead><tr>"
            '<th>Baseline</th><th class="num">Pixels changed</th>'
            '<th class="num">Not counting volatile text</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div></details>")


def render_comparison(report, record):
    status = record.get("status") or "passed"
    group = COMPARISON_GROUP.get(status, "within")
    baseline = record.get("baseline") or "?"
    nodeid = record.get("nodeid") or ""
    threshold = record.get("pixel_threshold")
    budget = record.get("max_diff_ratio")
    ratio = record.get("ratio")

    head = [badge(group, COMPARISON_LABEL.get(status, status)), f"<h3>{esc(baseline)}</h3>"]
    if record.get("closeup"):
        head.append(badge("closeup", "close-up"))
    meta = record.get("interaction")
    if isinstance(meta, dict):
        head.append(badge("interaction", f"{meta.get('step')}, {meta.get('phase')}"))
    test = XDIST_GROUP.sub("", nodeid)
    test_bits = f'<span class="test-id">{esc(test)}</span>' if test else ""
    if record.get("test_status") in ("failed", "error"):
        test_bits += " " + badge("failed", "test failed")
    captions = (("expected", "Expected"), ("created", "Created"), ("diff", "Difference"))

    if status == "reminted":
        captions = (("expected", "Committed baseline"), ("created", "Re-minted"),
                    ("diff", "Difference"))
        recapture = record.get("recapture_ratio")
        floor = record.get("remint_min_ratio") or 0
        verdict = (f"<strong>{percent(ratio)}</strong> of pixels changed from the committed "
                   f"baseline by more than {esc(threshold)} per channel, "
                   f"<strong>{percent(record.get('remint_ratio'))}</strong> not counting "
                   "volatile text.")
        if recapture is not None:
            verdict += f" A second capture right after moved {percent(recapture)}."
            if recapture > floor:
                head.append(badge("capture", "moved on recapture"))
        if ratio is not None and budget and ratio > budget:
            head.append(badge("over", "over the budget until committed"))
        if record.get("forced"):
            head.append(badge("reminted", "requested"))
        meter = ""
    elif status == "minted":
        # The new baseline, and a second capture compared with it.
        captions = (("expected", "New baseline"), ("created", "Captured again"),
                    ("diff", "Difference"))
        verdict = (f"No baseline existed, so this capture became one. A second capture right "
                   f"after differs from it by <strong>{percent(ratio)}</strong> (more than "
                   f"{esc(threshold)} per channel); budget <strong>{percent(budget)}</strong>.")
        meter = ""
    elif ratio is not None and budget:
        verdict = (f"<strong>{percent(ratio)}</strong> of pixels differ by more than {esc(threshold)} "
                   f"per channel; budget <strong>{percent(budget)}</strong>.")
        share = min(ratio / budget, 1.0)
        level = "over" if ratio > budget else "near" if ratio >= 0.8 * budget else "ok"
        meter = (f'<span class="meter-wrap"><span class="meter {level}" role="img" '
                 f'aria-label="{ratio / budget:.0%} of the budget">'
                 f'<span style="width:{share * 100:.1f}%"></span></span>'
                 f'<span class="meter-label">{ratio / budget:.0%} of the budget</span></span>')
    else:
        verdict = (f"Budget {percent(budget)} of pixels differing by more than {esc(threshold)} per channel."
                   if budget is not None else "")
        meter = ""
    facts = []
    if record.get("mismatched") is not None and record.get("total"):
        facts.append(f"{record['mismatched']:,} of {record['total']:,} pixels")
    if record.get("max_delta") is not None:
        facts.append(f"largest channel difference {record['max_delta']}")
    for key, word in (("expected_size", "expected"), ("created_size", "created"), ("compared_size", "compared")):
        size = record.get(key)
        if size:
            facts.append(f"{word} {size[0]}x{size[1]}")
    if record.get("capture"):
        facts.append(record["capture"])
    error = f'<pre class="message">{esc(record["error"])}</pre>' if record.get("error") else ""

    figures = []
    for kind, caption in captions:
        path = record["images"].get(kind)
        uri = report.images.get(path) if path else None
        full = f"{caption}: {baseline}"
        if uri:
            figures.append(
                f'<figure><button type="button" class="shot" aria-label="Open {esc(caption.lower())} at original size">'
                f'<img src="{uri}" alt="{esc(full)}" loading="lazy" decoding="async" data-caption="{esc(full)}">'
                f"</button><figcaption>{caption}</figcaption></figure>")
        else:
            why = ("left out: unreadable, or past the page's image budget" if path else
                   {"expected": "no baseline", "created": "nothing was captured",
                    "diff": "nothing to compare"}[kind])
            figures.append(f'<figure class="empty"><div class="placeholder">{esc(why)}</div>'
                           f"<figcaption>{caption}</figcaption></figure>")
    search = f"{baseline} {test}".lower()
    return (f'<article class="card cmp" id="{esc(record.get("anchor") or "")}" '
            f'data-group="{group}" data-closeup="{"1" if record.get("closeup") else ""}" '
            f'data-interaction="{"1" if record.get("interaction") else ""}" '
            f'data-search="{esc(search)}">'
            f'<header class="card-head">{"".join(head)}</header>'
            f'<p class="test">{test_bits}</p>'
            f'<p class="verdict"><span>{verdict}</span>{meter}</p>'
            f'<p class="facts">{esc(", ".join(facts))}</p>{error}'
            f'<div class="trio">{"".join(figures)}</div></article>')


def render_footer(report):
    meta = report.meta
    link = (f' Also in <a href="{esc(meta["run_url"])}#artifacts">this run\'s artifacts</a>: '
            "allure-report, container-logs, and e2e-failures when a test failed.") if meta["run_url"] else ""
    return (f'<footer><p>Built by <code>scripts/ci_report.py</code> at {esc(meta["generated"])}.'
            f"{link}</p></footer>")


def render_summary(report):
    """Markdown for $GITHUB_STEP_SUMMARY: the suite table and comparison counts."""
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")

    lines = ["| Suite | Result | Passed | Failed | Errors | Skipped |",
             "| --- | --- | ---: | ---: | ---: | ---: |"]
    for suite in report.suites:
        numbers = suite_numbers(suite)
        word = SUITE_WORD[suite.status]
        if numbers is None:
            errors = f"{len(suite.tsc_errors)} errors" if suite.found else ""
            lines.append(f"| {cell(suite.label)} | {word} | | {errors} | | |")
        elif suite.found and not suite.problem:
            lines.append(f"| {cell(suite.label)} | {word} | {numbers['passed']} | {numbers['failed']} "
                         f"| {numbers['errors']} | {numbers['skipped']} |")
        else:
            lines.append(f"| {cell(suite.label)} | {word} | | | | |")
    counts = Counter(COMPARISON_GROUP.get(r.get("status"), "within") for r in report.comparisons)
    remint = (f" Re-mint: {counts['reminted']} baselines replaced, {counts['unchanged']} kept."
              if counts["reminted"] or counts["unchanged"] else "")
    if counts["minted"]:
        remint += f" Minted: {counts['minted']} new baselines."
    if report.pairs:
        remint += f" Interaction pairs: {len(report.pairs)} steps."
    lines += ["", f"Screenshot comparisons: {len(report.comparisons)} recorded, "
              f"{counts['over']} over budget, {counts['missing']} without a baseline, "
              f"{counts['capture']} capture failures.{remint}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- page assets

CSS = """
:root{--bg:#f5f6f8;--panel:#fff;--text:#1c2230;--muted:#5d6676;--line:#dce0e7;--code:#eef1f5;
--pass:#1a7f37;--fail:#c62828;--warn:#9a5b00;--skip:#687080;--accent:#2457d6;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--panel:#171b21;--text:#e5e8ee;--muted:#9aa3b1;
--line:#2a3039;--code:#0b0e12;--pass:#3fb950;--fail:#f47067;--warn:#d29922;--skip:#8b949e;--accent:#6ea8fe}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--accent)}
code,pre{font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:8px 10px;
overflow:auto;white-space:pre-wrap;word-break:break-word;margin:6px 0}
header.top,main,footer{max-width:1500px;margin:0 auto;padding:0 16px}
header.top{padding-top:18px}
.title-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
h1{font-size:22px;margin:0}
h2{font-size:18px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:0}
h4{font-size:13px;margin:0 0 4px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.meta{color:var(--muted);margin:6px 0}
nav{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 0}
.muted{color:var(--muted)}
.note{color:var(--warn)}
.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-block;border-radius:999px;padding:1px 9px;font-size:12px;font-weight:600;
border:1px solid currentColor;white-space:nowrap}
.badge.passed,.badge.success,.badge.within{color:var(--pass)}
.badge.failed,.badge.failure,.badge.error,.badge.over,.badge.unreadable{color:var(--fail)}
.badge.missing,.badge.capture,.badge.cancelled,.badge.unclear,.badge.timed_out{color:var(--warn)}
.badge.skipped,.badge.neutral,.badge.unknown,.badge.xfailed,.badge.unchanged{color:var(--skip)}
.badge.reminted,.badge.minted,.badge.closeup,.badge.interaction{color:var(--accent)}
table{border-collapse:collapse;width:100%;background:var(--panel);border:1px solid var(--line);border-radius:8px}
th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-size:12px;color:var(--muted);font-weight:600}
tr.failure td{background:color-mix(in srgb,var(--fail) 8%,transparent)}
.table-wrap{overflow-x:auto}
details>summary{cursor:pointer;color:var(--muted);margin:4px 0}
.steps-box>summary{font-weight:600}
.suite{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:14px 0}
.suite h3{display:flex;gap:10px;align-items:center}
.case{border-top:1px solid var(--line);padding:10px 0 4px;margin-top:8px}
.test-id{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-all}
.message{border-left:3px solid var(--fail)}
.problem{border-left:3px solid var(--warn)}
.failure-shot{margin:8px 0}
.tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:4px 0 8px}
.chip{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--text);
border-radius:999px;padding:3px 12px;cursor:pointer}
.chip[aria-pressed=true]{border-color:var(--accent);box-shadow:inset 0 0 0 1px var(--accent)}
#cmp-search{font:inherit;flex:1 1 220px;min-width:0;padding:5px 10px;border:1px solid var(--line);
border-radius:6px;background:var(--panel);color:var(--text)}
.legend{color:var(--muted);font-size:12px;display:flex;gap:6px 14px;flex-wrap:wrap;align-items:center}
.swatch{display:inline-block;width:12px;height:12px;border:1px solid var(--line);vertical-align:-2px}
.swatch.counted{background:#ff0000}.swatch.within{background:#ffbe3c}.swatch.same{background:#d9d9d9}
.swatch.volatile{background:#4682ff}
details.unchanged{margin:14px 0}
.cards{display:flex;flex-direction:column;gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;
content-visibility:auto;contain-intrinsic-size:auto 520px}
.card[hidden]{display:none}
.card-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card-head h3{font:600 13px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-all}
.card p{margin:6px 0}
.verdict{display:flex;gap:4px 14px;align-items:center;flex-wrap:wrap}
.meter-wrap{display:inline-flex;gap:8px;align-items:center}
.meter{display:inline-block;width:140px;height:8px;border-radius:4px;background:var(--code);
border:1px solid var(--line);overflow:hidden;vertical-align:middle}
.meter span{display:block;height:100%;background:var(--pass)}
.meter.near span{background:var(--warn)}.meter.over span{background:var(--fail)}
.meter-label,.facts{color:var(--muted);font-size:12px}
.trio{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:8px}
.trio figure{margin:0;min-width:0}
.pair-row{border-top:1px solid var(--line);padding-top:8px;margin-top:8px}
.pair-row h4 .muted{font-weight:400}
figcaption{font-size:12px;color:var(--muted);margin-top:3px;text-align:center}
.shot{display:block;width:100%;padding:0;border:1px solid var(--line);background:var(--code);cursor:zoom-in}
.shot img{display:block;width:100%;height:auto;max-height:70vh;object-fit:contain}
.failure-shot .shot{display:inline-block;width:min(100%,640px)}
.failure-shot .shot img{max-height:480px}
.placeholder{display:flex;align-items:center;justify-content:center;min-height:120px;height:100%;
border:1px dashed var(--line);color:var(--muted);font-size:12px;text-align:center;padding:8px}
footer{color:var(--muted);font-size:12px;padding-top:24px;padding-bottom:32px}
#viewer{position:fixed;inset:0;z-index:10;background:rgba(8,10,14,.94);display:flex;flex-direction:column}
#viewer[hidden]{display:none}
.viewer-bar{color:#e5e8ee;padding:8px 16px;font-size:13px;display:flex;gap:16px;flex-wrap:wrap}
.viewer-bar .hint{color:#9aa3b1}
.viewer-scroll{flex:1;overflow:auto}
.viewer-scroll img{display:block;margin:0 auto;max-width:none;max-height:none;width:auto;height:auto}
body.viewing{overflow:hidden}
"""

VIEWER = ('<div id="viewer" hidden tabindex="-1" role="dialog" aria-modal="true" aria-label="Image at original size">'
          '<div class="viewer-bar"><span class="viewer-caption"></span>'
          '<span class="hint">Original size. Arrow keys switch images, Esc or a click closes.</span></div>'
          '<div class="viewer-scroll"><img alt=""></div></div>')

JS = """
(() => {
  const cards = [...document.querySelectorAll('.cmp')];
  const chips = [...document.querySelectorAll('.chip')];
  const search = document.getElementById('cmp-search');
  let group = 'all';
  function filter() {
    const q = ((search && search.value) || '').trim().toLowerCase();
    for (const card of cards) {
      const inGroup = group === 'all' || card.dataset.group === group ||
                      (group === 'closeup' && card.dataset.closeup === '1') ||
                      (group === 'interaction' && card.dataset.interaction === '1');
      card.hidden = !(inGroup && (!q || card.dataset.search.includes(q)));
    }
  }
  for (const chip of chips) {
    chip.addEventListener('click', () => {
      group = chip.dataset.group;
      for (const c of chips) c.setAttribute('aria-pressed', String(c === chip));
      filter();
    });
  }
  if (search) search.addEventListener('input', filter);

  const viewer = document.getElementById('viewer');
  const big = viewer.querySelector('img');
  const caption = viewer.querySelector('.viewer-caption');
  const scroller = viewer.querySelector('.viewer-scroll');
  let set = [], at = 0, opener = null;
  function show(i) {
    at = (i + set.length) % set.length;
    const img = set[at];
    big.src = img.src;  // the same data URI string, not a second copy of it
    big.alt = img.alt;
    caption.textContent = img.dataset.caption || img.alt;
  }
  function close() {
    viewer.hidden = true;
    document.body.classList.remove('viewing');
    big.removeAttribute('src');
    if (opener) opener.focus();
  }
  document.addEventListener('click', (event) => {
    if (!viewer.hidden) { close(); return; }
    const button = event.target.closest('.shot');
    if (!button) return;
    const scope = button.closest('.trio') || button.closest('figure');
    set = [...scope.querySelectorAll('.shot img')];
    opener = button;
    show(set.indexOf(button.querySelector('img')));
    viewer.hidden = false;
    document.body.classList.add('viewing');
    scroller.scrollTo(0, 0);
    viewer.focus();
  });
  document.addEventListener('keydown', (event) => {
    if (viewer.hidden) return;
    if (event.key === 'Escape') close();
    else if (event.key === 'ArrowRight') show(at + 1);
    else if (event.key === 'ArrowLeft') show(at - 1);
    else return;
    event.preventDefault();
  });
})();
"""


# ---------------------------------------------------------------- cli


def _labelled(value):
    label, sep, path = value.partition("=")
    if not sep or not label or not path:
        raise argparse.ArgumentTypeError(f"expected LABEL=PATH, got {value!r}")
    return label, path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--junit", action="append", type=_labelled, default=[], metavar="LABEL=PATH")
    parser.add_argument("--jest", action="append", type=_labelled, default=[], metavar="LABEL=PATH")
    parser.add_argument("--tsc", action="append", type=_labelled, default=[], metavar="LABEL=PATH")
    parser.add_argument("--comparisons", metavar="DIR")
    parser.add_argument("--failures", metavar="DIR")
    parser.add_argument("--jobs", metavar="PATH", help="the jobs API response for this run attempt")
    parser.add_argument("--job-name", help="which job in --jobs is this one (default: $GITHUB_JOB)")
    parser.add_argument("--all-jobs", action="store_true",
                        help="report on every job in --jobs, not only this one")
    parser.add_argument("--out", required=True, metavar="PATH")
    parser.add_argument("--summary", metavar="PATH", help="also write a Markdown summary here")
    parser.add_argument("--max-image-mb", type=int, default=150,
                        help="leave images out past this much embedded data (default 150)")
    parser.add_argument("--workers", type=int, default=min(32, os.cpu_count() or 4))
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    report = build(args)
    page = render(report)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(page)
    if args.summary:
        with open(args.summary, "w", encoding="utf-8") as handle:
            handle.write(render_summary(report))
    kept = sum(1 for uri in report.images.values() if uri)
    print(f"wrote {args.out}: {len(page) / 1e6:.1f} MB, {len(report.suites)} suites, "
          f"{len(report.comparisons)} comparisons, {kept} images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
