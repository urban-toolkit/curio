"""The Weekly flake hunt's report, on the hunt's own run page.

weekly-flake-hunt.yml dispatches the Full stack build on main with repeat 10,
then runs this. It finds every run the hunt started (a workflow_dispatch of
docker-compose.yml on main, by github-actions[bot], created since the hunt
began), waits for them to end, and writes one Markdown summary: for each run
its link, attempts, result, length, jobs by outcome and CI report page, then
the jobs that did not pass, each linked, and the summary that run's ci-report
wrote (its ci-summary artifact: the flaky tests and the suite table). It exits 1 when a run did not pass or found a
flaky test, so the hunt's own run is red that week.

    python3 scripts/ci_weekly_report.py --since <ISO time> --out <summary.md>
    python3 scripts/ci_weekly_report.py --run <id> [--run <id> ...] --out <summary.md>

--run reports on the given runs at once, without looking for them or waiting.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime

WORKFLOW = "docker-compose.yml"
BOT = "github-actions[bot]"
#: The header of the flaky-test table ci_report.py's render_summary writes.
FLAKY_HEADER = "| Suite | Test | Passed in runs | Failed in runs |"
#: Job outcomes the page does not name: every other job is listed under its run.
PASSED = frozenset({"success", "skipped"})


class Api:
    def __init__(self, api: str, repo: str, token: str):
        self.base, self.token = f"{api}/repos/{repo}/", token

    def _open(self, path: str):
        request = urllib.request.Request(self.base + path, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        return urllib.request.urlopen(request, timeout=60)

    def json(self, path: str) -> dict:
        for attempt in range(3):
            try:
                with self._open(path) as response:
                    return json.load(response)
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(10)
        return None

    def bytes(self, path: str) -> bytes:
        """An artifact's zip. The API answers with a redirect to storage, which
        refuses a request that still carries the token, so the redirect is
        followed by hand, without it."""
        opener = urllib.request.build_opener(_KeepRedirect)
        request = urllib.request.Request(self.base + path, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        })
        try:
            with opener.open(request, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise
            location = exc.headers["Location"]
        with urllib.request.urlopen(location, timeout=120) as response:
            return response.read()


class _KeepRedirect(urllib.request.HTTPRedirectHandler):
    """Hands a redirect back as an HTTPError instead of following it."""

    def redirect_request(self, *args, **kwargs):
        return None


def started_runs(fetch, since: str) -> list[dict]:
    """The Full stack build runs the hunt dispatched: on main, by the bot, created since ``since``."""
    found = fetch(f"actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&branch=main"
                  f"&created=%3E%3D{since}&per_page=50")
    runs = [run for run in found.get("workflow_runs", [])
            if (run.get("triggering_actor") or run.get("actor") or {}).get("login") == BOT
            and run.get("created_at", "") >= since]
    return sorted(runs, key=lambda run: run["created_at"])


def wait_for(fetch, ids, poll: float, deadline: float, sleep=time.sleep, clock=time.time) -> list[dict]:
    """Each run once it has ended, or as it is when ``deadline`` (a ``clock`` time) passes."""
    while True:
        runs = [fetch(f"actions/runs/{run_id}") for run_id in ids]
        if all(run.get("status") == "completed" for run in runs) or clock() >= deadline:
            return runs
        sleep(poll)


def _hours(run: dict) -> str:
    try:
        start = datetime.fromisoformat(run["run_started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(run["updated_at"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        return ""
    return f"{(end - start).total_seconds() / 3600:.1f} h"


def jobs_by_outcome(fetch, run_id) -> tuple[Counter, list[str]]:
    """The run's jobs counted by outcome, and each job that did not pass as a linked name."""
    outcomes, not_passed, page = Counter(), [], 1
    while True:
        jobs = fetch(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100&page={page}").get("jobs", [])
        for job in jobs:
            outcome = job.get("conclusion") or job.get("status") or "unknown"
            outcomes[outcome] += 1
            if outcome not in PASSED:
                name = job.get("name", "unnamed job")
                link = f"[{name}]({job['html_url']})" if job.get("html_url") else name
                not_passed.append(f"{link} ({outcome})")
        if len(jobs) < 100:
            return outcomes, not_passed
        page += 1


def run_section(fetch, fetch_bytes, run: dict) -> dict:
    """What the report says of one run, and whether it counts against the week."""
    artifacts = fetch(f"actions/runs/{run['id']}/artifacts?per_page=100").get("artifacts", [])
    newest = {}
    for artifact in artifacts:
        name = artifact.get("name", "")
        if not artifact.get("expired") and (name not in newest or artifact["created_at"] > newest[name]["created_at"]):
            newest[name] = artifact
    summary = ""
    if "ci-summary" in newest:
        blob = fetch_bytes(f"actions/artifacts/{newest['ci-summary']['id']}/zip")
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            summary = archive.read("summary.md").decode("utf-8")
    pages = sorted((a for name, a in newest.items() if name.startswith("curio-ci-report")),
                   key=lambda a: a["created_at"])
    page = f"{run['html_url']}/artifacts/{pages[-1]['id']}" if pages else ""
    outcomes, not_passed = jobs_by_outcome(fetch, run["id"])
    return {
        "run": run, "summary": summary, "page": page,
        "jobs": outcomes, "not_passed": not_passed,
        "flaky": FLAKY_HEADER in summary,
        "passed": run.get("status") == "completed" and run.get("conclusion") == "success",
    }


def render(sections: list[dict], since: str) -> str:
    lines = [f"## Weekly flake hunt, from {since}", ""]
    if not sections:
        return "\n".join(lines + [f"No Full stack build run started by {BOT} on main since {since}.", ""])
    lines += ["| Run | Attempts | Result | Length | Jobs | CI report |", "| --- | ---: | --- | ---: | --- | --- |"]
    for section in sections:
        run = section["run"]
        result = run.get("conclusion") or run.get("status", "")
        jobs = ", ".join(f"{count} {outcome}" for outcome, count in section["jobs"].most_common())
        page = f"[page]({section['page']})" if section["page"] else "none"
        lines.append(f"| [{run['id']}]({run['html_url']}) | {run.get('run_attempt', 1)} | {result} "
                     f"| {_hours(run)} | {jobs} | {page} |")
    for section in sections:
        lines += ["", f"### Run {section['run']['id']}", ""]
        if section["not_passed"]:
            lines += ["**Jobs that did not pass:** " + ", ".join(section["not_passed"]), ""]
        lines.append(section["summary"].strip() or "No summary: the run's ci-report uploaded no ci-summary.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None, environ=os.environ, sleep=time.sleep, clock=time.time) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="when the hunt began, ISO 8601 UTC")
    parser.add_argument("--run", action="append", default=[], help="report on this run at once")
    parser.add_argument("--out", required=True, help="where to append the Markdown summary")
    parser.add_argument("--poll", type=float, default=300.0, help="seconds between looks")
    parser.add_argument("--hours", type=float, default=11.5, help="how long to wait for the runs")
    args = parser.parse_args(argv)
    if not (args.since or args.run):
        parser.error("give --since or --run")

    api = Api(environ.get("GITHUB_API_URL", "https://api.github.com"), environ["GITHUB_REPOSITORY"],
              environ.get("GH_TOKEN") or environ["GITHUB_TOKEN"])
    deadline = clock() + args.hours * 3600
    if args.run:
        ids = args.run
    else:
        # The dispatch makes its run a moment later: look for up to ten minutes.
        ids = []
        for _ in range(20):
            ids = [run["id"] for run in started_runs(api.json, args.since)]
            if ids:
                break
            sleep(30)
        print(f"runs the hunt started: {ids or 'none'}", flush=True)
    runs = wait_for(api.json, ids, args.poll, deadline, sleep, clock) if ids and not args.run else \
        [api.json(f"actions/runs/{run_id}") for run_id in ids]
    sections = [run_section(api.json, api.bytes, run) for run in runs]
    with open(args.out, "a", encoding="utf-8") as handle:
        handle.write(render(sections, args.since or "the given runs"))
    week_red = not sections or any(not s["passed"] or s["flaky"] for s in sections)
    for section in sections:
        state = "passed" if section["passed"] else (section["run"].get("conclusion") or "still running")
        print(f"run {section['run']['id']}: {state}{', flaky tests' if section['flaky'] else ''}")
    return 1 if week_red else 0


if __name__ == "__main__":
    sys.exit(main())
