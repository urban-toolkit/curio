"""The steps of the Skill evaluations workflow (``.github/workflows/skill-evals.yml``).

- ``mask``: on the runner, before anything prints, has GitHub mask the base
  URL's host and its host and port in the job's log, as it masks the secrets
  themselves. It prints only the ``::add-mask::`` commands GitHub reads.
- ``previous --out <folder>``: on the runner, the per-model summaries of the
  newest finished run of this workflow on main, from its
  ``skill-evals-summary`` artifact. The report compares with them. Nothing
  found is no failure.
- ``run --scope <file> --out <folder>``: in the CI image, on the branch's own
  code. It reads the models from ``CURIO_EVAL_MODELS`` (a JSON list) and the
  endpoint from ``CURIO_EVAL_BASE_URL`` and ``CURIO_EVAL_API_KEY``.
  1. Each model is probed with one short request, and one that does not
     answer is not run. So is ``CURIO_EVAL_GRADER_MODEL``, the benchmark's
     one grader for every model, when it names one: if it does not answer,
     no model runs.
  2. Each model that answered runs ``agent_eval.py skills --scope``, side by
     side, into ``results/<model>/``. Each runs ``CURIO_EVAL_JOBS`` workers,
     a number or a JSON object of a number per model, 4 when unset.
  3. The report (``scripts/skill_evals_report.py``) is written.
  4. Every file under the out folder is checked for the key, the base URL and
     its host.

  It fails on a probe that failed, a runner that failed, a run left in an
  error, a leak or a skill under its floor.

The key and the base URL go to the runners in their environment only. No
output names either, and every line a runner prints is scrubbed of both
before it reaches the log.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
#: Workers each model runs when CURIO_EVAL_JOBS does not say.
DEFAULT_JOBS = 4
#: What the probe asks, and how long it waits.
PROBE_MESSAGE = "Answer with the single word: ready."
PROBE_TIMEOUT_S = 90.0
PROBE_TRIES = 2
#: The artifact a run's per-model summaries go to, and this workflow's file.
SUMMARY_ARTIFACT = "skill-evals-summary"
WORKFLOW = "skill-evals.yml"

ENV_MODELS = "CURIO_EVAL_MODELS"
ENV_JOBS = "CURIO_EVAL_JOBS"
ENV_BASE_URL = "CURIO_EVAL_BASE_URL"
ENV_API_KEY = "CURIO_EVAL_API_KEY"
#: The benchmark's graders, which the workers read (``skill_eval_worker.ENV_GRADER``): one model, or a
#: JSON list of them in order, the best first. Each model is graded by the first that is not itself.
ENV_GRADER = "CURIO_EVAL_GRADER_MODEL"


def _say(text: str) -> None:
    print(text, flush=True)


# --- mask ----------------------------------------------------------------------------


def masks(base_url: str) -> list[str]:
    """What to mask of *base_url* besides the URL, a secret already: the URL
    without its last slash, its host and port, and its host."""
    parts = urlsplit(base_url.strip())
    found = [base_url.strip().rstrip("/"), parts.netloc, parts.hostname or ""]
    return sorted({value for value in found if value and value not in ("localhost", "127.0.0.1")},
                  key=len, reverse=True)


def cmd_mask(_args) -> int:
    for value in masks(os.environ.get(ENV_BASE_URL, "")):
        print(f"::add-mask::{value}", flush=True)
    return 0


# --- previous ------------------------------------------------------------------------


def _api(url: str, token: str, *, raw: bool = False):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    # Not sent on to where an artifact's download redirects, a signed URL of
    # its own that refuses a second credential.
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    return body if raw else json.loads(body)


def cmd_previous(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repo, token = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GH_TOKEN", "")
    try:
        listing = _api(f"{api}/repos/{repo}/actions/workflows/{WORKFLOW}/runs?branch=main&status=completed"
                       "&per_page=20", token)
        for run in listing.get("workflow_runs") or []:
            artifacts = _api(f"{api}/repos/{repo}/actions/runs/{run['id']}/artifacts?name={SUMMARY_ARTIFACT}",
                             token).get("artifacts") or []
            if not artifacts or artifacts[0].get("expired"):
                continue
            data = _api(artifacts[0]["archive_download_url"], token, raw=True)
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = [name for name in archive.namelist() if name.endswith(".json") and "/" not in name]
                for name in names:
                    (out / name).write_bytes(archive.read(name))
            _say(f"compared with run {run['id']} of {run.get('created_at')}: {len(names)} model(s)")
            return 0
        _say("no earlier run of the skills on main to compare with")
    except Exception as exc:  # noqa: BLE001 - nothing to compare with is no failure
        _say(f"no earlier run to compare with: {type(exc).__name__}")
    return 0


# --- run -----------------------------------------------------------------------------


def models_from(value: str) -> list[str]:
    """The models a ``CURIO_EVAL_MODELS`` value lists, in its order."""
    try:
        found = json.loads(value or "[]")
    except ValueError:
        raise ValueError(f"{ENV_MODELS} must be a JSON list of model names") from None
    if not isinstance(found, list) or not all(isinstance(name, str) and name.strip() for name in found):
        raise ValueError(f"{ENV_MODELS} must be a JSON list of model names")
    return list(dict.fromkeys(name.strip() for name in found))


def graders_from(value: str) -> list[str]:
    """The graders a ``CURIO_EVAL_GRADER`` value names, the best first: one
    model's name, or a JSON list of them."""
    value = (value or "").strip()
    if not value.startswith(("[", "{")):
        return [value] if value else []
    try:
        found = json.loads(value)
    except ValueError:
        raise ValueError(f"{ENV_GRADER} must be a model's name or a JSON list of them") from None
    if not isinstance(found, list) or not all(isinstance(name, str) and name.strip() for name in found):
        raise ValueError(f"{ENV_GRADER} must be a model's name or a JSON list of them")
    return list(dict.fromkeys(name.strip() for name in found))


