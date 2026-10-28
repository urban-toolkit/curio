"""The page of the functions node code calls, its strict reader, and the pin to the catalogs.

``skills/node-functions/SKILL.md`` lists every function Curio gives a node's
code: its call, the engines whose code has it, what it does and each of its
arguments, an argument that names a catalog's item saying which.
``node_functions.parse`` reads its body, the page after its frontmatter, line
by line and refuses any line of another shape, so the agents' checks can read
from it which arguments name a dataset, a collection, a model or a key.

The pin: the arguments the page says name a Data Catalog item are the first
arguments of exactly the three loaders the backend resolves ids from
(``curio_load_data``, ``curio_data_path``, ``curio_load_collection``), each
``dataset_id``; ``curio_load_model``'s ``model_id`` names a Model Catalog
model, and ``curio_secret``'s ``name`` a Node code key. Renaming one in the
sandbox, or resolving a fourth call, fails here.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE = REPO_ROOT / "agents" / "agent.curio.builtin@1"
#: The skill that gives the functions.
SKILL = REPO_ROOT / "skills" / "node-functions"
#: The loaders whose first argument the backend reads a Data Catalog id from.
LOADERS = {"curio_load_data", "curio_data_path", "curio_load_collection"}

#: A page of one function, each part in its place.
GOOD = """## Functions node code calls

What the page is about.

### curio_one(dataset_id, size=2, *, kind="video", tag=None)

Engines: python, javascript.

Reads one thing.

- `dataset_id` (a Data Catalog dataset): the dataset's id.
- `size`: how many.
- `kind`: what it is.
- `tag` (a Node code key): a key.
"""


def _parse(text: str):
    from utk_curio.backend.app.agents.domain import node_functions

    return node_functions.parse(text)


def test_a_page_reads_as_its_functions_with_their_engines_and_arguments():
    (function,) = _parse(GOOD)
    assert (function.name, function.engines, function.does, function.line) == (
        "curio_one", ("python", "javascript"), "Reads one thing.", 5,
    )
    assert function.call == 'curio_one(dataset_id, size=2, *, kind="video", tag=None)'
    assert [(a.name, a.default, a.keyword_only, a.catalog) for a in function.arguments] == [
        ("dataset_id", None, False, "dataset"),
        ("size", "2", False, None),
        ("kind", '"video"', True, None),
        ("tag", "None", True, "key"),
    ]
    assert function.argument("size").default_value == 2
    assert function.argument("kind").default_value == "video"
    assert [a.name for a in function.catalog_arguments] == ["dataset_id", "tag"]
    two = GOOD + "\n### curio_two()\n\nEngines: python.\n\nReads nothing.\n"
    assert [f.name for f in _parse(two)] == ["curio_one", "curio_two"]
    assert _parse(two)[1].arguments == ()


@pytest.mark.parametrize("change, said", [
    (("(a Data Catalog dataset)", "(a dataset of ours)"), "no catalog phrase"),
    (("Engines: python, javascript.", "Engines: python, r."), "engines are"),
    (("Engines: python, javascript.", "Engines: python, python."), "engines are"),
    (("Engines: python, javascript.", "Engines: Python and JavaScript."), "Engines:"),
    (("- `size`: how many.\n", ""), "has 4 arguments and 3 lines"),
    (("- `size`: how many.\n", "- `size`: how many.\n- `colour`: extra.\n"), "has 4 arguments and 5 lines"),
    (("- `size`: how many.\n- `kind`: what it is.\n", "- `kind`: what it is.\n- `size`: how many.\n"),
     "the bullet names kind"),
    (("- `size`: how many.", "* `size`: how many."), "an argument is"),
    (("Reads one thing.\n\n", "Reads one thing.\nAnd another.\n\n"), "followed by a blank line"),
    (("\nEngines: python, javascript.\n", "\n"), "followed by a blank line"),
    (("size=2", "size=len(x)"), "is no argument"),
    (("size=2, *", "size=2, count, *"), "count has no default but follows"),
    (("tag=None)", "tag=None, *)"), "at most, and an argument after it"),
    (("dataset_id, size=2", "dataset_id, dataset_id"), "names dataset_id twice"),
    (("### curio_one(", "### one("), "a function starts with its call"),
    (("What the page is about.", "- A bullet of prose."), "prose only"),
    (("## Functions node code calls\n", "# Functions node code calls\n"), "starts with its title"),
])
def test_a_line_of_any_other_shape_is_refused_naming_it(change, said):
    from utk_curio.backend.app.agents.domain import node_functions

    old, new = change
    assert old in GOOD
    with pytest.raises(node_functions.NodeFunctionsError, match=said):
        node_functions.parse(GOOD.replace(old, new, 1))


def test_a_function_stated_twice_or_a_gap_between_functions_is_refused():
    from utk_curio.backend.app.agents.domain import node_functions

    block = GOOD.split("\n\n", 2)[2]
    with pytest.raises(node_functions.NodeFunctionsError, match="curio_one is stated twice"):
        node_functions.parse(GOOD + "\n" + block)
    with pytest.raises(node_functions.NodeFunctionsError, match="one blank line goes before"):
        node_functions.parse(GOOD + "\n\n### curio_two()\n\nEngines: python.\n\nReads nothing.\n")
    with pytest.raises(node_functions.NodeFunctionsError, match="ends with its last argument's line"):
        node_functions.parse(GOOD + "\n")


def test_lines_count_from_the_line_the_page_starts_on():
    """The skill's body starts below its frontmatter, so a function's line
    and an error's count from the line of the file the page starts on."""
    from utk_curio.backend.app.agents.domain import node_functions

    (function,) = node_functions.parse(GOOD, first_line=15)
    assert function.line == 19
    with pytest.raises(node_functions.NodeFunctionsError, match=r"SKILL\.md, line 15: the page starts with its title"):
        node_functions.parse(GOOD.replace("## Functions", "# Functions", 1), first_line=15)
    with pytest.raises(node_functions.NodeFunctionsError, match=r"SKILL\.md, line 21: Engines:"):
        node_functions.parse(GOOD.replace("Engines: python, javascript.", "Engines: Python.", 1), first_line=15)


