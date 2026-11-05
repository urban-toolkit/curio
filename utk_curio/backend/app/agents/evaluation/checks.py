"""A test case's checks: assertions decided from a run's own record, with no model.

A test case of a skill's ``evals/evals.json`` may hold ``checks`` beside its
``assertions`` (``skill_evals.py``). Each check names the assertion it decides,
by its place in the list (from 1), and what the run's record must show; an
assertion several checks name holds when all of them do. A grader model judges
every other assertion, and the benchmark (``benchmark.py``) takes a checked
assertion's result from its checks, which is exact, and counts where the
grader said otherwise.

What a check reads of a run, all of it written by ``skill_eval_worker.py``:
``outputs/calls.json`` (each tool call, its status and, for a call whose
change landed, its arguments; each delegation, its capability and inputs),
``outputs/changes.json`` (the nodes, connections and scenarios the run added,
changed or removed), ``outputs/reply.md``, the test case's dataflow, for
the type of a node the run did not add, and the node the run's agent was
attached to, if any.

The kinds, each with what it holds (``absent: true`` turns any of them into
"the run did not"):

- ``tool``: the run called ``tool``, and its call landed (status ``ok`` or
  ``applied``, or the ``status`` named); on ``node`` when named, and with
  ``args``, each a dotted path into the call's arguments and the value there.
  A call whose arguments name no node is on the node the agent is attached
  to, as the tools resolve it (``tools.py``'s ``_resolve_node_id``); so a
  check names ``node`` only on a tool that works on one node, never on
  ``node.create`` or ``dataflow.plan.write``.
- ``delegate``: the run delegated ``capability``, on ``node`` when named, and
  the delegation ended ``ok`` (or the ``status`` named). A delegation whose
  inputs name no node and no ``nodeType`` is on the node the agent is
  attached to (``turns/delegates.py``'s ``_delegate_target_node_id``).
- ``node-added``: the run added a node of ``type`` (``count`` of them, when named).
- ``edge-added``: the run added a connection from a node of type ``from`` to
  one of type ``to``; an interaction edge when ``interaction`` is true, a data
  edge when false.
- ``code``: the content of a node the run wrote (its ``node``, a node of its
  ``type``, or any) matches the regular expression ``pattern``. With
  ``absent``, a node was written and none of what it wrote matches.
- ``spec``: the content of a node the run wrote, read as JSON, holds the
  dotted ``path`` (equal to ``equals`` when named). A chip outside a string,
  such as ``"scale": [!! scenario colors !!]``, reads as a string of its own
  text (``code_references.with_chip_placeholders``). With ``absent``, a node
  was written and none of what it wrote holds it.
- ``unchanged``: the run added, changed and removed nothing.
- ``reply``: the reply matches the regular expression ``pattern``, in any case.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from utk_curio.backend.app.execution import code_references

#: The statuses of a call whose work landed: a read's, and a write's.
LANDED = ("ok", "applied")
#: Each kind, the keys it must hold and the keys it may.
KINDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "tool": (frozenset({"tool"}), frozenset({"status", "node", "args"})),
    "delegate": (frozenset({"capability"}), frozenset({"status", "node"})),
    "node-added": (frozenset({"type"}), frozenset({"count"})),
    "edge-added": (frozenset({"from", "to"}), frozenset({"interaction"})),
    "code": (frozenset({"pattern"}), frozenset({"node", "type"})),
    "spec": (frozenset({"path"}), frozenset({"node", "type", "equals"})),
    "unchanged": (frozenset(), frozenset()),
    "reply": (frozenset({"pattern"}), frozenset()),
}
#: The keys every check may hold.
COMMON = frozenset({"assertion", "kind", "absent"})
#: The edge type an interaction edge carries in a dataflow.
INTERACTION = "Interaction"


@dataclass(frozen=True)
class Check:
    """One check of a test case: the assertion it decides (from 1), its kind,
    and what that kind holds."""

    assertion: int
    kind: str
    holds: Mapping = field(default_factory=dict)

    @property
    def absent(self) -> bool:
        return bool(self.holds.get("absent"))

    def as_dict(self) -> dict:
        return {"assertion": self.assertion, "kind": self.kind, **dict(self.holds)}


def read(raw, assertions: int, where: str, problems: list[str]) -> tuple[Check, ...]:
    """The checks of a test case whose ``checks`` is *raw*, which has
    *assertions* assertions; each problem goes to *problems*, named from *where*."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        problems.append(f"{where}: checks must be a list")
        return ()
    found = []
    for at, item in enumerate(raw, start=1):
        here = f"{where}: checks[{at}]"
        if not isinstance(item, Mapping):
            problems.append(f"{here} is no object")
            continue
        kind, number = item.get("kind"), item.get("assertion")
        if kind not in KINDS:
            problems.append(f"{here}: kind must be one of {', '.join(sorted(KINDS))}, not {kind!r}")
            continue
        if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= assertions:
            problems.append(f"{here}: assertion must be the place of one of its {assertions} assertions, "
                            f"from 1, not {number!r}")
            continue
        needed, allowed = KINDS[kind]
        missing = sorted(needed - set(item))
        unknown = sorted(set(item) - needed - allowed - COMMON)
        if missing:
            problems.append(f"{here}: a {kind} check needs {', '.join(missing)}")
        if unknown:
            problems.append(f"{here}: a {kind} check takes no {', '.join(unknown)}")
        for key in ("pattern",):
            if key in item:
                try:
                    re.compile(str(item[key]))
                except re.error as exc:
                    problems.append(f"{here}: its pattern is no regular expression: {exc}")
        if "args" in item and not isinstance(item["args"], Mapping):
            problems.append(f"{here}: args must be an object of dotted paths and values")
        if "count" in item and (not isinstance(item["count"], int) or isinstance(item["count"], bool)
                                or item["count"] < 1):
            problems.append(f"{here}: count must be a whole number above 0")
        if not missing and not unknown:
            found.append(Check(assertion=number, kind=kind,
                               holds={key: value for key, value in item.items() if key not in ("assertion", "kind")}))
    return tuple(found)


