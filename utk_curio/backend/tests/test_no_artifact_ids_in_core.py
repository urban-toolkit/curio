"""No app code names an artifact Curio ships.

Every catalog is a folder of manifests: ``packages/`` (nodes and models),
``datasets/``, ``discovery/`` and ``agents/``. Curio reads what an artifact
brings off its manifest, so a user's package, dataset, source or agent gets
what Curio's own get. An id in app code is a rule for one artifact, which a
new one would not get without an edit there.

The scan collects every shipped id from the manifests themselves: each
manifest's ``id``, and ``<package id>/<template id>`` for each node type. It
leaves out ``curio.builtin``, the base every store holds, whose nodes the core
defines. It looks for each id in the app's code: the backend, the sandbox,
the command line, the frontend (its ``src/`` and its build files), the
launcher, the release files and ``scripts/``. It looks for the SCOUT
publisher's prefixes too (``scout.``, ``model.scout.``, ``data.scout.``),
which rules used to match.

It reads Python, JavaScript and TypeScript, JSON and shell files, without
their comments and docstrings: naming an artifact in words is fine. Markdown,
such as the agents' prompt templates, is not code, and tests are not app code.

``NOT_SCANNED`` lists the scripts that build shipped data or record fixtures
from a named source: naming what they build is what they are for.
``ALLOWED`` lists each other hit with why, by file and id, so a new hit fails,
and so does an entry no file needs any more.
"""

from __future__ import annotations

import ast
import functools
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[3]

#: The package every store is seeded with, whose nodes the core defines.
BASE_PACKAGE = "curio.builtin"

#: The catalogs, by folder, and what their manifests' ids name.
CATALOGS = {"packages": "package", "datasets": "dataset", "discovery": "source", "agents": "agent"}

#: What the scan reads, from the repository's root.
SCANNED = ("curio.py", "setup.py", "MANIFEST.in", "utk_curio", "scripts")

#: Folders inside ``SCANNED`` that hold no app code.
SKIPPED_DIRS = {
    "utk_curio/backend/tests",
    "utk_curio/sandbox/tests",
    "utk_curio/frontend/urban-workflows/src/tests",
    "utk_curio/frontend/urban-workflows/vendor",
    # A pip build's copy of the catalogs.
    "utk_curio/_shipped",
}
SKIPPED_DIR_NAMES = {"node_modules", "dist", "__pycache__"}

#: Scripts that build shipped data, or record test fixtures from a named
#: source, and so name what they build.
NOT_SCANNED = {
    "scripts/build_chicago_loop_layers_dataset.py": "builds the Chicago Loop layers dataset",
    "scripts/build_example_chicago_loop_layers.py": "builds the Chicago Loop layers example from its dataset",
    "scripts/build_example_datasets.py": "builds the example datasets and writes their manifests",
    "scripts/build_example_mapillary.py": "builds the Mapillary sample dataset",
    "scripts/build_example_scenario_charts.py": "builds the datasets the scenario chart examples read",
    "scripts/build_example_storage.py": "builds the example storage datasets",
    "scripts/build_flood_vulnerability_datasets.py": "builds the flood vulnerability datasets",
    "scripts/build_scout_flood_datasets.py": "builds SCOUT's flood datasets",
    "scripts/scout/crop_routing_data.py": "cuts SCOUT's weather into datasets and its roads into the Weather GNN's fixture",
    "scripts/scout/export_deep_umbra.py": "exports SCOUT's Deep Umbra model into its package",
    "scripts/scout/scout_checkout.py": "names the SCOUT files the scripts beside it read, and what they write",
    "scripts/record_discovery_fixtures.py": "records each source's responses as test fixtures",
    "scripts/write_streetview_fixtures.py": "writes the street view source's test fixtures",
}

_DIGESTS = (
    "the digests every shipped copy of a package has had, generated once from git "
    "history and frozen, to tell an untouched copy from an older release"
)
_EVALUATION = "the offline evaluation reconstructs runs of this one agent"
_CASES = "cases beside the code they test, read only by the Jest and pytest suites"

#: Each other hit app code may hold: file -> (ids, why).
ALLOWED = {
    "utk_curio/backend/app/packages/repositories/legacy_catalog_digests.json": (
        {"ai.utk.uhvi", "curio.example-ui", "curio.media", "curio.weather"},
        _DIGESTS,
    ),
    "utk_curio/backend/app/agents/evaluation/live.py": ({"agent.dataflow-builder"}, _EVALUATION),
    "utk_curio/tools/agent_eval.py": ({"agent.dataflow-builder"}, _EVALUATION),
    "utk_curio/frontend/urban-workflows/src/utils/nodeDisplayLabel.cases.json": ({"ai.utk.uhvi"}, _CASES),
    "utk_curio/frontend/urban-workflows/src/utils/scenarios/scenarioParts.cases.json": (
        {"curio.scout/donuts"},
        _CASES,
    ),
}