def test_the_page_curio_ships_reads_and_the_preamble_includes_it():
    """Every function it gives, with its engines, read from the skill's body
    as written and each on the line of the file it is on; the preamble every
    agent reads places the skill whole, and the user guides link to it."""
    from utk_curio.backend.app.agents.domain import agent_text, builtin, node_functions, skills

    skill = skills.parse(SKILL)
    assert node_functions.PAGE == "skills/node-functions/SKILL.md" and skill.name == node_functions.SKILL
    functions = node_functions.read()
    assert functions == node_functions.parse(skill.body, first_line=skill.body_line)
    lines = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("\n")
    assert [lines[function.line - 1] for function in functions] == [f"### {function.call}" for function in functions]
    engines = {function.name: function.engines for function in functions}
    assert engines["curio_layer"] == ("python", "javascript")
    assert {name for name, have in engines.items() if have == ("python",)} == set(engines) - {"curio_layer"}
    assert [f.name for f in node_functions.for_engine("javascript", functions)] == ["curio_layer"]
    preamble = (BASE / "default_preamble.md").read_text(encoding="utf-8")
    assert preamble.count("{{skill:" + node_functions.SKILL + "}}") == 1
    page = agent_text.skill_text(node_functions.SKILL)
    for m in builtin.list_builtin_manifests():
        assert builtin.read_prompt_text(m.dir_name, "system").count(page) == 1, m.agent_id


def test_map_edits_call_is_the_one_its_step_defines():
    """A Map Editor node's code is one call of ``curio_edit_features``, and the
    page gives it as ``feature_edits.edit_features`` defines it."""
    from utk_curio.backend.app.agents.domain import node_functions
    from utk_curio.sandbox.util.feature_edits import edit_features

    call = next(f for f in node_functions.read() if f.name == "curio_edit_features").call
    assert call == "curio_edit_features" + str(inspect.signature(edit_features))
    assert call == (
        "curio_edit_features(value, edits, key=None, layer=None, keys=None, new_layers=None, crs=None, "
        "by_input=False)"
    )


def test_the_ids_a_function_names_are_the_ones_the_backend_resolves():
    """The pin. Each argument the page says names a catalog's item is its
    function's first, given by position, and named as the sandbox names it;
    the calls the backend reads Data Catalog ids, model ids and key names
    from are exactly the functions whose argument names one."""
    from utk_curio.backend.app.agents.application import source_grounding
    from utk_curio.backend.app.agents.domain import node_functions
    from utk_curio.backend.app.datasets.domain.code_refs import DATASET_PATH_CALL_RE, MODEL_CALL_RE
    from utk_curio.backend.app.users.connection_keys import SECRET_CALL_RE
    from utk_curio.sandbox.app import worker
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers
    from utk_curio.sandbox.util.secrets import make_curio_secret

    functions = node_functions.read()
    naming = {kind: {f.name for f in functions if any(a.catalog == kind for a in f.arguments)}
              for kind in ("dataset", "collection", "model", "key")}
    assert naming["dataset"] | naming["collection"] == LOADERS == set(source_grounding.data_catalog_calls())
    # The gate's scan reads the id each loader names as a Data Catalog id.
    for name in sorted(LOADERS):
        refs = source_grounding.scan_sources(f'x = {name}("data.utk.x")', "python")
        assert [(ref.kind, ref.literal, ref.call) for ref in refs] == [("catalog-id", "data.utk.x", name)]
    assert naming["collection"] == {"curio_load_collection"}
    assert naming["model"] == {"curio_load_model"}
    assert naming["key"] == {"curio_secret"}
    resolved = {
        "data": {f.name for f in functions if DATASET_PATH_CALL_RE.search(f'{f.name}("data.utk.x")')},
        "model": {f.name for f in functions if MODEL_CALL_RE.search(f'{f.name}("model.curio.x")')},
        "key": {f.name for f in functions if SECRET_CALL_RE.search(f'{f.name}("census")')},
    }
    assert resolved == {"data": LOADERS, "model": naming["model"], "key": naming["key"]}

    namespace = {"curio_secret": make_curio_secret({})}
    install_catalog_helpers(
        namespace, data_path=worker._make_curio_data_path({}), formats=None, collections=None,
        media_dir=None, models=None,
    )
    named = {"dataset": "dataset_id", "collection": "dataset_id", "model": "model_id", "key": "name"}
    for function in functions:
        for position, argument in enumerate(function.arguments):
            if argument.catalog is None:
                continue
            assert (position, argument.default, argument.keyword_only) == (0, None, False), function.call
            assert argument.name == named[argument.catalog], function.call
            first = next(iter(inspect.signature(namespace[function.name]).parameters))
            assert first == argument.name, f"the sandbox's {function.name} takes {first}, the page {argument.name}"
