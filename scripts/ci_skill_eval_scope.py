"""Say what a run of the Skill evaluations workflow measures: what its scope asks, or what the branch changes against main.

The Skill evaluations workflow (``.github/workflows/skill-evals.yml``), started
by hand, runs each skill's ``evals/evals.json`` on the models of the
repository variable ``CURIO_EVAL_MODELS`` (``agent_eval.py skills --scope``).
What it runs is this script's answer, a scope. With its ``scope`` input
``auto``, that is what the branch changes against main:

- **A changed skill** (any file of its folder, ``skills/<name>/`` or
  ``packages/<package>/skills/<name>/``): its test cases, 3 runs with the
  skill and 3 without. Its trigger queries too when the skill is new, its
  ``description`` changed or its trigger queries did.
- **A core skill or the page that places it** (a page of the base entry of
  ``agents/`` that holds ``{{skill:<name>}}``, the preamble): every skill's
  test cases, 3 runs both ways, since every prompt holds them. A change to a
  core skill's ``evals/`` alone, which no prompt holds, measures that skill
  as any other.
- **Agent text or code** (``agents/``, the agents' backend, the evaluation
  tools, the package manifests whose descriptions prompts list, the Trill
  schema, this node's own files): every other skill's first test case, once,
  with the skill.
- **Anything else:** nothing, and the run measures nothing.

The other values of the input ask for a measure outright: ``none``, ``smoke``
(every skill's first test case, once), ``core`` (every skill's test cases),
``full`` (every skill's trigger queries and test cases), ``graders`` (each
model grades the prepared answers of every skill's ``evals/truth.json``, the
grader truth, once) or skill names, comma-separated. A ``tmp/`` branch's
``auto`` measures nothing, and so does any event but a dispatch.

The scope is JSON: ``measure`` (the widest of the above it holds), ``why``
(one line per reason) and ``measures``, each skill's measure as
``skill_evals.Measure`` reads it. With ``--github`` it goes to the step's
``skill_evals`` output, compact, or empty when it measures nothing, and its
reasons to the job summary. A scope that cannot be read holds ``error``, and
the run fails saying it.

    python3 scripts/ci_skill_eval_scope.py --github
    python3 scripts/ci_skill_eval_scope.py --base 5f7e14ba09 --head HEAD

It needs only the standard library, so it runs on the runner's Python. On
GitHub it reads what the branch changes from the compare API, as a dispatch
checks out only its branch's commit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The kinds of run and the two conditions, as ``skill_evals`` names them.
TRIGGER, TASK, GRADE = "trigger", "task", "grade"
WITH_SKILL, WITHOUT_SKILL = "with_skill", "without_skill"
#: Runs of each query and test case a whole measure makes (``skill_evals.RUNS``).
RUNS = 3

#: A skill's trigger queries and test cases, 3 runs both ways.
WHOLE = {"kinds": [TRIGGER, TASK], "runs": RUNS, "conditions": [WITH_SKILL, WITHOUT_SKILL], "cases": None}
#: Its test cases alone, 3 runs both ways.
CASES = {"kinds": [TASK], "runs": RUNS, "conditions": [WITH_SKILL, WITHOUT_SKILL], "cases": None}
#: Its first test case, once, with the skill.
SMOKE = {"kinds": [TASK], "runs": 1, "conditions": [WITH_SKILL], "cases": 1}
#: Each prepared answer of its grader truth, graded once by the model measured.
GRADERS = {"kinds": [GRADE], "runs": 1, "conditions": [WITH_SKILL], "cases": None}
#: The file of a skill's ``evals/`` folder that holds its grader truth (``grader_truth.TRUTH_FILE``).
TRUTH_FILE = "truth.json"

#: The measures from the narrowest, so the widest a scope holds names it.
ORDER = ("none", "smoke", "changed", "core", "full")

#: Paths whose change is agent text or code: every skill's smoke case.
AGENT_PATHS = (
    re.compile(r"^agents/"),
    re.compile(r"^skills/[^/]+$"),
    re.compile(r"^utk_curio/backend/app/agents/"),
    re.compile(r"^utk_curio/tools/(agent_eval|skill_eval_[a-z_]+|skill_benchmark)\.py$"),
    re.compile(r"^packages/[^/]+/manifest\.json$"),
    re.compile(r"^docs/schemas/trill\.v1\.json$"),
    re.compile(r"^scripts/(ci_skill_eval[a-z_]*|skill_eval[a-z_]*)\.(py|json)$"),
    re.compile(r"^\.github/workflows/skill-evals\.yml$"),
)
#: A skill's folder in a path: ``skills/<name>/`` or ``packages/<package>/skills/<name>/``.
SKILL_PATH = re.compile(r"^(?:packages/[^/]+/)?skills/([^/]+)/")
#: How a page places a skill's body.
PLACED = re.compile(r"\{\{skill:([a-z0-9-]+)\}\}")


@dataclass(frozen=True)
class Change:
    """One changed file: ``A``, ``M``, ``D`` (added, modified, deleted), and its path."""

    status: str
    path: str


def skills_with_evals(root: Path) -> dict[str, str]:
    """Every skill in *root* that holds ``evals/evals.json``, by name: its folder, relative to *root*."""
    found: dict[str, str] = {}
    for pattern in ("skills/*/evals/evals.json", "packages/*/skills/*/evals/evals.json"):
        for path in sorted(root.glob(pattern)):
            folder = path.parent.parent
            found.setdefault(folder.name, folder.relative_to(root).as_posix())
    return found


def base_entry(root: Path) -> Path | None:
    """The base entry of ``agents/``: the folder whose manifest's kind is ``base``."""
    for manifest in sorted(root.glob("agents/*/manifest.json")):
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("kind") == "base":
                return manifest.parent
        except (OSError, ValueError):
            continue
    return None