def grader_for(model: str, graders: list[str]) -> str | None:
    """Who grades *model*'s answers: the first of *graders* that is not
    *model*, since no model grades its own when another is named; None,
    when no other is named, for the model itself."""
    return next((grader for grader in graders if grader != model), None) if graders else None


def jobs_for(value: str, model: str) -> int:
    """How many workers *model* runs, from a ``CURIO_EVAL_JOBS`` value: a
    number for every model, or an object of a number per model (``default``
    for the others)."""
    value = (value or "").strip()
    if not value:
        return DEFAULT_JOBS
    found = json.loads(value)
    if isinstance(found, dict):
        found = found.get(model, found.get("default", DEFAULT_JOBS))
    if not isinstance(found, int) or isinstance(found, bool) or found < 1:
        raise ValueError(f"{ENV_JOBS} must be a whole number above 0, or an object of them per model")
    return found


def probe(model: str, base_url: str, api_key: str, scrub) -> dict:
    """Whether *model* answers one short request: ``ok``, the seconds it took, and the error it gave."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=PROBE_TIMEOUT_S, max_retries=0)
    error = ""
    for attempt in range(1, PROBE_TRIES + 1):
        started = time.monotonic()
        try:
            client.chat.completions.create(model=model, messages=[{"role": "user", "content": PROBE_MESSAGE}],
                                           max_tokens=256)
            return {"ok": True, "seconds": round(time.monotonic() - started, 2), "attempts": attempt}
        except Exception as exc:  # noqa: BLE001 - every failure is the answer here
            status = getattr(exc, "status_code", None)
            error = scrub(f"{type(exc).__name__}{f' {status}' if status else ''}: {exc}")[:300]
        if attempt < PROBE_TRIES:
            time.sleep(15)
    return {"ok": False, "error": error, "attempts": PROBE_TRIES}


def _stream(process: subprocess.Popen, prefix: str, scrub) -> None:
    for line in process.stdout:
        print(f"[{prefix}] {scrub(line.rstrip())}", flush=True)


def _limits() -> str:
    """The container's memory limit and CPUs, for the log."""
    try:
        memory = Path("/sys/fs/cgroup/memory.max").read_text(encoding="utf-8").strip()
    except OSError:
        memory = "unknown"
    if memory.isdigit():
        memory = f"{int(memory) / 2**30:.1f} GiB"
    return f"memory limit {memory}, {os.cpu_count()} CPUs"