_PYTHON = {".py"}
_SCRIPT = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
_SHELL_NAMES = {"MANIFEST.in"}

#: Where SCOUT's publisher prefix starts a name: ``scout.``, ``model.scout.``
#: or ``data.scout.``.
_PREFIX = re.compile(r"(?<![\w./-])(?:model\.|data\.)?scout\.")


class Hit(NamedTuple):
    path: str
    line: int
    name: str


def shipped_ids(root: Path) -> dict[str, str]:
    """Every id the catalogs under *root* ship, but ``curio.builtin``'s: id -> kind."""
    ids: dict[str, str] = {}
    for folder, kind in CATALOGS.items():
        for manifest in sorted((root / folder).glob("*/manifest.json")):
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data["id"] == BASE_PACKAGE:
                continue
            ids[data["id"]] = kind
            for template in data.get("templates") or []:
                ids[f"{data['id']}/{template['id']}"] = "node type"
    return ids


def _id_pattern(ids) -> re.Pattern:
    """Any of *ids* as a whole id: ``curio.scout``, ``curio.scout@1`` or
    ``packages/curio.scout@1/``, never part of a longer id. A node type
    matches before its package."""
    names = "|".join(re.escape(name) for name in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(?<![\w.-])(?:{names})(?![\w-]|\.\w)")


def _found(text: str, pattern: re.Pattern) -> list[str]:
    """The shipped ids and SCOUT prefixes *text* names, spelled out or as a
    regular expression (``scout\\.``)."""
    text = text.replace("\\.", ".")
    spans = [match.span() for match in pattern.finditer(text)]
    names = [text[start:end] for start, end in spans]
    names += [
        match.group()
        for match in _PREFIX.finditer(text)
        if not any(start <= match.start() < end for start, end in spans)
    ]
    return names


# ---------------------------------------------------------------------------
# Code without its comments
# ---------------------------------------------------------------------------

def _python_strings(text: str, name: str) -> list[tuple[int, str]]:
    """(line, value) of each string in Python *text*, but those standing alone
    as a statement: docstrings, and the strings that document an attribute."""
    tree = ast.parse(text, filename=name)
    alone = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in alone
    ]


_SCRIPT_TOKEN = re.compile(
    r"""
      (?P<space>\s+)
    | (?P<comment>//[^\n]*|/\*.*?(?:\*/|\Z))
    | (?P<string>"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?)
    | (?P<word>[\w$]+)
    | (?P<other>.)
    """,
    re.S | re.X,
)
#: A template literal's text, up to its end or its next ``${``.
_TEMPLATE_TEXT = re.compile(r"(?:\\.|[^`\\$]|\$(?!\{))*", re.S)
_REGEX_LITERAL = re.compile(r"/(?:\\.|\[(?:\\.|[^\]\\\n])*\]|[^/\\\n\[])+/\w*")
#: After these a ``/`` starts a regular expression, not a division. ``<`` is
#: not one: ``</`` closes a JSX element.
_BEFORE_REGEX = frozenset("(,=:[!&|?{};+-*%>~^") | {
    "", "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "throw", "case", "do", "else", "yield", "await",
}


def _script_without_comments(text: str) -> str:
    """JavaScript or TypeScript *text* with its comments blanked. Its strings,
    template literals, regular expressions, code and JSX text stay, and so do
    its line breaks."""
    comments: list[tuple[int, int]] = []
    frames = [0]  # the brace depth of the file's code, then of each open ``${``
    prev = ""  # the last token, for telling a regular expression from a division
    pos, end = 0, len(text)

    def template_from(at: int) -> tuple[int, str]:
        """Read a template literal's text from *at* to its end, or to its next
        ``${``, which opens a frame. The position after, and the last token."""
        stop = _TEMPLATE_TEXT.match(text, at).end()
        if text.startswith("${", stop):
            frames.append(0)
            return stop + 2, "{"
        return min(stop + 1, end), "`"

    while pos < end:
        if text[pos] == "/" and prev in _BEFORE_REGEX and text[pos + 1:pos + 2] not in ("/", "*"):
            literal = _REGEX_LITERAL.match(text, pos)
            if literal:
                pos, prev = literal.end(), "regex"
                continue
        token = _SCRIPT_TOKEN.match(text, pos)
        kind, value = token.lastgroup, token.group()
        pos = token.end()
        if kind == "space":
            continue
        if kind == "comment":
            comments.append(token.span())
            continue
        if value == "`":
            pos, prev = template_from(pos)
            continue
        if value == "}" and frames[-1] == 0 and len(frames) > 1:
            frames.pop()
            pos, prev = template_from(pos)
            continue
        if value == "{":
            frames[-1] += 1
        elif value == "}":
            frames[-1] -= 1
        prev = value if kind in ("word", "other") else kind
    chars = list(text)
    for start, stop in comments:
        for at in range(start, stop):
            if chars[at] != "\n":
                chars[at] = " "
    return "".join(chars)


