"""Skill evaluations, as agentskills.io describes them: what each skill's ``evals/evals.json`` holds, and how its runs are counted.

A skill's folder may hold ``evals/evals.json``
(https://agentskills.io/skill-creation/evaluating-skills), which its listing
leaves out (``domain/skills.py``), so no run is offered it:

- ``skill_name``: the skill's name, its folder's.
- ``evals``: test cases, each an ``id``, a ``prompt`` (a realistic user
  message), an ``expected_output`` (what success looks like) and
  ``assertions`` (what a grader checks the answer against).
- ``trigger_queries``, for a skill a chat loads with ``skill.read``: about
  twenty queries, each a ``query`` and whether it ``should_trigger`` the
  skill, half of each (https://agentskills.io/skill-creation/optimizing-descriptions).

Curio's own fields say where a test case runs, at the top level and on any
test case: ``agent``, the agent whose chat runs it (``<id>@<major>``);
``dataflow``, the dataflow its project starts as (a path in Curio's shipped
folders, or in the skill's folder when it starts with ``evals/``); and
``target``, what the agent is attached to (``{"kind": "canvas"}``, the
default, or ``{"kind": "node", "node": <id>}``).

``agent_eval.py skills`` runs each trigger query and each test case three
times (:data:`RUNS`):

- **Trigger rate:** a query's runs that loaded the skill, of its runs. A
  query that should trigger passes above :data:`THRESHOLD`, one that should
  not below it.
- **Task result:** each test case with the skill (``with_skill``: the agent
  as Curio ships it) and without it (``without_skill``: the same agent with
  the skill taken out of every run's skills: its catalog, what it is handed
  and its preamble). A grader checks each answer against the assertions, and
  ``benchmark.json`` sets the two side by side.

A run that failed (an error) is counted apart: it is left out of every rate.

The endpoint is read from three variables, :data:`ENV_BASE_URL`,
:data:`ENV_API_KEY` and :data:`ENV_MODEL`. Nothing is written with the key
or the base URL: every output is scrubbed of them (:meth:`Endpoint.secrets`),
and :func:`leaks` reads each output file again for them.
"""

from __future__ import annotations

import json
import os
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from utk_curio import shipped
from utk_curio.backend.app.agents.domain import skills as skill_format

#: The file of a skill's ``evals/`` folder that holds its evaluations.
EVALS_FILE = "evals.json"
#: How many times each query and each test case runs, in each condition.
RUNS = 3
#: The trigger rate a query that should trigger passes above, and one that
#: should not passes below.
THRESHOLD = 0.5
#: The two conditions a test case runs in.
WITH_SKILL = "with_skill"
WITHOUT_SKILL = "without_skill"
CONDITIONS = (WITH_SKILL, WITHOUT_SKILL)
#: The two kinds of run.
TRIGGER = "trigger"
TASK = "task"
#: The variables the endpoint is read from.
ENV_BASE_URL = "CURIO_EVAL_BASE_URL"
ENV_API_KEY = "CURIO_EVAL_API_KEY"
ENV_MODEL = "CURIO_EVAL_MODEL"
#: What a run's agent is attached to when its test case names nothing.
CANVAS = "canvas"
NODE = "node"
#: Where a skill's own files for its evaluations start, in a ``dataflow`` path.
_OWN_PREFIX = f"{skill_format.EVALS_DIR}/"
#: Hosts a needle is not searched for by name alone: Curio's own text names them.
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


class EvalsError(ValueError):
    """An ``evals/evals.json`` that cannot be read, naming every problem."""


@dataclass(frozen=True)
class Context:
    """Where a run happens: the agent whose chat runs it, the dataflow its
    project starts as, and what the agent is attached to."""

    agent: str
    #: The dataflow's file, or None for an empty dataflow.
    dataflow: Path | None
    #: ``canvas``, or ``node`` with :attr:`node`.
    target: str = CANVAS
    node: str | None = None

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "dataflow": str(self.dataflow) if self.dataflow else None,
            "target": self.target,
            "node": self.node,
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "Context":
        dataflow = data.get("dataflow")
        return cls(agent=data["agent"], dataflow=Path(dataflow) if dataflow else None,
                   target=data.get("target") or CANVAS, node=data.get("node"))


