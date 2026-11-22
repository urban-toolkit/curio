"""Every shipped package node's code is its settings and one call.

A package node's logic is functions of its package's modules, and its code,
its template's source, holds its settings and returns one call of one of
them; a node that loads is one read of the Data Catalog and its return
(EXTENDING.md, "A node's logic is in its package's functions"). This test
holds every template of every shipped package to that, the built-in
package's left out: its nodes are Curio's own, whose code a person writes.
The tests of each package pin its nodes' code line by line; this one holds
all of them, and the next package's, to one shape.

A template's source is read as the sandbox runs it, inside a function, each
chip (``[!! ... !!]``, as ``code_references`` reads it) standing for the
value or the input it writes. The code holds:

- a docstring first, if any;
- ``from <module> import <names>``, the module one of its package's or of a
  package its manifest names in ``dependencies.packages``, each name one
  that module's ``__all__`` offers;
- settings, ``NAME = <value>``: a literal, a widget chip, a call of one of
  Curio's catalog functions with the item's id written in it, or a list,
  tuple or dict of those;
- one ``return`` of a call of a function it imports, each argument a
  literal, an input or its chip, a setting, a widget chip or a plain cast of
  one (``int``, ``float``, ``str``, ``bool``), one of Curio's functions
  handed whole, a catalog call with the item's id written in it, or a list,
  tuple or dict of those;
- or, for a loader, nothing but one ``return`` of a read of the Data
  Catalog, the item's id written in it or held by a widget.

Curio's catalog functions are those whose argument names an item of a
catalog, as ``skills/node-functions/SKILL.md`` says (read by
``node_functions.read``): Curio reads the id from the code before the node
runs, so the id is written in the call, and such a function is never handed
whole. A read of the Data Catalog is one whose item is a dataset or a
collection.

A Vega-Lite template's source (``.vl.json``) is a spec, not code, so it is
left out.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.packages.domain.package_id import BUILTIN_PACKAGE_ID

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
#: The source of a template that is code, and of one that is a Vega-Lite spec.
CODE_SUFFIX = ".py"
SPEC_SUFFIX = ".vl.json"
#: The casts a widget chip's value may take as an argument.
CASTS = ("int", "float", "str", "bool")
#: The catalog items a read of the Data Catalog names (``node_functions``).
DATA_CATALOG = ("dataset", "collection")
#: The name a chip stands as while the code is parsed, and how to read it back.
CHIP = "_curio_chip_{}_"
CHIP_RE = re.compile(r"^_curio_chip_(\d+)_$")
INPUT_RE = re.compile(r"^input_\d+$")


def _manifests() -> list[tuple[Path, dict]]:
    return [
        (path.parent, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(PACKAGES.glob("*/manifest.json"))
    ]


def _templates() -> list[tuple[str, str, str]]:
    """``(package folder, template id, node type)`` of each shipped template
    whose source is Python code, the built-in package's left out."""
    return [
        (folder.name, template["id"], f"{raw['id']}/{template['id']}")
        for folder, raw in _manifests()
        if raw["id"] != BUILTIN_PACKAGE_ID
        for template in raw.get("templates", [])
        if str(template.get("source") or "").endswith(CODE_SUFFIX)
    ]


TEMPLATES = _templates()


def _source(folder: str, template_id: str) -> str:
    raw = json.loads((PACKAGES / folder / "manifest.json").read_text(encoding="utf-8"))
    (template,) = [t for t in raw["templates"] if t["id"] == template_id]
    return (PACKAGES / folder / template["source"]).read_text(encoding="utf-8")


def _all_of(path: Path) -> tuple[str, ...]:
    """The names a module's ``__all__`` lists; none when it has no ``__all__``."""
    for statement in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in statement.targets
        ):
            return tuple(ast.literal_eval(statement.value))
    return ()