def _without_hash_comments(text: str) -> str:
    return "\n".join("" if line.lstrip().startswith("#") else line for line in text.splitlines())


def _pieces(path: Path, relative: str) -> list[tuple[int, str]] | None:
    """(line, text) of what to look in, in the file at *path*, or None for a
    file that is not code."""
    if path.suffix in _PYTHON:
        return _python_strings(path.read_text(encoding="utf-8"), relative)
    if path.suffix in _SCRIPT:
        text = _script_without_comments(path.read_text(encoding="utf-8"))
    elif path.suffix == ".json":
        text = path.read_text(encoding="utf-8")
    elif path.suffix == ".sh" or path.name in _SHELL_NAMES:
        text = _without_hash_comments(path.read_text(encoding="utf-8"))
    else:
        return None
    return list(enumerate(text.splitlines(), 1))


def _files(root: Path):
    """Each file under *root* the scan covers, with its path from *root*."""
    for top in SCANNED:
        start = root / top
        if start.is_file():
            yield start, top
            continue
        for dirpath, dirnames, filenames in os.walk(start):
            here = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in SKIPPED_DIR_NAMES
                and not d.startswith(".")
                and (here / d).relative_to(root).as_posix() not in SKIPPED_DIRS | NOT_SCANNED.keys()
            )
            for filename in sorted(filenames):
                relative = (here / filename).relative_to(root).as_posix()
                if relative not in NOT_SCANNED:
                    yield here / filename, relative


def _area(relative: str) -> str:
    """``utk_curio/backend`` for a file under it, ``scripts`` for a script,
    and a file at the root by its name."""
    parts = relative.split("/")
    return "/".join(parts[:2]) if parts[0] == "utk_curio" else parts[0]


def scan(root: Path, ids) -> tuple[list[Hit], Counter]:
    """Every shipped id and SCOUT prefix the app code under *root* names, and
    how many code files the scan read in each area."""
    pattern = _id_pattern(ids)
    hits: list[Hit] = []
    read: Counter = Counter()
    for path, relative in _files(root):
        pieces = _pieces(path, relative)
        if pieces is None:
            continue
        read[_area(relative)] += 1
        for line, text in pieces:
            hits += [Hit(relative, line, name) for name in _found(text, pattern)]
    return hits, read


@functools.lru_cache(maxsize=1)
def _repo_scan() -> tuple[tuple[Hit, ...], Counter]:
    hits, read = scan(REPO, shipped_ids(REPO))
    return tuple(hits), read


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_the_scan_reads_every_catalog():
    ids = shipped_ids(REPO)
    assert set(ids.values()) == {"package", "node type", "dataset", "source", "agent"}, Counter(ids.values())
    assert len(ids) > 50, sorted(ids)
    assert BASE_PACKAGE not in ids
    assert not [name for name in ids if name.startswith(f"{BASE_PACKAGE}/")]


def test_the_scan_reads_every_part_of_the_app():
    _, read = _repo_scan()
    least = {
        "utk_curio/backend": 300, "utk_curio/sandbox": 20, "utk_curio/frontend": 400,
        "utk_curio/cli": 5, "utk_curio/common": 2, "utk_curio/tools": 2,
        "utk_curio/main.py": 1, "utk_curio/shipped.py": 1,
        "scripts": 10, "curio.py": 1, "setup.py": 1, "MANIFEST.in": 1,
    }
    assert {area: read[area] for area in least if read[area] < least[area]} == {}, read


