"""The functions Curio gives node code, read from their page in the base entry.

``agents/agent.curio.builtin@1/knowledge/node-functions.md`` lists every
function a node's code calls by name, and the preamble includes it whole. Its
lines have fixed shapes, which :func:`parse` reads and refuses anything else:

- the page's title, ``## <title>``, then paragraphs of prose;
- per function, its call, ``### curio_<name>(<arguments>)``, written as a
  Python signature: a name, ``name=<literal>`` (``None``, ``True``,
  ``False``, a whole number or a double-quoted text), and ``*`` before the
  arguments only a keyword names;
- ``Engines: <engine>, <engine>.``, the engines whose node code has it, as
  a template names its ``engine``: ``python`` or ``javascript``;
- one line on what it does;
- one bullet per argument, in the call's order:
  ``- `<name>`: <what it is>``, or, for an argument that names an item of a
  catalog, ``- `<name>` (<catalog phrase>): <what it is>``, the phrase one
  of :data:`CATALOG_PHRASES`.

A blank line separates each of those. The structured result says, for each
function, the engines that have it and, for each argument, the catalog item
it names, if any: what the agents' checks read.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

#: The page, by its path in the base entry (``curio:knowledge/node-functions.md``).
PAGE = "knowledge/node-functions.md"
#: The engines a node's code runs in, as a template names its ``engine``.
ENGINES = ("python", "javascript")
#: What an argument that names an item of a catalog says it is, and the kind
#: of item: a Data Catalog dataset or collection, a Model Catalog model, or a
#: Node code key (API Settings).
CATALOG_PHRASES = {
    "a Data Catalog dataset": "dataset",
    "a Data Catalog collection": "collection",
    "a Model Catalog model": "model",
    "a Node code key": "key",
}

_TITLE_RE = re.compile(r"^## \S.*$")
_CALL_RE = re.compile(r"^### (curio_[a-z][a-z0-9_]*)\((.*)\)$")
_ENGINES_RE = re.compile(r"^Engines: ([a-z]+(?:, [a-z]+)*)\.$")
_ARGUMENT_RE = re.compile(r"^- `([a-z_][a-z0-9_]*)`(?: \(([^()]+)\))?: (\S.*)$")
_PARAMETER_RE = re.compile(r'^([a-z_][a-z0-9_]*)(?:=(None|True|False|-?[0-9]+|"[^"\\]*"))?$')
#: Line starts no prose line may have: each begins a line of another shape.
_NOT_PROSE = ("#", "- ", "Engines:", "```")


class NodeFunctionsError(ValueError):
    """The page holds a line of no shape it may have, or a function it states twice."""


@dataclass(frozen=True)
class Argument:
    """One argument of a function, as its page gives it."""

    name: str
    #: The default as the call writes it (``None``, ``0``, ``"video"``), or
    #: None for an argument a call must give.
    default: str | None
    #: Whether only a keyword names it: it follows ``*`` in the call.
    keyword_only: bool
    #: The catalog item it names (``dataset``, ``collection``, ``model`` or
    #: ``key``), or None.
    catalog: str | None
    #: What it is.
    text: str

    @property
    def default_value(self):
        """The default as a Python value. Raises ValueError when there is none."""
        if self.default is None:
            raise ValueError(f"{self.name} has no default")
        return ast.literal_eval(self.default)

    @property
    def catalog_phrase(self) -> str | None:
        """What the page says of the catalog item it names, such as
        ``a Data Catalog dataset``, or None."""
        return next((phrase for phrase, kind in CATALOG_PHRASES.items() if kind == self.catalog), None)


@dataclass(frozen=True)
class NodeFunction:
    """One function node code calls, as its page gives it."""

    name: str
    #: The engines whose node code has it, in :data:`ENGINES` order.
    engines: tuple[str, ...]
    #: What it does: one line.
    does: str
    arguments: tuple[Argument, ...]
    #: The line of its call on the page, counted from 1.
    line: int

    @property
    def call(self) -> str:
        """Its call as the page heads it: ``curio_layer(value, layer, slot=0)``."""
        parts, starred = [], False
        for argument in self.arguments:
            if argument.keyword_only and not starred:
                parts.append("*")
                starred = True
            parts.append(argument.name if argument.default is None else f"{argument.name}={argument.default}")
        return f"{self.name}({', '.join(parts)})"

    def argument(self, name: str) -> Argument | None:
        return next((argument for argument in self.arguments if argument.name == name), None)

    @property
    def catalog_arguments(self) -> tuple[Argument, ...]:
        """The arguments that name an item of a catalog."""
        return tuple(argument for argument in self.arguments if argument.catalog is not None)


def _parameters(text: str, where: str) -> list[tuple[str, str | None, bool]]:
    """``(name, default, keyword_only)`` for each argument of a call's
    *text*, as Python reads a signature."""
    if not text:
        return []
    found, names, starred, defaulted = [], set(), False, False
    items = text.split(", ")
    for position, item in enumerate(items):
        if item == "*":
            if starred or position == len(items) - 1:
                raise NodeFunctionsError(f"{where}: a call has one * at most, and an argument after it")
            starred = True
            continue
        match = _PARAMETER_RE.match(item)
        if not match:
            raise NodeFunctionsError(
                f"{where}: {item!r} is no argument; an argument is a name, or name=<None, True, False, "
                'a whole number or a "text">'
            )
        name, default = match.group(1), match.group(2)
        if name in names:
            raise NodeFunctionsError(f"{where}: the call names {name} twice")
        if default is None and defaulted and not starred:
            raise NodeFunctionsError(f"{where}: {name} has no default but follows an argument that has one")
        defaulted = defaulted or default is not None
        names.add(name)
        found.append((name, default, starred))
    return found


def _engines(text: str, where: str) -> tuple[str, ...]:
    engines = text.split(", ")
    unknown = [engine for engine in engines if engine not in ENGINES]
    if unknown or len(set(engines)) != len(engines):
        raise NodeFunctionsError(
            f"{where}: the engines are {', '.join(ENGINES)}, each once, not {text!r}"
        )
    return tuple(engine for engine in ENGINES if engine in engines)


def _lines(text: str) -> list[tuple[int, str]]:
    if not text.endswith("\n") or "\r" in text:
        raise NodeFunctionsError(f"{PAGE} ends in a line break and holds no carriage return")
    return list(enumerate(text[:-1].split("\n"), 1))


def parse(text: str) -> tuple[NodeFunction, ...]:
    """Every function the page *text* gives, in its order.

    Raises :class:`NodeFunctionsError` on a line of no shape the page may
    have, naming its line: a call that is no signature, an engine that is
    none, an argument bullet with no argument of its call or out of its
    order, a catalog phrase not in :data:`CATALOG_PHRASES`, an argument with
    no bullet, a part missing, and a function stated twice."""
    lines = _lines(text)
    if not _TITLE_RE.match(lines[0][1]) or len(lines) < 2 or lines[1][1] != "":
        raise NodeFunctionsError(f"{PAGE}, line 1: the page starts with its title, ## <title>, and a blank line")
    at = 2
    while at < len(lines) and not lines[at][1].startswith("### "):
        number, line = lines[at]
        if line.startswith(_NOT_PROSE):
            raise NodeFunctionsError(
                f"{PAGE}, line {number}: before the first function, the page holds prose only, not {line!r}"
            )
        at += 1

    if at < len(lines) and (lines[at - 1][1] != "" or lines[at - 2][1] == ""):
        raise NodeFunctionsError(f"{PAGE}, line {lines[at][0]}: one blank line goes before a function's call")

    functions: list[NodeFunction] = []
    while at < len(lines):
        number, heading = lines[at]
        where = f"{PAGE}, line {number}"
        call = _CALL_RE.match(heading)
        if not call:
            raise NodeFunctionsError(f"{where}: a function starts with its call, ### curio_<name>(<arguments>), "
                                     f"not {heading!r}")
        name = call.group(1)
        if any(function.name == name for function in functions):
            raise NodeFunctionsError(f"{where}: {name} is stated twice")
        parameters = _parameters(call.group(2), where)
        block = []
        at += 1
        while at < len(lines) and not lines[at][1].startswith("### "):
            block.append(lines[at])
            at += 1
        if at < len(lines):
            if len(block) < 2 or block[-1][1] != "" or block[-2][1] == "":
                raise NodeFunctionsError(f"{PAGE}, line {lines[at][0]}: one blank line goes before a function's call")
            block.pop()
        elif block and block[-1][1] == "":
            raise NodeFunctionsError(f"{PAGE}, line {block[-1][0]}: the page ends with its last argument's line")
        shape = [line for _number, line in block]
        if len(shape) < 4 or shape[0] != "" or shape[2] != "" or shape[4:5] not in ([""], []):
            raise NodeFunctionsError(
                f"{where}: {name}'s call is followed by a blank line, its engines, a blank line, one line on "
                "what it does, a blank line and its arguments, one bullet each"
            )
        engines_line = _ENGINES_RE.match(shape[1])
        if not engines_line:
            raise NodeFunctionsError(f"{PAGE}, line {block[1][0]}: Engines: <engine>, <engine>. not {shape[1]!r}")
        engines = _engines(engines_line.group(1), f"{PAGE}, line {block[1][0]}")
        does = shape[3]
        if not does or does.startswith(_NOT_PROSE):
            raise NodeFunctionsError(f"{PAGE}, line {block[3][0]}: one line on what {name} does, not {does!r}")
        bullets = block[5:]
        if len(bullets) != len(parameters):
            raise NodeFunctionsError(
                f"{where}: {name} has {len(parameters)} arguments and {len(bullets)} lines after what it does; "
                "each argument has one bullet, in the call's order, with no line between them"
            )
        arguments = []
        for (bullet_number, bullet), (parameter, default, keyword_only) in zip(bullets, parameters):
            found = _ARGUMENT_RE.match(bullet)
            if not found:
                raise NodeFunctionsError(
                    f"{PAGE}, line {bullet_number}: an argument is - `<name>`: <text>, or "
                    f"- `<name>` (<catalog phrase>): <text>, not {bullet!r}"
                )
            if found.group(1) != parameter:
                raise NodeFunctionsError(
                    f"{PAGE}, line {bullet_number}: the bullet names {found.group(1)}, and the call's argument "
                    f"there is {parameter}"
                )
            phrase = found.group(2)
            if phrase is not None and phrase not in CATALOG_PHRASES:
                raise NodeFunctionsError(
                    f"{PAGE}, line {bullet_number}: {phrase!r} is no catalog phrase; one is "
                    + ", ".join(repr(known) for known in CATALOG_PHRASES)
                )
            arguments.append(Argument(
                name=parameter, default=default, keyword_only=keyword_only,
                catalog=CATALOG_PHRASES[phrase] if phrase is not None else None, text=found.group(3),
            ))
        functions.append(NodeFunction(name, engines, does, tuple(arguments), number))
    if not functions:
        raise NodeFunctionsError(f"{PAGE} gives no function")
    return tuple(functions)


def read() -> tuple[NodeFunction, ...]:
    """Every function the page Curio ships gives, as the agents read it."""
    from utk_curio.backend.app.agents.domain import agent_text

    return parse(agent_text.read(agent_text.page_file(PAGE)))


def for_engine(engine: str, functions: tuple[NodeFunction, ...] | None = None) -> tuple[NodeFunction, ...]:
    """The functions whose node code in *engine* has them."""
    if engine not in ENGINES:
        raise ValueError(f"{engine!r} is not one of {ENGINES}")
    return tuple(function for function in (read() if functions is None else functions) if engine in function.engines)