class Rule:
    """What the code of a node of the package in *folder* may name: the
    modules it may import from, with what each offers, and Curio's
    functions."""

    def __init__(self, folder: str):
        from utk_curio.backend.app.agents.domain import node_functions
        from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
        from utk_curio.backend.app.packages.repositories.python_modules import module_files

        manifest = load_package_manifest(PACKAGES / folder)
        #: Each module of the package, and of each package it names, by its
        #: dotted name: what its ``__all__`` offers.
        self.offered: dict[str, tuple[str, ...]] = {}
        for package in (folder, *manifest.package_deps):
            root = PACKAGES / package
            for dotted, path in module_files(root, load_package_manifest(root)):
                self.offered[dotted] = _all_of(path)
        python = [function for function in node_functions.read() if "python" in function.engines]
        self.catalog = {function.name for function in python if function.catalog_arguments}
        self.reads = {
            function.name for function in python
            if any(argument.catalog in DATA_CATALOG for argument in function.catalog_arguments)
        }
        self.handed_whole = {function.name for function in python if not function.catalog_arguments}


def code_problems(code: str, rule: Rule) -> list[str]:
    """Each way *code* is more than its settings and one call, or than a
    loader's one read; none when it is just that."""
    from utk_curio.backend.app.execution.code_references import REFERENCE_RE, parse_reference

    chips: list[tuple[str, dict]] = []

    def stand_in(match: re.Match) -> str:
        chips.append((match.group(0), parse_reference(match.group(1))))
        return CHIP.format(len(chips) - 1)

    text = REFERENCE_RE.sub(stand_in, code)
    try:
        tree = ast.parse("def node():\n" + "\n".join("    " + line for line in text.splitlines()))
    except SyntaxError as error:
        return [f"the code does not parse: {error}"]

    def written(node: ast.AST) -> str:
        """*node* as code, each chip as it is written."""
        return re.sub(r"_curio_chip_(\d+)_", lambda m: chips[int(m.group(1))][0], ast.unparse(node))

    def at(node: ast.AST) -> str:
        return f"line {node.lineno - 1}: {written(node).splitlines()[0]}"

    def chip_of(node: ast.AST) -> dict | None:
        found = CHIP_RE.match(node.id) if isinstance(node, ast.Name) else None
        return chips[int(found.group(1))][1] if found else None

    def literal(node: ast.AST) -> bool:
        try:
            ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return False
        return True

    def as_literal(node: ast.AST) -> bool:
        """A literal, or a chip a run writes as one: any but an input's."""
        chip = chip_of(node)
        return literal(node) or (chip is not None and chip["kind"] != "input")

    def catalog_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in rule.catalog
            and all(as_literal(arg) for arg in node.args)
            and all(keyword.arg is not None and as_literal(keyword.value) for keyword in node.keywords)
        )

    def collection_of(node: ast.AST, each) -> bool:
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return all(each(element) for element in node.elts)
        if isinstance(node, ast.Dict):
            return all(key is not None and literal(key) for key in node.keys) and all(
                each(value) for value in node.values
            )
        return False

    def setting(node: ast.AST) -> bool:
        return as_literal(node) or catalog_call(node) or collection_of(node, setting)

    def argument(node: ast.AST, settings: set) -> bool:
        if as_literal(node) or catalog_call(node):
            return True
        if isinstance(node, ast.Name):
            return (
                chip_of(node) is not None  # an input's chip, a layer's among them
                or INPUT_RE.match(node.id) is not None
                or node.id in settings
                or node.id in rule.handed_whole
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CASTS:
            return len(node.args) == 1 and not node.keywords and (chip_of(node.args[0]) or {}).get("kind") == "widget"
        return collection_of(node, lambda element: argument(element, settings))

    problems: list[str] = []
    statements = list(tree.body[0].body)
    first = statements[0] if statements else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        statements = statements[1:]
    if not statements or not isinstance(statements[-1], ast.Return):
        return ["the code does not end in a return"]
    *head, last = statements
    imported: set = set()
    settings: set = set()
    for statement in head:
        if isinstance(statement, ast.ImportFrom) and statement.level == 0 and statement.module:
            offered = rule.offered.get(statement.module)
            if offered is None:
                problems.append(
                    f"{at(statement)}: {statement.module} is no module of the package or of a package its "
                    "manifest names in dependencies.packages"
                )
                continue
            for alias in statement.names:
                if alias.name in offered:
                    imported.add(alias.asname or alias.name)
                else:
                    problems.append(f"{at(statement)}: {statement.module}'s __all__ does not offer {alias.name}")
        elif isinstance(statement, (ast.Import, ast.ImportFrom)):
            problems.append(f"{at(statement)}: the code imports only functions of its package's modules")
        elif (
            isinstance(statement, ast.Assign) and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            if setting(statement.value):
                settings.add(statement.targets[0].id)
            else:
                problems.append(
                    f"{at(statement)}: no setting: a setting is a literal, a widget, a catalog call with "
                    "its id written in it, or a list, tuple or dict of those"
                )
        else:
            problems.append(
                f"{at(statement)}: this {type(statement).__name__} statement is no import, setting or return"
            )
    call = last.value
    if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
        returned = written(call) if call is not None else "nothing"
        problems.append(f"{at(last)}: returns {returned}, not a call of a function the code imports")
    elif call.func.id in imported:
        for given in [*call.args, *call.keywords]:
            value = given.value if isinstance(given, ast.keyword) else given
            unnamed = isinstance(given, ast.Starred) or (isinstance(given, ast.keyword) and given.arg is None)
            if unnamed or not argument(value, settings):
                problems.append(
                    f"{at(last)}: the argument {written(given)} is no literal, input, setting, widget or its "
                    "cast, Curio function handed whole, catalog call with its id written in it, or a list, "
                    "tuple or dict of those"
                )
    elif call.func.id in rule.reads:
        if head:
            problems.append(f"{at(last)}: a loader's whole code is one read of the Data Catalog and its return")
        if not catalog_call(call):
            problems.append(f"{at(last)}: the read's id is neither written in the code nor held by a widget")
    else:
        problems.append(
            f"{at(last)}: returns {call.func.id}(...), which the code does not import and which is no read "
            "of the Data Catalog"
        )
    return problems


@pytest.mark.parametrize(
    ("folder", "template_id"), [(folder, template) for folder, template, _ in TEMPLATES],
    ids=[node_type for _, _, node_type in TEMPLATES],
)
def test_each_package_nodes_code_is_its_settings_and_one_call(folder, template_id):
    code = _source(folder, template_id)
    assert code_problems(code, Rule(folder)) == [], code


def test_the_rule_reads_every_shipped_packages_code_but_the_built_in_packages():
    """Each shipped package with a node of Python code is read, the built-in
    package left out, and every other template's source is a Vega-Lite
    spec: no other kind of code goes unread."""
    read = {folder for folder, _template, _node_type in TEMPLATES}
    with_code, builtin = set(), set()
    for folder, raw in _manifests():
        sources = [t["source"] for t in raw.get("templates", []) if isinstance(t.get("source"), str)]
        if raw["id"] == BUILTIN_PACKAGE_ID:
            builtin.add(folder.name)
            continue
        assert all(s.endswith((CODE_SUFFIX, SPEC_SUFFIX)) for s in sources), (folder.name, sources)
        if any(s.endswith(CODE_SUFFIX) for s in sources):
            with_code.add(folder.name)
    assert builtin and not builtin & read, builtin
    assert read and read == with_code, (read, with_code)


def _plant(code: str, old: str, new: str) -> str:
    assert code.count(old) == 1, f"{old!r} is not once in the code"
    return code.replace(old, new)


def _sample_video_frames(*replacements: tuple[str, str], then: str = "") -> tuple[str, str, str]:
    """Media's Sample Video Frames with *replacements* made and *then* added
    at its end: ``(package folder, code, its unplanted code)``."""
    code = original = _source("curio.media@1", "video-frames")
    for old, new in replacements:
        code = _plant(code, old, new)
    return "curio.media@1", code + then, original


IMPORT = "from media_collections import sample_video_frames"
CALL = "return sample_video_frames("
EVERY = "every_seconds=EVERY_SECONDS"
#: Code planted with one break of the rule each: how to make it, and the
#: words the problem it must raise holds. Loaders are written whole.
PLANTED = {
    "a-loop": (
        lambda: _sample_video_frames((CALL, "for _ in range(2):\n    pass\n" + CALL)),
        "this For statement is no import, setting or return",
    ),
    "an-import-of-a-function-its-module-keeps": (
        lambda: _sample_video_frames((IMPORT, IMPORT + ", _by_decoding")),
        "media_collections's __all__ does not offer _by_decoding",
    ),
    "an-import-from-a-package-its-manifest-does-not-name": (
        lambda: _sample_video_frames((IMPORT, IMPORT + "\nfrom weather_census import gt65_column")),
        "weather_census is no module of the package",
    ),
    "an-import-of-a-library": (
        lambda: _sample_video_frames((IMPORT, "import numpy as np\n" + IMPORT)),
        "import numpy as np: the code imports only functions",
    ),
    "two-calls": (
        lambda: _sample_video_frames(
            (IMPORT, IMPORT + ", split_audio"), (CALL, "frames = sample_video_frames("),
            then="return split_audio(frames, curio_derived_file)\n",
        ),
        "frames = sample_video_frames(input_0",
    ),
    "a-library-call-in-an-argument": (
        lambda: _sample_video_frames((EVERY, "every_seconds=max(EVERY_SECONDS, 1.0)")),
        "the argument every_seconds=max(EVERY_SECONDS, 1.0)",
    ),
    "a-cast-of-an-input": (
        lambda: _sample_video_frames((EVERY, "every_seconds=float(input_0)")),
        "the argument every_seconds=float(input_0)",
    ),
    "a-catalog-function-handed-whole": (
        lambda: _sample_video_frames(("input_0, curio_derived_file,", "input_0, curio_load_collection,")),
        "the argument curio_load_collection",
    ),
    "a-catalog-read-of-an-id-the-code-does-not-write": (
        lambda: _sample_video_frames(
            ("MAX_FRAMES_PER_VIDEO = 300", "MAX_FRAMES_PER_VIDEO = 300\nROWS = curio_load_collection(input_0)"),
        ),
        "ROWS = curio_load_collection(input_0): no setting",
    ),
    "a-loader-that-reads-a-catalog-path-with-a-library": (
        lambda: (
            "curio.weather@1",
            'import rasterio\n\ndataset_path = curio_data_path("data.example.mrt")\n'
            "src = rasterio.open(dataset_path)\n\nreturn src\n",
            None,
        ),
        "returns src, not a call",
    ),
    "a-loader-that-reads-twice": (
        lambda: (
            "curio.weather@1",
            'rows = curio_load_data("data.example.weather")\nreturn curio_load_data("data.example.census")\n',
            None,
        ),
        "a loader's whole code is one read of the Data Catalog and its return",
    ),
    "a-loader-whose-id-the-code-does-not-write": (
        lambda: ("curio.weather@1", "return curio_load_data(input_0)\n", None),
        "the read's id is neither written in the code nor held by a widget",
    ),
}


@pytest.mark.parametrize("planted", sorted(PLANTED))
def test_the_rule_refuses_code_planted_with(planted):
    """Each planted break fails the rule with its own problem, where the
    shipped code it was planted in passes."""
    make, words = PLANTED[planted]
    folder, code, original = make()
    rule = Rule(folder)
    if original is not None:
        assert code_problems(original, rule) == [], original
    problems = code_problems(code, rule)
    assert any(words in problem for problem in problems), (problems, code)


@pytest.mark.parametrize("code", [
    'return curio_load_data("data.example.mrt")\n',
    '"""A loader."""\n\nreturn curio_load_data([!! dataset !!])\n',
    'return curio_load_collection("data.example.photos")\n',
], ids=["a-dataset-by-id", "a-dataset-a-widget-holds", "a-collection-by-id"])
def test_a_loader_is_one_read_of_the_data_catalog_and_its_return(code):
    """A loader's whole code, a docstring aside, is the return of one read of
    the Data Catalog, its item's id written in it or held by a widget."""
    assert code_problems(code, Rule("curio.weather@1")) == []