@dataclass(frozen=True)
class Case:
    """One test case of ``evals``."""

    id: int
    prompt: str
    expected_output: str
    assertions: tuple[str, ...]
    context: Context


@dataclass(frozen=True)
class Query:
    """One query of ``trigger_queries``, by its place in the list (from 1)."""

    index: int
    query: str
    should_trigger: bool


@dataclass(frozen=True)
class SkillEvals:
    """A skill's ``evals/evals.json``, read."""

    name: str
    #: The skill's folder.
    folder: Path
    cases: tuple[Case, ...]
    queries: tuple[Query, ...]
    #: Where the trigger queries run: the file's top-level fields.
    context: Context

    @property
    def file(self) -> Path:
        return self.folder / skill_format.EVALS_DIR / EVALS_FILE


# --- Reading ------------------------------------------------------------------------


def evals_file(folder) -> Path:
    """Where the skill in *folder* keeps its evaluations."""
    return Path(folder) / skill_format.EVALS_DIR / EVALS_FILE


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _context(data: Mapping, folder: Path, default: Context | None, where: str,
             problems: list[str]) -> Context | None:
    """The context *data* names, each field it leaves out taken from *default*."""
    agent = data.get("agent", default.agent if default else None)
    if not _text(agent) or "@" not in agent:
        problems.append(f"{where}: agent must name an agent as <id>@<major>, not {agent!r}")
        return None
    dataflow = default.dataflow if default else None
    if "dataflow" in data:
        dataflow = _dataflow_path(data["dataflow"], folder, where, problems)
    target, node = (default.target, default.node) if default else (CANVAS, None)
    if "target" in data:
        raw = data["target"]
        kind = raw.get("kind") if isinstance(raw, Mapping) else None
        if kind == CANVAS:
            target, node = CANVAS, None
        elif kind == NODE and _text(raw.get("node")):
            target, node = NODE, raw["node"]
        else:
            problems.append(f"{where}: target must be {{\"kind\": \"canvas\"}} or a node by its id, not {raw!r}")
    if target == NODE and node and dataflow is not None and dataflow.is_file():
        ids = {n.get("id") for n in _nodes(dataflow)}
        if node not in ids:
            problems.append(f"{where}: the dataflow holds no node {node!r}")
    return Context(agent=agent, dataflow=dataflow, target=target, node=node)


def _dataflow_path(value, folder: Path, where: str, problems: list[str]) -> Path | None:
    if value is None:
        return None
    if not _text(value):
        problems.append(f"{where}: dataflow must be a path, not {value!r}")
        return None
    try:
        path = folder / value if value.startswith(_OWN_PREFIX) else shipped.path(value)
    except ValueError as exc:
        problems.append(f"{where}: {exc}")
        return None
    if ".." in Path(value).parts or not path.is_file():
        problems.append(f"{where}: the dataflow {value!r} is no file")
        return None
    return path


