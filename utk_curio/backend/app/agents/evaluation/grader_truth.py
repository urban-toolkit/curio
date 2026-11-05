"""Grader truth: answers to the skills' test cases whose grade is known, so a grader's agreement can be measured.

A grader model judges every assertion of a test case that its ``checks``
(``checks.py``) do not decide. These answers measure how often it is right,
with no answer labeled by hand. A skill's ``evals/truth.json`` holds them,
beside its ``evals/evals.json``:

- A **golden** answer is the reply, changes and calls a correct answer gives.
  It is written from Curio's shipped examples (``docs/examples/``, the cases'
  own dataflows), its generators and its tests, the way ``oracle.py`` writes
  the replies that rebuild an example, and driven through the real tools, so
  Curio's own checks passed it. It passes every assertion of its case.
- A **mutant** is a golden answer with one known-wrong output. It names the
  assertions it fails (``fails``) and passes every other one. Its name says
  its class:
  - ``refused-<what>``: an output planted from a test that pins Curio's
    refusal of it: an edge the plan check refuses, a spec the document check
    refuses, a Map Editor call its reader rejects, code the grounding gate
    refuses, a tile the dashboard refuses. It is shown as landed, so the
    grader has to judge it, and it fails the assertions that output breaks.
  - ``fenced``: the class seen in real runs. The golden answer's content is
    moved into a fenced block of the reply, its change is removed and its
    write call is refused, as a refused write leaves it. It fails each
    assertion whose evidence in the golden answer was that change: the node
    it made, what the written content holds or lacks, what the plan adds,
    the setting, and a reply's claim that it landed. That is how a ``code``
    or ``spec`` check decides it: one that says a written node lacks
    something needs a node written at all. It passes each assertion that
    rests on the reply's explanation, or that says a change or a call did not
    happen (creates no node, adds no Data Pool), as a ``tool``,
    ``node-added`` or ``unchanged`` check decides it.
- A **gap** is a case with no such source, and why, as ``oracle.py``'s
  ``Unrepresentable`` names what the contract cannot express.

Every case has a golden answer or a gap. Each answer holds what a grader is
shown of a run, in the shapes ``skill_eval_worker.py`` writes them: ``reply``
(``outputs/reply.md``, without the newline the worker ends it with),
``changes`` (``outputs/changes.json``: ``changed``, ``cards`` and
``awaiting_review``) and ``calls`` (``outputs/calls.json``).
:func:`write_outputs` writes them as a run folder holds them, so
``checks.RunRecord.of`` reads an answer as it reads a run.

The file::

    {"skill_name": "<the skill's name>",
     "cases": [{"case": 1, "assertions": ["...", "..."]}],
     "answers": [{"case": 1, "name": "golden", "kind": "golden", "source": "...",
                  "fails": [], "reply": "...", "changes": {...}, "calls": [...]}],
     "gaps": [{"case": 3, "why": "..."}]}

``cases`` holds, for each test case, the assertions its answers were built
against, word for word. ``fails`` names assertions by their place, so a case
whose assertions changed since makes every ``fails`` of its answers suspect:
the file is refused, naming the case, until each answer's ``fails`` is checked
against the new assertions and they are copied into its entry.

:func:`read` reads one skill's file and :func:`shipped` every shipped skill's;
both raise :class:`TruthError` naming every problem.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from utk_curio.backend.app.agents.domain import tool_names
from utk_curio.backend.app.agents.domain import skills as skill_format
from utk_curio.backend.app.agents.evaluation import skill_evals

#: The file of a skill's ``evals/`` folder that holds its grader truth.
TRUTH_FILE = "truth.json"
#: The two kinds of answer.
GOLDEN, MUTANT = "golden", "mutant"
KINDS = (GOLDEN, MUTANT)
#: The classes of mutant, by how a mutant's name starts.
FENCED, REFUSED = "fenced", "refused"
#: The keys an answer holds.
ANSWER_KEYS = ("case", "name", "kind", "source", "fails", "reply", "changes", "calls")
#: An answer's name: a run folder's name.
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# --- The shapes skill_eval_worker.py writes (test_grader_truth.py holds them to it) ---

#: A call whose change landed, the one status that shows its arguments.
APPLIED = "applied"
#: The tool a delegation is a call of, and the keys it shows; one no agent took
#: shows its capability and status alone.
DELEGATE = tool_names.DELEGATE_TOOL
DELEGATE_KEYS = frozenset({"tool", "capability", "agent", "status", "inputs"})
DELEGATE_UNTAKEN_KEYS = frozenset({"tool", "capability", "status"})
#: The tool never shown: a run without the skill seldom calls it.
SKILL_READ = "skill.read"
#: The keys of ``outputs/changes.json``.
CHANGES_KEYS = ("changed", "cards", "awaiting_review")
#: What ``changed`` holds, and how each was changed.
CHANGED_KINDS = ("nodes", "edges", "scenarios")
CHANGED_HOWS = ("added", "changed", "removed")
#: What a node holds of where the canvas draws it, which the worker leaves out.
LAYOUT = frozenset({"x", "y", "position", "positionAbsolute", "width", "height", "measured", "selected",
                    "dragging", "zIndex", "style"})
#: What a removed item shows, and what a changed one shows beside its changes.
REMOVED_KEYS = frozenset({"id", "type", "title", "name", "source", "target"})
CHANGED_KEYS = frozenset({"id", "type", "title", "name", "changes"})
#: What a change card shows (``skill_evals.change_cards``).
CARD_KEYS = frozenset({*skill_evals._CARD_KEYS, "undo"})
#: What a kept proposal holds for its review's bookkeeping, which is not shown.
BOOKKEEPING = frozenset({"proposalId", "mintSequenceId", "contentSha256", "pins", "status"})
#: The most characters of one text the worker shows.
CLIP = 16000


class TruthError(ValueError):
    """A ``truth.json`` that cannot be read, naming every problem."""


@dataclass(frozen=True)
class Answer:
    """One answer of a skill's grader truth: its case, its name and kind, what
    it came from, the assertions it fails (from 1), and what a grader sees."""

    skill: str
    case: int
    #: Unique within its case: ``golden``, ``fenced`` or ``refused-<what>``.
    name: str
    kind: str
    source: str
    fails: tuple[int, ...]
    reply: str
    changes: dict
    calls: list

    @property
    def key(self) -> str:
        """The answer's run folder, from its skill's."""
        return f"truth/eval-{self.case}/{self.name}"

    @property
    def mutation(self) -> str | None:
        """A mutant's class, :data:`FENCED` or :data:`REFUSED`; None for a golden answer."""
        if self.kind != MUTANT:
            return None
        return FENCED if self.name == FENCED else REFUSED