# --- A run, as the checks read it ---------------------------------------------------


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@dataclass
class RunRecord:
    """What the checks read of one task run."""

    calls: list = field(default_factory=list)
    changed: dict = field(default_factory=dict)
    reply: str = ""
    #: The type of each node of the dataflow the run started on, by its id.
    types: dict = field(default_factory=dict)
    #: The node the run's agent was attached to, or None on the canvas.
    attached: str | None = None

    @classmethod
    def of(cls, folder: Path, dataflow: Path | None = None, attached: str | None = None) -> "RunRecord":
        """The record of the run in *folder* (``.../run-<k>``), whose test case
        started on *dataflow* with its agent attached to the node *attached*."""
        folder = Path(folder)
        changes = _json(folder / "outputs" / "changes.json") or {}
        try:
            reply = (folder / "outputs" / "reply.md").read_text(encoding="utf-8")
        except OSError:
            reply = ""
        types = {}
        spec = _json(dataflow) if dataflow else None
        if isinstance(spec, Mapping):
            for node in (spec.get("dataflow") or {}).get("nodes") or []:
                if isinstance(node, Mapping) and node.get("id") is not None:
                    types[str(node["id"])] = str(node.get("type") or "")
        calls = _json(folder / "outputs" / "calls.json")
        return cls(calls=calls if isinstance(calls, list) else [],
                   changed=changes.get("changed") if isinstance(changes.get("changed"), dict) else {},
                   reply=reply, types=types, attached=attached)

    def _of(self, kind: str, how: str) -> list:
        found = (self.changed.get(kind) or {}).get(how)
        return [item for item in found if isinstance(item, Mapping)] if isinstance(found, list) else []

    def added_nodes(self) -> list:
        return self._of("nodes", "added")

    def type_of(self, node_id) -> str:
        for node in self.added_nodes():
            if str(node.get("id")) == str(node_id):
                return str(node.get("type") or "")
        return self.types.get(str(node_id), "")

    def written(self, node: str | None = None, type_: str | None = None) -> list[str]:
        """The contents the run wrote: each added node's, and each changed
        node's content after the change, of the node or type named."""
        found = []
        for added in self.added_nodes():
            if self._names(added, node, type_) and isinstance(added.get("content"), str):
                found.append(added["content"])
        for changed in self._of("nodes", "changed"):
            after = ((changed.get("changes") or {}).get("content") or {}).get("after")
            if self._names(changed, node, type_) and isinstance(after, str):
                found.append(after)
        return found

    @staticmethod
    def _names(item: Mapping, node: str | None, type_: str | None) -> bool:
        return (node is None or str(item.get("id")) == str(node)) and (type_ is None or item.get("type") == type_)