def core(root: Path) -> tuple[set[str], set[str]]:
    """The base entry's pages that place a skill (``{{skill:<name>}}``), by
    their paths, and the skills they place: what every prompt holds."""
    entry = base_entry(root)
    pages: set[str] = set()
    placed: set[str] = set()
    if entry is None:
        return pages, placed
    for page in sorted(entry.glob("*.md")):
        if page.name == "README.md":
            continue
        names = PLACED.findall(page.read_text(encoding="utf-8"))
        if names:
            pages.add(page.relative_to(root).as_posix())
            placed.update(names)
    return pages, placed


def description(text: str | None) -> str | None:
    """A ``SKILL.md``'s ``description``, its lines joined, or None."""
    if not text or not text.startswith("---"):
        return None
    head = text.split("\n---", 1)[0]
    lines = head.splitlines()[1:]
    for at, line in enumerate(lines):
        if line.startswith("description:"):
            value = [line[len("description:"):].strip()]
            for more in lines[at + 1:]:
                if more and not more[0].isspace():
                    break
                value.append(more.strip())
            words = " ".join(part for part in value if part not in (">", ">-", "|", "|-"))
            return " ".join(words.split())
    return None


def trigger_queries(text: str | None):
    """An ``evals.json``'s ``trigger_queries``, or None."""
    try:
        data = json.loads(text) if text else None
    except ValueError:
        return None
    return data.get("trigger_queries") if isinstance(data, dict) else None


def _in_evals(path: str) -> bool:
    """Whether *path* is in its skill's ``evals/`` folder, which no run is offered."""
    found = SKILL_PATH.match(path)
    return bool(found) and path[found.end():].startswith("evals/")


def _wider(measure: dict, other: dict) -> dict:
    """The wider of two measures of one skill."""
    rank = (WHOLE, CASES, SMOKE)
    return min(measure, other, key=lambda found: rank.index(found) if found in rank else len(rank))


def _all(names: Iterable[str], measure: dict) -> dict[str, dict]:
    return {name: dict(measure) for name in names}


