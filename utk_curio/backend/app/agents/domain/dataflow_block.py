"""The dataflow block: what a run that writes code is given of its dataflow. Pure.

A run that writes code gets one block of at most :data:`MAX_CHARS` characters
beside its task, framed as the canvas context is: a user message whose first
line, the frame, says what follows is data. It is never a slot of the system
turn, since a package's text can come from anyone. It holds:

- the dataflow's datasets and models, each with the line that loads it;
- the account's Node code keys, by name, each with the line that reads it,
  never a value;
- the template of the node being written: its whole description, its starter,
  and the functions its code can import, listed under it.

:func:`layout` writes the block from those rows, each a line kept whole. When
they do not all fit, it keeps them in this order and leaves the rest out: the
template's description, its starter, the functions the starter imports, the
keys, the models, the datasets, then the template's other functions, those
with a docstring first. A last part says how many it left out of each kind
and, to a run that holds the tool that lists them, which tool that is
(:data:`LISTED_BY`). Its words are the sections of the base entry's
``dataflow-block.md``, and its frame the ``dataflow-block`` section of
``frames.md``, beside the canvas context's (:func:`words`).

The rows come from the code that owns each (``application/dataflow_block.py``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from utk_curio.backend.app.agents.domain import agent_text, builtin

#: The page of the base entry whose sections are the block's words.
PAGE = "dataflow-block.md"
#: The section of the base entry's frames page that frames the block.
FRAME_SECTION = "dataflow-block"
#: The most characters a block holds, its frame and its last part included.
MAX_CHARS = 8_000
#: The kinds of item a block can leave out, in the order its last part names them.
KINDS = ("description", "starter", "keys", "models", "datasets", "functions")
#: The tool that lists every item of a kind, named to a run that holds it.
LISTED_BY = {"datasets": "catalog.search", "models": "models.search", "functions": "packages.resolve"}
#: The most characters of a dataset's title or a model's name a line keeps.
NAME_MAX_CHARS = 80
#: What a frame names, filled by :func:`_fill`.
_PLACEHOLDER_RE = re.compile(r"\{(count|tool)\}")
#: ``from <module> import <names>``, the names in parentheses or up to the line's end or a comment.
_IMPORT_FROM_RE = re.compile(r"^[ \t]*from[ \t]+([A-Za-z_][\w.]*)[ \t]+import[ \t]+(\([^)]*\)|[^#\n]+)", re.MULTILINE)
#: ``import <module>, <module>``.
_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+([^#\n]+)", re.MULTILINE)


@dataclass(frozen=True)
class Dataset:
    """A dataset of the dataflow, as the Data Catalog lists it."""

    id: str
    title: str
    format: str
    #: The line that loads it, as the Data Catalog gives it.
    loader: str


@dataclass(frozen=True)
class Model:
    """A model of the dataflow, from the Model Catalog."""

    id: str
    name: str
    #: The line that loads it.
    loader: str


@dataclass(frozen=True)
class Key:
    """A Node code key saved in API Settings: never its value."""

    name: str
    host: str
    #: How the host takes it, such as ``query:key`` or ``header:X-Api-Key``.
    delivery: str
    #: The line that reads it.
    use: str


@dataclass(frozen=True)
class Function:
    """A public function a module of a package defines."""

    module: str
    name: str
    #: Its signature as Python writes one, without annotations.
    call: str
    #: The first paragraph of its docstring.
    doc: str = ""


@dataclass(frozen=True)
class Template:
    """The template of the node being written."""

    id: str
    label: str
    description: str
    starter: str | None = None
    #: The language its starter is written in, which the starter's fence names.
    language: str = ""
    #: The functions its code can import, its own package's first.
    functions: tuple[Function, ...] = ()


def words() -> Mapping[str, str]:
    """The block's words, as an agent reads them: the sections of :data:`PAGE`,
    and its ``frame``, the :data:`FRAME_SECTION` section of the frames page."""
    found = dict(agent_text.sections(PAGE))
    found["frame"] = agent_text.section(builtin.FRAMES_FILE, FRAME_SECTION)
    return MappingProxyType(found)


def _word(found: Mapping[str, str], name: str) -> str:
    if name not in found:
        raise agent_text.AgentTextError(
            f"{agent_text.PAGE_PREFIX}{PAGE} has no section {name!r}; its sections are: {', '.join(found) or 'none'}"
        )
    return found[name]


def _fill(text: str, values: Mapping[str, str], where: str) -> str:
    """*text* with each ``{name}`` of *values* replaced, in one pass. Raises
    ``agent_text.AgentTextError`` when *text* names one other than once."""
    for name in values:
        if text.count("{" + name + "}") != 1:
            raise agent_text.AgentTextError(
                f"{agent_text.PAGE_PREFIX}{PAGE}, section {where}, names {{{name}}} "
                f"{text.count('{' + name + '}')} times, where it names it once"
            )
    return _PLACEHOLDER_RE.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def _one_line(text: object, limit: int | None = None) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:limit].rstrip() if limit is not None and len(flat) > limit else flat


def _dataset_line(row: Dataset) -> str:
    title = _one_line(row.title, NAME_MAX_CHARS) or row.id
    return f"- {row.id} ({title}, {row.format or 'file'}): {'; '.join(_lines(row.loader))}"


def _model_line(row: Model) -> str:
    return f"- {row.id} ({_one_line(row.name, NAME_MAX_CHARS) or row.id}): {_one_line(row.loader)}"


def _key_line(row: Key) -> str:
    return f"- {row.name}, for {row.host} ({row.delivery}): {_one_line(row.use)}"


def _function_line(row: Function) -> str:
    doc = _one_line(row.doc)
    return f"- {row.module}.{row.call}" + (f": {doc}" if doc else "")


def _lines(text: object) -> list[str]:
    return [line for line in str(text or "").splitlines() if line.strip()]


def imported_by(starter: str | None) -> tuple[frozenset[str], frozenset[str]]:
    """The names and the modules a starter imports: ``from m import a, b``
    imports ``a`` and ``b``, ``import m`` imports ``m``. Read line by line,
    since a starter is the body of a node's function, which Python does not
    parse as a module."""
    names: set[str] = set()
    modules: set[str] = set()
    for module, imported in _IMPORT_FROM_RE.findall(starter or ""):
        for item in imported.strip().strip("()").split(","):
            name = item.strip().split(" as ", 1)[0].strip()
            if name.isidentifier():
                names.add(name)
                modules.add(f"{module}.{name}")
    for listed in _IMPORT_RE.findall(starter or ""):
        modules.update(item.strip().split(" as ", 1)[0].strip() for item in listed.split(","))
    return frozenset(names), frozenset(modules)


def _ordered_functions(template: Template) -> tuple[list[Function], list[Function]]:
    """The template's functions the starter imports, then the others: those
    with a docstring first, each group in the template's order."""
    names, modules = imported_by(template.starter)
    first = [f for f in template.functions if f.name in names or f.module in modules]
    rest = [f for f in template.functions if f not in first]
    return first, [f for f in rest if f.doc.strip()] + [f for f in rest if not f.doc.strip()]