def cmd_run(args) -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from utk_curio.backend.app.agents.evaluation import skill_evals
    from utk_curio.backend.app.agents.evaluation.report import scrub as scrub_text

    sys.path.insert(0, str(HERE))
    import skill_evals_report as report

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scope = json.loads(Path(args.scope).read_text(encoding="utf-8"))
    (out / "scope.json").write_text(json.dumps(scope, indent=2) + "\n", encoding="utf-8")
    if scope.get("error"):
        print(f"FAILED: the run's scope could not be read: {scope['error']}", file=sys.stderr)
        return 1
    base_url, api_key = os.environ.get(ENV_BASE_URL, "").strip(), os.environ.get(ENV_API_KEY, "").strip()
    if not base_url or not api_key:
        print(f"FAILED: {ENV_BASE_URL} and {ENV_API_KEY} are not set. A pull request from a fork, or one "
              "Dependabot opens, gets no secrets: push the branch to this repository and dispatch the Full stack "
              "build on it with skill_evals.", file=sys.stderr)
        return 1
    try:
        models = models_from(os.environ.get(ENV_MODELS, ""))
        jobs = {model: jobs_for(os.environ.get(ENV_JOBS, ""), model) for model in models}
        graders = graders_from(os.environ.get(ENV_GRADER, ""))
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    if not models:
        print(f"FAILED: the repository variable {ENV_MODELS} lists no model", file=sys.stderr)
        return 1
    secrets = skill_evals.Endpoint(base_url=base_url, api_key=api_key, model=models[0]).secrets()

    def scrub(text: str) -> str:
        return scrub_text(text, values=secrets)

    grader_of = {model: grader_for(model, graders) for model in models}
    asked = list(dict.fromkeys([*models, *(grader for grader in grader_of.values() if grader)]))
    said = "; ".join(f"{model} by {grader_of[model] or 'itself'}" for model in models)
    _say(f"{len(models)} model(s), each graded: {said}; "
         f"{len(scope.get('measures') or {})} skill(s) measured; {_limits()}")
    with ThreadPoolExecutor(max_workers=len(asked)) as pool:
        probes = dict(zip(asked, pool.map(lambda model: probe(model, base_url, api_key, scrub), asked)))
    for model, answer in probes.items():
        _say(f"probe {model}: " + (f"answered in {answer['seconds']} s" if answer["ok"]
                                   else f"FAILED, {answer['error']}"))
    for model, grader in grader_of.items():
        if grader and not probes[grader]["ok"] and probes[model]["ok"]:
            # Every grade of its answers would fail: it does not run.
            probes[model] = {"ok": False, "error": f"its grader, {grader}, did not answer its probe"}

    env = {key: value for key, value in os.environ.items() if key not in (ENV_MODELS, ENV_JOBS)}
    processes: dict[str, subprocess.Popen] = {}
    threads = []
    for model in models:
        if not probes[model]["ok"]:
            continue
        folder = out / "results" / report.slug(model)
        folder.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(REPO_ROOT / "utk_curio" / "tools" / "agent_eval.py"), "skills",
                   "--scope", str(out / "scope.json"), "--jobs", str(jobs[model]), "--out", str(folder)]
        own = {"CURIO_EVAL_MODEL": model, ENV_GRADER: grader_of[model] or ""}
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding="utf-8", cwd=REPO_ROOT, env={**env, **own})
        processes[model] = process
        thread = threading.Thread(target=_stream, args=(process, report.slug(model), scrub), daemon=True)
        thread.start()
        threads.append(thread)
    exits = {model: process.wait() for model, process in processes.items()}
    for thread in threads:
        thread.join()

    runs, problems = report.build(out, models, scope=scope, probes=probes, exits=exits,
                                  previous=Path(args.previous) if args.previous else None,
                                  run_url=os.environ.get("CURIO_EVAL_RUN_URL") or None)
    endpoint = skill_evals.Endpoint(base_url=base_url, api_key=api_key, model=models[0])
    leaked = skill_evals.leaks(out, endpoint)
    if leaked:
        problems.append(f"{len(leaked)} file(s) hold the key, the base URL or its host: {', '.join(leaked[:5])}")
    _say((out / report.SUMMARY).read_text(encoding="utf-8"))
    if problems:
        print("FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    _say(f"passed: {sum(run.runs for run in runs)} runs on {len(runs)} model(s), no file holds the endpoint")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mask", help="mask the base URL's host in the job's log").set_defaults(func=cmd_mask)
    previous = sub.add_parser("previous", help="fetch main's last per-model summaries")
    previous.add_argument("--out", required=True)
    previous.set_defaults(func=cmd_previous)
    run = sub.add_parser("run", help="probe, run and report every model")
    run.add_argument("--scope", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--previous", default=None)
    run.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