def from_changes(changes: Iterable[Change], *, root: Path, old_text: Callable[[str], str | None],
                 new_text: Callable[[str], str | None] | None = None) -> dict:
    """The scope of a run that changes *changes*, the checkout of its commit at
    *root*, and *old_text* reading a path as main has it (None if absent).
    *new_text* reads a path as the run has it, from *root* when not given."""
    changes = list(changes)
    if new_text is None:
        def new_text(path: str) -> str | None:
            file = root / path
            return file.read_text(encoding="utf-8") if file.is_file() else None
    evals = skills_with_evals(root)
    core_pages, core_skills = core(root)
    measures: dict[str, dict] = {}
    why: list[str] = []
    widest = "none"

    def measure(name: str, found: dict) -> None:
        measures[name] = _wider(measures[name], found) if name in measures else dict(found)

    def reach(word: str) -> None:
        nonlocal widest
        widest = max(widest, word, key=ORDER.index)

    changed_skills: dict[str, list[Change]] = {}
    agent = []
    for change in changes:
        found = SKILL_PATH.match(change.path)
        if found:
            changed_skills.setdefault(found.group(1), []).append(change)
        elif change.path in core_pages:
            why.append(f"{change.path} places the core skills, which every prompt holds")
            reach("core")
        elif any(pattern.match(change.path) for pattern in AGENT_PATHS):
            agent.append(change.path)

    for name, mine in sorted(changed_skills.items()):
        # A core skill's own evaluations are in no prompt: they measure it alone.
        if name in core_skills and any(not _in_evals(change.path) for change in mine):
            why.append(f"{name} is a core skill, which every prompt holds")
            reach("core")
            continue
        if name not in evals:
            gone = all(change.status == "D" for change in mine)
            why.append(f"{name} changed but {'is gone' if gone else 'holds no evals/evals.json'}, so it is not measured")
            continue
        folder = evals[name]
        skill_file, evals_json = f"{folder}/SKILL.md", f"{folder}/evals/evals.json"
        new_skill = old_text(skill_file) is None
        now, evals_now = new_text(skill_file), new_text(evals_json)
        if new_skill:
            reason = "is new"
        elif description(old_text(skill_file)) != description(now):
            reason = "changed its description"
        elif trigger_queries(old_text(evals_json)) != trigger_queries(evals_now):
            reason = "changed its trigger queries"
        else:
            reason = ""
        if reason:
            why.append(f"{name} {reason}: its trigger queries and test cases, {RUNS} runs both ways")
            measure(name, WHOLE)
        else:
            why.append(f"{name} changed: its test cases, {RUNS} runs both ways")
            measure(name, CASES)
        reach("changed")

    if widest == "core":
        for name in evals:
            measure(name, CASES)
    if agent:
        shown = ", ".join(agent[:3]) + (f" and {len(agent) - 3} more" if len(agent) > 3 else "")
        why.append(f"agent text or code changed ({shown}): each other skill's first test case, once")
        for name in evals:
            measure(name, SMOKE)
        reach("smoke")
    if not measures:
        why.append("nothing an agent reads changed")
    return {"version": 1, "measure": widest if measures else "none", "why": why, "measures": measures}


def from_input(value: str, *, root: Path) -> dict | None:
    """The scope a dispatch's ``skill_evals`` input asks for, or None for ``auto``."""
    value = (value or "auto").strip()
    evals = skills_with_evals(root)
    if value == "auto":
        return None
    if value == "none":
        return {"version": 1, "measure": "none", "why": ["the dispatch asked for none"], "measures": {}}
    if value == "graders":
        truth = [name for name, folder in evals.items() if (root / folder / "evals" / TRUTH_FILE).is_file()]
        return {"version": 1, "measure": "graders",
                "why": ["the dispatch asked for the graders: each model grades the grader truth's answers",
                        f"{len(truth)} skill(s) hold a grader truth"],
                "measures": _all(truth, GRADERS)}
    asked = {"smoke": SMOKE, "core": CASES, "full": WHOLE}
    if value in asked:
        return {"version": 1, "measure": value, "why": [f"the dispatch asked for {value}"],
                "measures": _all(evals, asked[value])}
    names = [name.strip() for name in value.removeprefix("skills:").split(",") if name.strip()]
    unknown = [name for name in names if name not in evals]
    if unknown:
        raise ValueError(f"no skill holds evals/evals.json named {', '.join(unknown)}")
    return {"version": 1, "measure": "changed", "why": [f"the dispatch asked for {', '.join(names)}"],
            "measures": _all(names, WHOLE)}


def nothing(reason: str) -> dict:
    return {"version": 1, "measure": "none", "why": [reason], "measures": {}}


def for_event(*, event: str, ref: str, value: str, root: Path,
              changes: Callable[[], tuple[list[Change], Callable[[str], str | None]]]) -> dict:
    """The scope of a run of *event* on *ref*: what its dispatch's scope input
    asks, or for ``auto``, what *changes* (the changes and the reader of
    main's text) come to."""
    if event != "workflow_dispatch":
        return nothing(f"a {event or 'run'} event measures nothing: the workflow measures when it is started")
    asked = from_input(value, root=root)
    if asked is not None:
        return asked
    if ref.startswith("tmp/"):
        return nothing("a tmp/ before-run measures nothing")
    found, old_text = changes()
    return from_changes(found, root=root, old_text=old_text)