def _at(value, path: str):
    """The value at the dotted *path* in *value*, and whether it is there."""
    for part in path.split("."):
        if isinstance(value, Mapping) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None, False
    return value, True


def _node_of(arguments, attached: str | None = None) -> str | None:
    """The node a call's recorded *arguments* name, else *attached*; None for
    a call whose arguments the record does not hold."""
    if not isinstance(arguments, Mapping):
        return None
    for key in ("nodeId", "node", "id"):
        if arguments.get(key) is not None:
            return str(arguments[key])
    return attached


def _holds(check: Check, run: RunRecord) -> bool:
    """Whether what *check* names happened in *run*, before ``absent`` turns it."""
    holds, kind = check.holds, check.kind
    if kind == "tool":
        statuses = (holds["status"],) if "status" in holds else LANDED
        for call in run.calls:
            if not isinstance(call, Mapping) or call.get("tool") != holds["tool"] or call.get("status") not in statuses:
                continue
            if "node" in holds and _node_of(call.get("arguments"), run.attached) != str(holds["node"]):
                continue
            arguments = call.get("arguments") if isinstance(call.get("arguments"), Mapping) else {}
            if all(_at(arguments, path) == (value, True) for path, value in (holds.get("args") or {}).items()):
                return True
        return False
    if kind == "delegate":
        status = holds.get("status", "ok")
        for call in run.calls:
            if not (isinstance(call, Mapping) and call.get("tool") == "delegate"
                    and call.get("capability") == holds["capability"] and call.get("status") == status):
                continue
            inputs = call.get("inputs")
            # A delegation that names a nodeType writes a new node's template.
            attached = None if isinstance(inputs, Mapping) and inputs.get("nodeType") else run.attached
            if "node" not in holds or _node_of(inputs, attached) == str(holds["node"]):
                return True
        return False
    if kind == "node-added":
        count = sum(1 for node in run.added_nodes() if node.get("type") == holds["type"])
        return count == holds["count"] if "count" in holds else count > 0
    if kind == "edge-added":
        for edge in run._of("edges", "added"):
            interaction = edge.get("type") == INTERACTION
            if "interaction" in holds and bool(holds["interaction"]) != interaction:
                continue
            if run.type_of(edge.get("source")) == holds["from"] and run.type_of(edge.get("target")) == holds["to"]:
                return True
        return False
    if kind == "code":
        pattern = re.compile(str(holds["pattern"]), re.MULTILINE)
        return any(pattern.search(text) for text in run.written(holds.get("node"), holds.get("type")))
    if kind == "spec":
        for text in run.written(holds.get("node"), holds.get("type")):
            try:
                value, there = _at(json.loads(code_references.with_chip_placeholders(text)), str(holds["path"]))
            except ValueError:
                continue
            if there and ("equals" not in holds or value == holds["equals"]):
                return True
        return False
    if kind == "unchanged":
        return not any(run.changed.get(key) for key in ("nodes", "edges", "scenarios"))
    if kind == "reply":
        return bool(re.search(str(holds["pattern"]), run.reply, re.IGNORECASE | re.MULTILINE))
    raise ValueError(f"no check kind {kind!r}")


def passes(check: Check, run: RunRecord) -> bool:
    """Whether *run* meets *check*. A ``code`` or ``spec`` check that says a
    written node lacks something needs a node written at all."""
    found = _holds(check, run)
    if not check.absent:
        return found
    if check.kind in ("code", "spec") and not run.written(check.holds.get("node"), check.holds.get("type")):
        return False
    return not found


def decided(checks, run: RunRecord) -> dict[int, bool]:
    """Each assertion *checks* decide, by its place (from 1), and whether *run* meets it."""
    out: dict[int, bool] = {}
    for check in checks:
        out[check.assertion] = out.get(check.assertion, True) and passes(check, run)
    return out