def _nodes(dataflow: Path) -> list[dict]:
    try:
        spec = json.loads(dataflow.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    nodes = (spec.get("dataflow") or {}).get("nodes") if isinstance(spec, dict) else None
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def _case(raw, folder: Path, default: Context | None, seen: set, problems: list[str]) -> Case | None:
    where = f"evals[{raw.get('id') if isinstance(raw, Mapping) else '?'}]"
    if not isinstance(raw, Mapping):
        problems.append(f"{where} is no object")
        return None
    case_id = raw.get("id")
    if not isinstance(case_id, int) or isinstance(case_id, bool) or case_id in seen:
        problems.append(f"{where}: id must be a whole number no other test case has")
        return None
    seen.add(case_id)
    for key in ("prompt", "expected_output"):
        if not _text(raw.get(key)):
            problems.append(f"{where}: {key} must be text")
    assertions = raw.get("assertions")
    if not isinstance(assertions, list) or not assertions or not all(_text(a) for a in assertions):
        problems.append(f"{where}: assertions must be a list of statements")
        assertions = []
    context = _context(raw, folder, default, where, problems)
    if context is None or not _text(raw.get("prompt")) or not _text(raw.get("expected_output")):
        return None
    return Case(id=case_id, prompt=raw["prompt"], expected_output=raw["expected_output"],
                assertions=tuple(assertions), context=context)


def _queries(raw, problems: list[str]) -> tuple[Query, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        problems.append("trigger_queries must be a list")
        return ()
    found: list[Query] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        query = item.get("query") if isinstance(item, Mapping) else None
        should = item.get("should_trigger") if isinstance(item, Mapping) else None
        if not _text(query) or not isinstance(should, bool):
            problems.append(f"trigger_queries[{index}] must be a query and should_trigger, true or false")
            continue
        if query in seen:
            problems.append(f"trigger_queries[{index}] repeats an earlier query")
            continue
        seen.add(query)
        found.append(Query(index=index, query=query, should_trigger=should))
    return tuple(found)


def read(folder) -> SkillEvals:
    """The evaluations of the skill in *folder*. Raises :class:`EvalsError`
    naming every problem of its ``evals/evals.json``."""
    folder = Path(folder)
    file = evals_file(folder)
    where = f"{folder.name}/{skill_format.EVALS_DIR}/{EVALS_FILE}"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalsError(f"{where} cannot be read: {exc}") from None
    if not isinstance(data, Mapping):
        raise EvalsError(f"{where} is no JSON object")
    problems: list[str] = []
    if data.get("skill_name") != folder.name:
        problems.append(f"skill_name must be {folder.name!r}, its folder's name")
    default = _context(data, folder, None, "the top level", problems)
    cases_raw = data.get("evals")
    if not isinstance(cases_raw, list) or not cases_raw:
        problems.append("evals must be a list of test cases")
        cases_raw = []
    seen: set = set()
    cases = [_case(raw, folder, default, seen, problems) for raw in cases_raw]
    queries = _queries(data.get("trigger_queries"), problems)
    if problems or default is None:
        raise EvalsError(f"{where}: " + "; ".join(problems))
    return SkillEvals(name=folder.name, folder=folder, cases=tuple(c for c in cases if c),
                      queries=queries, context=default)


def skill_folders() -> tuple[Path, ...]:
    """The folders of every skill Curio ships: those of ``skills/``, then
    those each package Curio ships keeps in its ``skills/``."""
    packaged = sorted(path.parent for path in shipped.path("packages").glob(f"*/skills/*/{skill_format.SKILL_FILE}"))
    return (*skill_format.shipped_folders(), *packaged)


def shipped_evals() -> tuple[SkillEvals, ...]:
    """The evaluations of every skill Curio ships that holds them."""
    return tuple(read(folder) for folder in skill_folders() if evals_file(folder).is_file())


# --- Planning -----------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """One run: a trigger query's or a test case's, in one condition."""

    kind: str
    skill: str
    #: The run's folder in the results, from the skill's: ``triggers/q07/run-2``
    #: or ``eval-3/with_skill/run-1``.
    key: str
    condition: str
    run: int
    message: str
    context: Context
    #: A trigger query's place and label.
    query: int | None = None
    should_trigger: bool | None = None
    #: A test case's id, what success looks like, and its assertions.
    case: int | None = None
    expected_output: str | None = None
    assertions: tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return f"{self.skill}/{self.key}"

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "skill": self.skill, "key": self.key, "condition": self.condition,
            "run": self.run, "message": self.message, "context": self.context.as_dict(),
            "query": self.query, "should_trigger": self.should_trigger, "case": self.case,
            "expected_output": self.expected_output, "assertions": list(self.assertions),
        }

    @classmethod
    def from_dict(cls, data: Mapping) -> "Task":
        values = dict(data)
        values["context"] = Context.from_dict(data["context"])
        values["assertions"] = tuple(data.get("assertions") or ())
        return cls(**values)


def plan(evals: Iterable[SkillEvals], *, runs: int = RUNS, kinds: Iterable[str] = (TRIGGER, TASK)) -> list[Task]:
    """Every run of *evals*, *runs* times each: each trigger query (with the
    skill, as it ships), then each test case with the skill and without it."""
    kinds = set(kinds)
    tasks: list[Task] = []
    for skill in evals:
        if TRIGGER in kinds:
            for query in skill.queries:
                for run in range(1, runs + 1):
                    tasks.append(Task(
                        kind=TRIGGER, skill=skill.name, key=f"triggers/q{query.index:02d}/run-{run}",
                        condition=WITH_SKILL, run=run, message=query.query, context=skill.context,
                        query=query.index, should_trigger=query.should_trigger,
                    ))
        if TASK in kinds:
            for case in skill.cases:
                for condition in CONDITIONS:
                    for run in range(1, runs + 1):
                        tasks.append(Task(
                            kind=TASK, skill=skill.name, key=f"eval-{case.id}/{condition}/run-{run}",
                            condition=condition, run=run, message=case.prompt, context=case.context,
                            case=case.id, expected_output=case.expected_output, assertions=case.assertions,
                        ))
    return tasks


# --- Counting -----------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _stddev(values: list[float]) -> float | None:
    return round(statistics.pstdev(values), 4) if len(values) > 1 else (0.0 if values else None)


def _stat(values: list[float]) -> dict:
    return {"mean": _mean(values), "stddev": _stddev(values),
            "min": min(values) if values else None, "max": max(values) if values else None}


def trigger_results(skill: SkillEvals, results: Iterable[Mapping]) -> list[dict]:
    """Each trigger query of *skill* as agentskills.io's script reports it,
    from its runs' *results*: how many runs loaded the skill, of how many ran
    without an error, the rate, and whether the query passed."""
    by_query: dict[int, list[Mapping]] = {}
    for result in results:
        if result.get("kind") == TRIGGER and result.get("skill") == skill.name:
            by_query.setdefault(result["query"], []).append(result)
    rows = []
    for query in skill.queries:
        runs = by_query.get(query.index, [])
        ok = [r for r in runs if not r.get("error")]
        triggers = sum(1 for r in ok if r.get("triggered"))
        rate = triggers / len(ok) if ok else None
        passed = None if rate is None else (rate > THRESHOLD if query.should_trigger else rate < THRESHOLD)
        rows.append({
            "query": query.query, "should_trigger": query.should_trigger, "triggers": triggers,
            "runs": len(ok), "errors": len(runs) - len(ok),
            "trigger_rate": None if rate is None else round(rate, 4), "passed": passed,
        })
    return rows


def trigger_summary(rows: list[dict]) -> dict | None:
    """What a skill's trigger queries came to: how many passed, the mean rate
    of those that should trigger and of those that should not."""
    if not rows:
        return None
    judged = [row for row in rows if row["passed"] is not None]
    should = [row["trigger_rate"] for row in judged if row["should_trigger"]]
    should_not = [row["trigger_rate"] for row in judged if not row["should_trigger"]]
    return {
        "queries": len(rows), "judged": len(judged), "passed": sum(1 for row in judged if row["passed"]),
        "should_trigger_rate": _mean(should), "should_not_trigger_rate": _mean(should_not),
        "errors": sum(row["errors"] for row in rows),
    }


def benchmark(skill: SkillEvals, results: Iterable[Mapping]) -> dict:
    """*skill*'s test cases with the skill and without it, from their runs'
    *results*, as agentskills.io's ``benchmark.json``: each condition's pass
    rate, time and tokens over its runs, and the difference. A run with the
    skill also says whether the skill reached the model (loaded with
    ``skill.read``, handed, or in its preamble), and the pass rate is split by
    that too."""
    runs = [r for r in results if r.get("kind") == TASK and r.get("skill") == skill.name]
    summary: dict = {}
    listed = []
    for condition in CONDITIONS:
        mine = [r for r in runs if r.get("condition") == condition]
        graded = [r for r in mine if not r.get("error") and isinstance(r.get("grading"), Mapping)]
        rates = [r["grading"]["summary"]["pass_rate"] for r in graded]
        entry = {
            "pass_rate": _stat(rates),
            "time_seconds": _stat([r["timing"]["duration_ms"] / 1000 for r in graded]),
            "tokens": _stat([float(r["timing"]["total_tokens"]) for r in graded]),
            "runs": len(graded), "errors": len(mine) - len(graded),
        }
        if condition == WITH_SKILL:
            used = [r for r in graded if r.get("used")]
            entry["used"] = {"runs": len(used), "pass_rate": _mean([r["grading"]["summary"]["pass_rate"]
                                                                     for r in used])}
            entry["not_used"] = {"runs": len(graded) - len(used), "pass_rate": _mean(
                [r["grading"]["summary"]["pass_rate"] for r in graded if not r.get("used")])}
        summary[condition] = entry
        for r in mine:
            listed.append({
                "eval_id": r.get("case"), "configuration": condition, "run_number": r.get("run"),
                "result": None if r.get("error") else {
                    **{k: r["grading"]["summary"][k] for k in ("pass_rate", "passed", "failed", "total")},
                    "time_seconds": r["timing"]["duration_ms"] / 1000, "tokens": r["timing"]["total_tokens"],
                } if isinstance(r.get("grading"), Mapping) else None,
                "used": r.get("used"), "error": r.get("error"),
            })
    delta = {}
    for key in ("pass_rate", "time_seconds", "tokens"):
        a, b = summary[WITH_SKILL][key]["mean"], summary[WITHOUT_SKILL][key]["mean"]
        delta[key] = None if a is None or b is None else round(a - b, 4)
    summary["delta"] = delta
    return {"skill_name": skill.name, "run_summary": summary, "runs": listed}


def grading_summary(results: list[Mapping]) -> dict:
    """The ``summary`` of a ``grading.json``, from its assertion results."""
    passed = sum(1 for r in results if r.get("passed") is True)
    total = len(results)
    return {"passed": passed, "failed": total - passed, "total": total,
            "pass_rate": round(passed / total, 4) if total else 0.0}


def projection(results: Iterable[Mapping], planned: Iterable[Task], jobs: int) -> dict:
    """How long *planned* would take on *jobs* workers, at the mean time each
    kind of run took in *results*, and the runs it holds of each kind."""
    took: dict[str, list[float]] = {TRIGGER: [], TASK: []}
    for result in results:
        if result.get("seconds") is not None:
            took.setdefault(result.get("kind"), []).append(float(result["seconds"]))
    counts = {TRIGGER: 0, TASK: 0}
    for task in planned:
        counts[task.kind] = counts.get(task.kind, 0) + 1
    means = {kind: _mean(values) for kind, values in took.items()}
    known = [means[kind] for kind in counts if counts[kind] and means.get(kind) is not None]
    fallback = statistics.fmean(known) if known else None
    total = 0.0
    for kind, count in counts.items():
        mean = means.get(kind) if means.get(kind) is not None else fallback
        total += count * (mean or 0.0)
    return {"runs": counts, "mean_seconds": means, "jobs": jobs,
            "hours": round(total / max(1, jobs) / 3600, 2) if fallback is not None else None}


# --- The endpoint, and what is never written ----------------------------------------


@dataclass(frozen=True)
class Endpoint:
    """The OpenAI-compatible endpoint a run's model calls go to, from the
    environment. Its ``repr`` names the model alone."""

    base_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model: str

    @classmethod
    def from_env(cls, env: Mapping | None = None) -> "Endpoint":
        """The endpoint the three variables name. Raises ``LookupError``
        naming those that are not set (never their values)."""
        env = os.environ if env is None else env
        names = (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL)
        missing = [name for name in names if not str(env.get(name) or "").strip()]
        if missing:
            raise LookupError("set " + ", ".join(missing))
        return cls(base_url=env[ENV_BASE_URL].strip(), api_key=env[ENV_API_KEY].strip(),
                   model=env[ENV_MODEL].strip())

    def secrets(self) -> dict[str, str]:
        """What scrubbing takes out of every output, by the name it is
        replaced with: the key, the base URL, its host and port, its host."""
        parts = urlsplit(self.base_url)
        found = {"eval-api-key": self.api_key, "eval-base-url": self.base_url}
        if self.base_url.rstrip("/") != self.base_url:
            found["eval-base-url-bare"] = self.base_url.rstrip("/")
        if parts.netloc:
            found["eval-endpoint"] = parts.netloc
        if parts.hostname and parts.hostname not in _LOOPBACK:
            found["eval-host"] = parts.hostname
        return found

    def needles(self) -> list[bytes]:
        """What :func:`leaks` looks for in each output: every value
        :meth:`secrets` names, however short."""
        return sorted({value.encode("utf-8") for value in self.secrets().values() if value}, key=len, reverse=True)


def leaks(folder: Path, endpoint: Endpoint) -> list[str]:
    """The files under *folder* that hold the endpoint's key, base URL or
    host, by their paths there: none, after a run whose writes were all
    scrubbed."""
    needles = endpoint.needles()
    found = []
    for path in sorted(Path(folder).rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if any(needle in data for needle in needles):
            found.append(path.relative_to(folder).as_posix())
    return found