# --- Reading what a run changes -----------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True).stdout


def _shown(commit: str) -> Callable[[str], str | None]:
    """A reader of *commit*'s files, from git: None for a file it does not have."""
    def text(path: str) -> str | None:
        try:
            return _git("show", f"{commit}:{path}")
        except subprocess.CalledProcessError:
            return None

    return text


def git_changes(base: str, head: str) -> tuple[list[Change], Callable[[str], str | None]]:
    """What *head* changes against *base*, and a reader of *base*'s files, from git."""
    found = []
    for line in _git("diff", "--name-status", "--no-renames", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            found.append(Change(status=parts[0][:1], path=parts[-1]))
    return found, _shown(base)


#: The compare API lists at most this many files; a branch that changes more is measured as core.
COMPARE_FILES = 300


def _api(url: str, *, raw: bool = False):
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return body.decode("utf-8") if raw else json.loads(body)


def compare_changes(sha: str) -> tuple[list[Change], Callable[[str], str | None]]:
    """What *sha* changes against its merge base with main, and a reader of
    the merge base's files, from the GitHub API (a dispatch has only its own
    commit checked out)."""
    api, repo = os.environ.get("GITHUB_API_URL", "https://api.github.com"), os.environ["GITHUB_REPOSITORY"]
    compared = _api(f"{api}/repos/{repo}/compare/main...{sha}")
    base = compared["merge_base_commit"]["sha"]
    files = compared.get("files") or []
    if len(files) >= COMPARE_FILES:
        raise _TooMany(len(files))
    statuses = {"added": "A", "removed": "D"}
    found = [Change(status=statuses.get(item.get("status"), "M"), path=item["filename"]) for item in files]

    def old_text(path: str) -> str | None:
        try:
            return _api(f"{api}/repos/{repo}/contents/{path}?ref={base}", raw=True)
        except Exception:  # noqa: BLE001 - absent at the base, as git show says
            return None

    return found, old_text


class _TooMany(Exception):
    pass


def _github(scope: dict) -> None:
    measured = scope.get("measures") or scope.get("error")
    value = json.dumps(scope, separators=(",", ":")) if measured else ""
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as sink:
        sink.write(f"skill_evals={value}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["## Skill evaluations", "",
                 f"What this run measures: **{scope.get('measure', 'error')}**, "
                 f"{len(scope.get('measures') or {})} skill(s).", ""]
        lines += [f"- {line}" for line in scope.get("why") or []]
        if scope.get("error"):
            lines.append(f"- the scope could not be read: {scope['error']}")
        with open(summary, "a", encoding="utf-8") as sink:
            sink.write("\n".join(lines) + "\n\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--github", action="store_true",
                        help="read the run from GitHub's variables and write the step's output and summary")
    parser.add_argument("--base", help="without --github: the commit to compare with (main's)")
    parser.add_argument("--head", default="HEAD", help="without --github: the commit measured")
    parser.add_argument("--input", default="auto", help="without --github: a dispatch's scope input")
    args = parser.parse_args(argv)
    if not args.github:
        asked = from_input(args.input, root=REPO_ROOT)
        if asked is None:
            if not args.base:
                parser.error("--base is needed to read what the head changes")
            found, old_text = git_changes(args.base, args.head)
            asked = from_changes(found, root=REPO_ROOT, old_text=old_text, new_text=_shown(args.head))
        print(json.dumps(asked, indent=2))
        return 0
    try:
        try:
            scope = for_event(
                event=os.environ.get("GITHUB_EVENT_NAME", ""), ref=os.environ.get("HEAD_REF", ""),
                value=os.environ.get("SKILL_EVALS", "auto"), root=REPO_ROOT,
                changes=lambda: compare_changes(os.environ["GITHUB_SHA"]),
            )
        except _TooMany as many:
            scope = from_input("core", root=REPO_ROOT)
            scope["why"] = [f"the branch changes {many.args[0]} files or more, more than the compare API lists, "
                            "so every skill's test cases are measured"]
    except Exception as exc:  # noqa: BLE001 - a scope that cannot be read is written down for the run to fail on
        scope = {"version": 1, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(scope, indent=2))
    _github(scope)
    return 0


if __name__ == "__main__":
    sys.exit(main())