@dataclass(frozen=True)
class Truth:
    """A skill's grader truth: its answers, and the cases it has no answer for."""

    skill: str
    answers: tuple[Answer, ...]
    #: Each ``{"case": <id>, "why": <text>}``.
    gaps: tuple[dict, ...]

    def golden(self, case: int) -> Answer | None:
        """The golden answer of *case*, or None."""
        return next((a for a in self.answers if a.case == case and a.kind == GOLDEN), None)


def truth_file(evals: skill_evals.SkillEvals) -> Path:
    """Where the skill of *evals* keeps its grader truth."""
    return Path(evals.folder) / skill_format.EVALS_DIR / TRUTH_FILE


def read(evals: skill_evals.SkillEvals) -> Truth | None:
    """The grader truth of the skill whose evaluations are *evals*, or None
    when it has none. Raises :class:`TruthError` naming every problem."""
    file = truth_file(evals)
    if not file.is_file():
        return None
    where = f"{evals.name}/{skill_format.EVALS_DIR}/{TRUTH_FILE}"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TruthError(f"{where} cannot be read: {exc}") from None
    problems: list[str] = []
    truth = _truth(data, evals, problems)
    if problems:
        raise TruthError(f"{where}: " + "; ".join(problems))
    return truth


def shipped() -> dict[str, Truth]:
    """The grader truth of every shipped skill that holds one, by the skill's name."""
    found = {}
    for evals in skill_evals.shipped_evals():
        truth = read(evals)
        if truth is not None:
            found[evals.name] = truth
    return found