class _Part:
    """One part of the block: its heading and the items it keeps, which a
    blank line sets apart from the part before it."""

    def __init__(self, heading: str):
        self.heading = heading
        self.items: list[str] = []
        self.left_out = 0

    def cost(self, item: str) -> int:
        return len(item) + 1 + (0 if self.items else 2 + len(self.heading))

    def text(self) -> str:
        return "\n".join([self.heading, *self.items])


class _Budget:
    def __init__(self, chars: int):
        self.chars = chars

    def keep(self, part: _Part, items: Iterable[str]) -> None:
        """Keep *items* in *part* while they fit: once one does not, it and
        every item after it are left out."""
        for item in items:
            if part.left_out or part.cost(item) > self.chars:
                part.left_out += 1
                continue
            self.chars -= part.cost(item)
            part.items.append(item)


def _keep_description(budget: _Budget, part: _Part, template: Template) -> int:
    """Keep the template's line, its description cut at a word to what fits
    when it does not fit whole; how many characters were cut."""
    head = f"{template.id} ({_one_line(template.label) or template.id})"
    description = _one_line(template.description)
    if not description or part.cost(f"{head}: {description}") <= budget.chars:
        budget.keep(part, [f"{head}: {description}" if description else head])
        return 0
    room = max(budget.chars - part.cost(f"{head}: "), 0)
    kept = description[:room].rsplit(" ", 1)[0] if room < len(description) else description
    budget.keep(part, [f"{head}: {kept}" if kept else head])
    return len(description) - len(kept)