def test_the_scan_finds_ids_planted_in_app_code(tmp_path):
    """The same scan, on a tree that holds a shipped id in each kind of file
    the scan reads, and the same ids where it does not look."""
    ids = shipped_ids(REPO)
    first = {kind: min(name for name, of in ids.items() if of == kind) for kind in set(ids.values())}
    dataset, node_type, source, agent = (first[k] for k in ("dataset", "node type", "source", "agent"))
    package = node_type.split("/")[0]

    def plant(relative: str, text: str) -> None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    plant("utk_curio/backend/app/feature/rules.py", (
        f'"""Reads {dataset} in a docstring."""\n'
        f"# {agent} in a comment\n"
        f'NAME = "{dataset}@1"\n'
        'PREFIX = f"data.scout.{name}"\n'
        "def pick(kind):\n"
        f'    """{source} in a function\'s docstring."""\n'
        f'    return kind.startswith("scout.") or kind == "{package}"\n'
        'MODEL = re.compile(r"^model\\.scout\\.")\n'
    ))
    plant("utk_curio/frontend/urban-workflows/src/feature/rules.tsx", (
        f"// {node_type} in a comment\n"
        f"/* {source}\n   in a block comment */\n"
        f"const url = 'https://example.org/a'; const t = `${{base}}/{node_type}@1`;\n"
        f'const s = "{source}"; const r = /a\\/b/; // {agent}\n'
        f"const view = <p>{agent}</p>;\n"
        "const m = 'model.scout.' + name; const q = x /* note */ / 2;\n"
        'import logo from "assets/scout.png";\n'
        f"const nested = `a ${{f(`b ${{c}}`)}} {dataset}`;\n"
        f"const k = /* {agent} */ 1;\n"
    ))
    plant("utk_curio/sandbox/util/rules.json", f'{{"source": "{source}"}}\n')
    plant("utk_curio/frontend/urban-workflows/webpack.extra.config.js", f'module.exports = ["{package}@1"];\n')
    plant("scripts/release_step.sh", f"# {dataset}\ncp -r datasets/{dataset}@1 out/\n")
    plant("scripts/scout/new_export.py", f'NAME = "{dataset}"\n')
    plant("setup.py", f'LEFT_OUT = ["{dataset}"]\n')
    plant("utk_curio/frontend/urban-workflows/src/feature/rules.cases.json", f'{{"type": "{node_type}"}}\n')
    # Where it does not look.
    plant("utk_curio/frontend/urban-workflows/src/tests/rules.test.ts", f'const s = "{source}";\n')
    plant("utk_curio/backend/tests/test_rules.py", f'NAME = "{dataset}"\n')
    plant("scripts/scout/export_deep_umbra.py", f'NAME = "{dataset}"\n')
    plant("utk_curio/llm-prompts/prompt.template.md", f"Ask the {agent}.\n")

    hits, _ = scan(tmp_path, ids)
    app = "utk_curio/backend/app/feature/rules.py"
    canvas = "utk_curio/frontend/urban-workflows/src/feature/rules.tsx"
    assert sorted(hits) == sorted([
        Hit(app, 3, dataset),
        Hit(app, 4, "data.scout."),
        Hit(app, 7, "scout."),
        Hit(app, 7, package),
        Hit(app, 8, "model.scout."),
        Hit(canvas, 4, node_type),
        Hit(canvas, 5, source),
        Hit(canvas, 6, agent),
        Hit(canvas, 7, "model.scout."),
        Hit(canvas, 9, dataset),
        Hit("utk_curio/sandbox/util/rules.json", 1, source),
        Hit("utk_curio/frontend/urban-workflows/webpack.extra.config.js", 1, package),
        Hit("scripts/release_step.sh", 2, dataset),
        Hit("scripts/scout/new_export.py", 1, dataset),
        Hit("setup.py", 1, dataset),
        Hit("utk_curio/frontend/urban-workflows/src/feature/rules.cases.json", 1, node_type),
    ])


def test_no_app_code_names_a_shipped_artifact():
    hits, _ = _repo_scan()
    unexpected = [
        f"{hit.path}:{hit.line}: {hit.name}"
        for hit in hits
        if hit.name not in ALLOWED.get(hit.path, (set(), ""))[0]
    ]
    assert not unexpected, (
        "app code names an artifact Curio ships; read what its manifest "
        "declares instead (or name it in words, in a comment):\n" + "\n".join(unexpected)
    )


def test_every_allowed_hit_is_still_there():
    hits, _ = _repo_scan()
    found = {(hit.path, hit.name) for hit in hits}
    stale = sorted(
        (path, name) for path, (names, _) in ALLOWED.items() for name in names if (path, name) not in found
    )
    assert not stale, f"ALLOWED names hits no file holds any more: {stale}"
    assert all(reason for _, reason in ALLOWED.values())


def test_every_script_left_out_is_still_there():
    missing = sorted(relative for relative in NOT_SCANNED if not (REPO / relative).exists())
    assert not missing, f"NOT_SCANNED names scripts that are gone: {missing}"