def write_outputs(answer: Answer, folder) -> Path:
    """Write *answer* into the run folder *folder* as the worker writes a run's
    outputs: ``outputs/reply.md``, ``outputs/changes.json`` and
    ``outputs/calls.json``. Returns *folder*."""
    out = Path(folder) / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "reply.md").write_text(answer.reply + "\n", encoding="utf-8")
    for name, value in (("changes.json", answer.changes), ("calls.json", answer.calls)):
        (out / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return Path(folder)


# --- Reading ------------------------------------------------------------------------


def _truth(data, evals: skill_evals.SkillEvals, problems: list[str]) -> Truth | None:
    if not isinstance(data, Mapping):
        problems.append("it is no JSON object")
        return None
    unknown = sorted(set(data) - {"skill_name", "cases", "answers", "gaps"})
    if unknown:
        problems.append(f"it takes no {', '.join(unknown)}")
    if data.get("skill_name") != evals.name:
        problems.append(f"skill_name must be {evals.name!r}, its skill's name")
    cases = {case.id: case for case in evals.cases}
    _built_against(data.get("cases"), cases, problems)
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, list):
        problems.append("answers must be a list")
        raw_answers = []
    answers = [_answer(raw, at, evals.name, cases, problems) for at, raw in enumerate(raw_answers, start=1)]
    answers = [answer for answer in answers if answer is not None]
    gaps = _gaps(data.get("gaps", []), cases, problems)
    seen: set = set()
    for answer in answers:
        if (answer.case, answer.name) in seen:
            problems.append(f"case {answer.case} holds two answers named {answer.name!r}")
        seen.add((answer.case, answer.name))
    golden = {answer.case for answer in answers if answer.kind == GOLDEN}
    for answer in answers:
        if answer.kind == MUTANT and answer.case not in golden:
            problems.append(f"the mutant {answer.case}/{answer.name} has no golden answer of its case to come from")
    for gap in gaps:
        if gap["case"] in golden:
            problems.append(f"case {gap['case']} has a golden answer and a gap")
    gapped = {gap["case"] for gap in gaps}
    for case_id in cases:
        if case_id not in golden and case_id not in gapped:
            problems.append(f"case {case_id} has neither a golden answer nor a gap")
    return Truth(skill=evals.name, answers=tuple(answers), gaps=tuple(gaps))


def _built_against(raw, cases: Mapping, problems: list[str]) -> None:
    """Each case's entry in ``cases``: the assertions its answers were built
    against, which must be its assertions now, word for word, since ``fails``
    names them by their place."""
    if not isinstance(raw, list):
        problems.append("cases must be a list of each test case and the assertions its answers were built against")
        return
    recorded: dict = {}
    for at, entry in enumerate(raw, start=1):
        here = f"cases[{at}]"
        if (not isinstance(entry, Mapping) or set(entry) != {"case", "assertions"}
                or not isinstance(entry["assertions"], list) or not all(_text(a) for a in entry["assertions"])):
            problems.append(f"{here} must be a case and the assertions its answers were built against")
            continue
        case_id = entry["case"]
        if not isinstance(case_id, int) or isinstance(case_id, bool) or case_id not in cases:
            problems.append(f"{here}: case must be the id of one of its skill's test cases, not {case_id!r}")
        elif case_id in recorded:
            problems.append(f"{here}: case {case_id} has two entries")
        else:
            recorded[case_id] = tuple(entry["assertions"])
    for case_id, case in cases.items():
        if case_id not in recorded:
            problems.append(f"case {case_id} has no entry in cases: record the assertions its answers were built "
                            "against")
        elif recorded[case_id] != tuple(case.assertions):
            problems.append(f"case {case_id}'s assertions are not the ones its truth was built against: check each "
                            "of its answers' fails against its assertions now, then copy them into its entry in cases")


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _answer(raw, at: int, skill: str, cases: Mapping, problems: list[str]) -> Answer | None:
    here = f"answers[{at}]"
    if not isinstance(raw, Mapping):
        problems.append(f"{here} is no object")
        return None
    missing = [key for key in ANSWER_KEYS if key not in raw]
    unknown = sorted(set(raw) - set(ANSWER_KEYS))
    if missing:
        problems.append(f"{here} needs {', '.join(missing)}")
    if unknown:
        problems.append(f"{here} takes no {', '.join(unknown)}")
    if missing:
        return None
    case_id, name, kind = raw["case"], raw["name"], raw["kind"]
    if isinstance(case_id, int) and not isinstance(case_id, bool) and isinstance(name, str):
        here = f"answers[{at}] ({case_id}/{name})"
    found = len(problems)
    case = cases.get(case_id) if isinstance(case_id, int) and not isinstance(case_id, bool) else None
    if case is None:
        problems.append(f"{here}: case must be the id of one of its skill's test cases, not {case_id!r}")
    if not isinstance(name, str) or not _NAME.match(name):
        problems.append(f"{here}: name must be lowercase letters, digits and dashes, not {name!r}")
    if kind not in KINDS:
        problems.append(f"{here}: kind must be {' or '.join(KINDS)}, not {kind!r}")
    elif isinstance(name, str):
        if kind == GOLDEN and name != GOLDEN:
            problems.append(f"{here}: a golden answer is named {GOLDEN!r}")
        if kind == MUTANT and name != FENCED and not name.startswith(f"{REFUSED}-"):
            problems.append(f"{here}: a mutant is named {FENCED!r} or {REFUSED}-<what>")
    if not _text(raw["source"]):
        problems.append(f"{here}: source must name what its content came from")
    fails = raw["fails"]
    count = len(case.assertions) if case is not None else 0
    if not isinstance(fails, list) or not all(isinstance(n, int) and not isinstance(n, bool) for n in fails):
        problems.append(f"{here}: fails must be a list of assertion places")
        fails = []
    else:
        if fails != sorted(set(fails)):
            problems.append(f"{here}: fails must name each assertion once, in order")
        outside = [n for n in fails if not 1 <= n <= count]
        if case is not None and outside:
            problems.append(f"{here}: fails names {outside}, outside its case's {count} assertions")
    if kind == GOLDEN and fails:
        problems.append(f"{here}: a golden answer fails nothing")
    if kind == MUTANT and not fails:
        problems.append(f"{here}: a mutant fails at least one assertion")
    if not isinstance(raw["reply"], str):
        problems.append(f"{here}: reply must be text")
    elif kind == GOLDEN and not raw["reply"].strip():
        problems.append(f"{here}: a golden answer replies")
    _changes(raw["changes"], here, problems)
    _calls(raw["calls"], here, problems)
    if len(problems) == found and isinstance(raw["changes"], Mapping) and isinstance(raw["calls"], list):
        _agree(raw["changes"], raw["calls"], here, problems)
    if len(problems) > found:
        return None
    return Answer(skill=skill, case=case_id, name=name, kind=kind, source=raw["source"], fails=tuple(fails),
                  reply=raw["reply"], changes=dict(raw["changes"]), calls=list(raw["calls"]))