def _keep_starter(budget: _Budget, part: _Part, template: Template) -> None:
    """Keep the starter's lines in a fenced block while they fit, the fence's
    two lines spent with its first."""
    fence = f"```{template.language}"
    lines = (template.starter or "").rstrip("\n").split("\n")
    closing = len("```") + 1
    for index, line in enumerate(lines):
        cost = len(line) + 1 + (part.cost(fence) + closing if not part.items else 0)
        if part.left_out or cost > budget.chars:
            part.left_out = len(lines) - index
            return
        budget.chars -= cost
        if not part.items:
            part.items.append(fence)
        part.items.append(line)


def _left_out_part(found: Mapping[str, str], parts: Mapping[str, _Part], cut: int, tools: frozenset[str]) -> str:
    counts = {kind: parts[kind].left_out for kind in KINDS if kind in parts}
    counts["description"] = cut
    lines = []
    for kind in KINDS:
        if counts.get(kind):
            line = _fill(_word(found, f"left-out-{kind}"), {"count": f"{counts[kind]:,}"}, f"left-out-{kind}")
            if LISTED_BY.get(kind) in tools:
                line += _fill(_word(found, "read-by"), {"tool": LISTED_BY[kind]}, "read-by")
            lines.append(f"- {line}.")
    return "\n".join([_word(found, "left-out"), *lines]) if lines else ""


def _reserve(found: Mapping[str, str]) -> int:
    """The most characters the last part can take: its heading, and a line of
    each kind with its tool, a count of up to six digits and a period."""
    tool = max(len(name) for name in LISTED_BY.values())
    line = len(_word(found, "read-by")) + tool + 12
    return 2 + len(_word(found, "left-out")) + sum(len(_word(found, f"left-out-{kind}")) + line for kind in KINDS)


def layout(
    *,
    datasets: Iterable[Dataset] = (),
    models: Iterable[Model] = (),
    keys: Iterable[Key] = (),
    template: Template | None = None,
    tools: Iterable[str] = (),
) -> str | None:
    """The block, at most :data:`MAX_CHARS` characters, or None when it would
    hold nothing. *tools* are the run's granted tools: the last part names a
    tool that lists what was left out only when the run holds it."""
    datasets, models, keys = list(datasets), list(models), list(keys)
    if not (datasets or models or keys or template):
        return None
    found = words()
    frame = _word(found, "frame")
    budget = _Budget(MAX_CHARS - len(frame) - _reserve(found))
    order = ("datasets", "models", "keys", "template", "starter", "functions")
    parts = {name: _Part(_word(found, name)) for name in order}
    cut = 0
    first: list[Function] = []
    rest: list[Function] = []
    if template is not None:
        cut = _keep_description(budget, parts["template"], template)
        if template.starter and template.starter.strip():
            _keep_starter(budget, parts["starter"], template)
        first, rest = _ordered_functions(template)
        budget.keep(parts["functions"], [_function_line(f) for f in first])
    budget.keep(parts["keys"], [_key_line(row) for row in keys])
    budget.keep(parts["models"], [_model_line(row) for row in models])
    budget.keep(parts["datasets"], [_dataset_line(row) for row in datasets])
    budget.keep(parts["functions"], [_function_line(f) for f in rest])
    if parts["starter"].items:
        parts["starter"].items.append("```")
    shown = [parts[name].text() for name in order if parts[name].items]
    left = _left_out_part(found, parts, cut, frozenset(tools))
    return "\n\n".join([frame, *shown, *([left] if left else [])])