def _gaps(raw, cases: Mapping, problems: list[str]) -> list[dict]:
    if not isinstance(raw, list):
        problems.append("gaps must be a list")
        return []
    found, seen = [], set()
    for at, item in enumerate(raw, start=1):
        here = f"gaps[{at}]"
        if not isinstance(item, Mapping) or set(item) != {"case", "why"}:
            problems.append(f"{here} must be a case and why")
            continue
        if not isinstance(item["case"], int) or isinstance(item["case"], bool) or item["case"] not in cases:
            problems.append(f"{here}: case must be the id of one of its skill's test cases, not {item['case']!r}")
            continue
        if not _text(item["why"]):
            problems.append(f"{here}: why must say why the case has no golden answer")
            continue
        if item["case"] in seen:
            problems.append(f"{here}: case {item['case']} is a gap twice")
            continue
        seen.add(item["case"])
        found.append({"case": item["case"], "why": item["why"]})
    return found


# --- The shapes ---------------------------------------------------------------------


def _long(value, path: str, here: str, problems: list[str]) -> None:
    """Every text in *value* within :data:`CLIP`, as the worker cuts them."""
    if isinstance(value, str):
        if len(value) > CLIP:
            problems.append(f"{here}: {path} runs past the {CLIP} characters the worker shows")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _long(item, f"{path}.{key}", here, problems)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _long(item, f"{path}[{index}]", here, problems)


def _changes(raw, here: str, problems: list[str]) -> None:
    if not isinstance(raw, Mapping) or set(raw) != set(CHANGES_KEYS):
        problems.append(f"{here}: changes must hold {', '.join(CHANGES_KEYS)} and nothing else")
        return
    changed, cards, pending = raw["changed"], raw["cards"], raw["awaiting_review"]
    if not isinstance(changed, Mapping) or not set(changed) <= set(CHANGED_KINDS):
        problems.append(f"{here}: changes.changed must hold only {', '.join(CHANGED_KINDS)}")
    else:
        for kind, hows in changed.items():
            if not isinstance(hows, Mapping) or not hows or not set(hows) <= set(CHANGED_HOWS):
                problems.append(f"{here}: changes.changed.{kind} must hold {', '.join(CHANGED_HOWS)}, "
                                "each only when it holds one")
                continue
            for how, items in hows.items():
                where = f"changes.changed.{kind}.{how}"
                if not isinstance(items, list) or not items or not all(isinstance(i, Mapping) for i in items):
                    problems.append(f"{here}: {where} must be a list of what was {how}")
                    continue
                for item in items:
                    _item(item, how, where, here, problems)
    if not isinstance(cards, list) or not all(isinstance(card, Mapping) for card in cards):
        problems.append(f"{here}: changes.cards must be a list of cards")
    else:
        for card in cards:
            extra = sorted(set(card) - CARD_KEYS)
            if extra or not isinstance(card.get("undo"), bool) or not _text(card.get("tool")):
                problems.append(f"{here}: a card shows its tool, undo and only {', '.join(sorted(CARD_KEYS))}"
                                + (f", not {', '.join(extra)}" if extra else ""))
    if not isinstance(pending, list) or not all(isinstance(item, Mapping) for item in pending):
        problems.append(f"{here}: changes.awaiting_review must be a list of proposals")
    else:
        for item in pending:
            kept = sorted(set(item) & BOOKKEEPING)
            if kept or not _text(item.get("tool")):
                problems.append(f"{here}: a proposal awaiting review shows its tool and none of its bookkeeping"
                                + (f", not {', '.join(kept)}" if kept else ""))
    _long(raw, "changes", here, problems)


def _item(item: Mapping, how: str, where: str, here: str, problems: list[str]) -> None:
    if item.get("id") is None:
        problems.append(f"{here}: each of {where} has an id")
    if how == "added":
        drawn = sorted(set(item) & LAYOUT)
        if drawn:
            problems.append(f"{here}: {where} shows no layout, not {', '.join(drawn)}")
    elif how == "removed":
        extra = sorted(set(item) - REMOVED_KEYS)
        if extra:
            problems.append(f"{here}: {where} shows only {', '.join(sorted(REMOVED_KEYS))}, not {', '.join(extra)}")
    else:
        extra = sorted(set(item) - CHANGED_KEYS)
        changes = item.get("changes")
        if extra:
            problems.append(f"{here}: {where} shows only {', '.join(sorted(CHANGED_KEYS))}, not {', '.join(extra)}")
        if (not isinstance(changes, Mapping) or not changes
                or not all(isinstance(v, Mapping) and set(v) == {"before", "after"} for v in changes.values())):
            problems.append(f"{here}: {where} names each change as its value before and after")


def _calls(raw, here: str, problems: list[str]) -> None:
    if not isinstance(raw, list) or not all(isinstance(call, Mapping) for call in raw):
        problems.append(f"{here}: calls must be a list of calls")
        return
    for at, call in enumerate(raw, start=1):
        where = f"calls[{at}]"
        tool, status = call.get("tool"), call.get("status")
        if not _text(tool) or not _text(status):
            problems.append(f"{here}: {where} names its tool and its status")
            continue
        if tool == SKILL_READ:
            problems.append(f"{here}: {where} is {SKILL_READ}, which the worker never shows")
        elif tool == DELEGATE:
            keys = set(call)
            if keys not in (DELEGATE_KEYS, DELEGATE_UNTAKEN_KEYS) or not _text(call.get("capability")):
                problems.append(f"{here}: {where}, a delegation, shows {', '.join(sorted(DELEGATE_KEYS))}, "
                                "or its capability and status alone when no agent took it")
        else:
            expected = {"tool", "status", "arguments"} if status == APPLIED else {"tool", "status"}
            if set(call) != expected:
                problems.append(f"{here}: {where} shows its tool and status"
                                + (" and its arguments" if status == APPLIED else ", and arguments only once applied"))
            elif status == APPLIED and not isinstance(call["arguments"], Mapping):
                problems.append(f"{here}: {where}'s arguments must be an object")
    _long(raw, "calls", here, problems)


#: The tools whose call lands a change, each with its card.
CHANGE_TOOLS = ("node.create", "node.content.write", "node.settings.write", "dataflow.plan.write")


def _agree(changes: Mapping, calls: list, here: str, problems: list[str]) -> None:
    """Each applied call of a tool that changes the dataflow has its card. (A
    delegated run's change has a card and no call of its own.)"""
    for tool in CHANGE_TOOLS:
        applied = sum(1 for call in calls if call.get("tool") == tool and call.get("status") == APPLIED)
        carded = sum(1 for card in changes["cards"] if card.get("tool") == tool)
        if applied > carded:
            problems.append(f"{here}: {applied} {tool} call(s) landed and only {carded} card(s) say so")
