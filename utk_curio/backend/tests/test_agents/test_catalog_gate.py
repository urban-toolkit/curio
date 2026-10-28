"""What node code an agent writes may name, call and import: the catalog ids gate.

The page of the functions Curio gives node code, the body of
``skills/node-functions/SKILL.md``, says which argument of each function
names an item of a catalog, and which engines have the function. The
grounding gate reads both from it:

- a Data Catalog dataset or collection, a Model Catalog model and a Node code
  key are ones the account has, each written as a string in the call: a model
  the account never added is refused, and the refusal names the Model
  Catalog's Add;
- a function is called only in code of an engine that has it: JavaScript code
  that calls a Python helper is refused;
- a module a package ships is imported only by the nodes that get it: a
  built-in node gets none.

Each refusal reaches the agent as a free correction, at node.create and in
Solve, before anything runs.

New names are read inside each test, so this module imports on a checkout
without them and each test fails on its own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utk_curio.backend.app.agents.application import source_grounding as sg
from utk_curio.backend.app.agents.application.turns import grounding
from utk_curio.backend.tests._support.agent_routes import _auth
from utk_curio.backend.tests.test_agents import test_routes_proposals as routes_proposals
from utk_curio.backend.tests.test_agents import test_routes_turns as routes_turns
from utk_curio.backend.tests.test_agents import test_source_grounding_routes as grounding_routes
from utk_curio.backend.tests.test_agents import test_verified_rounds as verified_rounds

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
#: The skill that gives the functions Curio gives node code.
SKILL = REPO / "skills" / "node-functions"


def _page() -> str:
    """The functions page as written: the skill's body, after its frontmatter."""
    from utk_curio.backend.app.agents.domain import skills

    return skills.parse(SKILL).body

USER = "4343"
PROJECT = "p-gate"
NB = "agent.curio.node-builder@1"
DL = "curio.builtin/data-loading"
CA = "curio.builtin/computation-analysis"
JS = "curio.builtin/js-computation"
VEGA = "curio.builtin/vis-vega"
RASTER_CALCULATOR = "curio.scout/raster-calculator"
DDRNET = "model.curio.ddrnet23-slim"
HEAT = "data.x.heat"
CENSUS = sg.SecretRef("census", "api.census.gov", "query:key")

#: A Raster Calculator's operation: Scout's raster algebra, from its package's module.
RASTERS = (
    "from scout_rasters.raster_algebra import raster_calculate\n\n"
    'return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)'
)

#: A function of each catalog kind the shipped page does not give, appended to it.
MORE_FUNCTIONS = """
### curio_open_table(dataset_id)

Engines: python.

Opens a table.

- `dataset_id` (a Data Catalog dataset): the dataset's id.

### curio_open_photos(dataset_id)

Engines: python.

Opens a collection's photos.

- `dataset_id` (a Data Catalog collection): the collection's id.

### curio_token(name)

Engines: python.

Gives a key's value.

- `name` (a Node code key): the key's name.
"""

#: The templates of the route tests' projects: a loader, and a Python and a
#: JavaScript code node.
TEMPLATES = [
    grounding_routes.TEMPLATES[0],
    {
        "id": "computation-analysis", "label": "Python Computation", "category": "computation",
        "engine": "python", "editor": "code", "description": "Run Python code.",
        "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    },
    {
        "id": "js-computation", "label": "JavaScript Computation", "category": "computation",
        "engine": "javascript", "editor": "code", "description": "Run JavaScript code.",
        "inputPorts": [{"types": ["DATAFRAME"], "cardinality": "[1,n]"}],
        "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
    },
]


def _add_package(user_key: str, dir_name: str) -> None:
    """A package Curio ships, added to *user_key*'s store as Add adds it."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    install_package_from_directory(user_key, PACKAGES / dir_name)


def _gate(
    code: str, *, engine: str | None = "python", node_type: str = CA, catalog_ids=(), secrets=None,
    is_data_loading: bool = False,
):
    """The refusal the gate gives *code* an agent wrote for a node of
    *node_type* in *USER*'s account, as node.create asks it, or None."""
    base = {
        "catalog_paths": {},
        "catalog_ids": {i: sg.CatalogRef(i, i, "csv", "") for i in catalog_ids},
        "texts": [], "verified": {}, "secrets": dict(secrets or {}),
    }
    _verdict, refusal = grounding._gate_generated_content(
        USER, PROJECT, {}, code=code, engine=engine, node_type=node_type, base=base,
        is_data_loading=is_data_loading,
    )
    return refusal


@pytest.fixture()
def project(client, user_and_token):
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    routes_proposals.TestNodeCreate()._write_builtin_package(_user_dir_key(user), templates=TEMPLATES)
    body = {"name": "p", "spec": {"dataflow": {"nodes": [], "edges": [], "packages": []}}, "outputs": []}
    resp = client.post("/api/projects", json=body, headers=_auth(token))
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()["id"]


def _refused_create(calls) -> str:
    """The text the agent got back for the node.create the gate refused."""
    [refusal] = [
        text for text in grounding_routes._tool_results(calls[-1], "node.create")
        if "refused" in text.split("\n", 1)[0]
    ]
    return refusal


class TestModelIds:
    """``curio_load_model``'s argument names a Model Catalog model: one this
    account added, as ``models.search`` lists them."""

    def test_a_model_the_account_never_added_is_refused_naming_the_model_catalogs_add(self, app, tmp_curio):
        _add_package(USER, f"{DDRNET}@1")
        for added in (DDRNET, f"{DDRNET}@1"):
            assert _gate(f'model = curio_load_model("{added}")\nreturn curio_segment(input_0, model)') is None, added
        for made_up in ("model.curio.ghost-segmenter", f"{DDRNET}@2"):
            refusal = _gate(f'model = curio_load_model("{made_up}")\nreturn curio_segment(input_0, model)')
            assert refusal and f"curio_load_model({made_up!r}) (line 1)" in refusal, (made_up, refusal)
            assert "Add in the Model Catalog" in refusal, refusal
            # The refusal lists the models the account has, to load one of them,
            # and asks for no data source: none is missing.
            assert DDRNET in refusal, refusal
            assert "Allowed sources" not in refusal and "ask the user for a path" not in refusal, refusal

    def test_node_create_with_a_made_up_model_id_proposes_nothing(
        self, client, user_and_token, tmp_curio, project, monkeypatch,
    ):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        _add_package(_user_dir_key(user), f"{DDRNET}@1")
        grounding_routes._install(client, token, project, NB)
        att = grounding_routes._attach(client, token, project, NB)
        code = 'model = curio_load_model("model.curio.ghost-segmenter")\nreturn curio_segment(input_0, model)'
        calls = grounding_routes._script(monkeypatch, [
            grounding_routes._create_tail(code, node_type=CA), "That model is not in your account.",
        ])
        body = grounding_routes._run(client, token, project, att, "segment the photos")
        assert grounding_routes._proposals(body) == []
        refusal = _refused_create(calls)
        assert "curio_load_model('model.curio.ghost-segmenter') (line 1)" in refusal
        assert "Add in the Model Catalog" in refusal and DDRNET in refusal


class TestEngines:
    """A function the page gives is called only in code of an engine its
    ``Engines:`` line names. A template's engine is its code's only when its
    nodes hold code: a Vega-Lite or Autark node's template names ``python``,
    and its content is a document."""

    def test_a_function_the_nodes_engine_lacks_is_refused(self, tmp_curio):
        loads = f'const rows = curio_load_data("{HEAT}");\nreturn rows;'
        refusal = _gate(loads, engine="javascript", node_type=JS, catalog_ids=[HEAT])
        assert refusal and "curio_load_data (line 1)" in refusal and "javascript" in refusal, refusal
        # The same call in Python is grounded, and JavaScript code has curio_layer.
        assert _gate(f'rows = curio_load_data("{HEAT}")\nreturn rows', catalog_ids=[HEAT]) is None
        layer = 'return curio_layer(input_0, "table_osm_roads");'
        assert _gate(layer, engine="javascript", node_type=JS) is None
        # A call a comment or a string only names is no call.
        named = f'// curio_load_data("{HEAT}") is for Python nodes\nconst note = "curio_secret(\'x\')";\n' + layer
        assert _gate(named, engine="javascript", node_type=JS, catalog_ids=[HEAT]) is None
        # A document holds no code: its template's engine judges nothing.
        spec = '{"mark": "bar", "description": "rows from curio_load_data(\\"elsewhere\\")"}'
        assert _gate(spec, engine=None, node_type=VEGA) is None

    def test_a_curio_name_the_page_does_not_give_is_refused(self, tmp_curio):
        """A call of a ``curio_`` name no function of the page has, which the
        code neither defines nor imports, is refused, naming the functions
        code of the node's engine has."""
        refusal = _gate(f'rows = curio_load_frame("{HEAT}")\nreturn rows', catalog_ids=[HEAT])
        assert refusal and "curio_load_frame (line 1)" in refusal and "curio_load_data" in refusal, refusal
        refusal = _gate("return curio_fetch_rows(input_0);", engine="javascript", node_type=JS)
        assert refusal and "curio_fetch_rows (line 1)" in refusal and "curio_layer" in refusal, refusal
        # A function the code defines or imports itself, or a method, is the code's own.
        assert _gate("def curio_helper(df):\n    return df\nreturn curio_helper(input_0)") is None
        assert _gate("from math import floor as curio_floor\nreturn curio_floor(2.5)") is None
        assert _gate("return frames.curio_frame(1)") is None
        own = "function curio_helper(x) { return x; }\nreturn curio_helper(input_0);"
        assert _gate(own, engine="javascript", node_type=JS) is None
        # A name JavaScript destructures from a value of its own is the code's own too.
        for bound in (
            "const { curio_rows } = helpers;\nreturn curio_rows(input_0);",
            "let { size, curio_rows } = helpers;\nreturn curio_rows(input_0);",
            "var [curio_rows] = [(x) => x];\nreturn curio_rows(input_0);",
        ):
            assert _gate(bound, engine="javascript", node_type=JS) is None, bound

    def test_node_create_of_javascript_that_calls_curio_load_data_proposes_nothing(
        self, client, user_and_token, tmp_curio, project, monkeypatch,
    ):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="heat.csv")
        grounding_routes._install(client, token, project, NB)
        att = grounding_routes._attach(client, token, project, NB)
        code = f'const rows = curio_load_data("{dataset_id}");\nreturn rows;'
        calls = grounding_routes._script(monkeypatch, [
            grounding_routes._create_tail(code, node_type=JS), "A JavaScript node cannot load it.",
        ])
        body = grounding_routes._run(client, token, project, att, "load the heat data in a JavaScript node")
        assert grounding_routes._proposals(body) == []
        refusal = _refused_create(calls)
        assert "curio_load_data (line 1)" in refusal and "javascript" in refusal

    def test_solve_refuses_it_before_the_sandbox_and_corrects_it(self, client, user_and_token, tmp_curio, monkeypatch):
        user, token = user_and_token
        solve_node = verified_rounds.TestSolveNode()
        ctx = solve_node._setup(
            client, user, token, monkeypatch, node_type="curio.builtin/custom-js@1",
            content='const rows = curio_load_data("{DATASET}");\nreturn rows;',
            child_replies=["return [1, 2, 3];"],
        )
        done = solve_node._solve_node(client, token, ctx)[-1][1]
        first = done["attempts"][0]
        # The code's own violation: no source is missing, so no Dataset Finder.
        assert first["source"] == "current content" and first["kind"] == "ungrounded-code", first
        assert "curio_load_data (line 1)" in first["detail"] and "javascript" in first["detail"], first
        assert done["verdict"] == "pass"
        # Only the correction reached the sandbox.
        assert ctx["endpoints"] == ["/execJs"], ctx["endpoints"]
        assert "curio_load_data" not in ctx["payloads"][0]["code"]


class TestThePage:
    """Which argument names which catalog's item is read from the page: a
    function the page gives is checked by the phrase of its argument."""

    def test_each_argument_that_names_a_catalog_item_is_read_from_the_page(self, tmp_curio, monkeypatch):
        from utk_curio.backend.app.agents.domain import node_functions

        functions = node_functions.parse(_page() + MORE_FUNCTIONS)
        monkeypatch.setattr(node_functions, "read", lambda: functions)
        secrets = {"census": CENSUS}
        assert _gate(f't = curio_open_table("{HEAT}")\nreturn t', catalog_ids=[HEAT]) is None
        assert _gate('k = curio_token("census")\nreturn k', secrets=secrets) is None
        for code, said in (
            ('t = curio_open_table("data.x.ghost")\nreturn t', "curio_open_table('data.x.ghost') (line 1)"),
            ('p = curio_open_photos("data.x.ghost")\nreturn p', "curio_open_photos('data.x.ghost') (line 1)"),
            ('k = curio_token("noaa")\nreturn k', "curio_token('noaa') (line 1)"),
        ):
            refusal = _gate(code, catalog_ids=[HEAT], secrets=secrets)
            assert refusal and said in refusal, (code, refusal)
        # The kind each argument names is in the refusal.
        assert "collection" in _gate('p = curio_open_photos("data.x.ghost")\nreturn p', catalog_ids=[HEAT])
        assert "saved: census" in _gate('k = curio_token("noaa")\nreturn k', secrets=secrets)

    def test_an_id_the_code_computes_is_refused(self, tmp_curio):
        """Curio reads a catalog item's id from the code before the node runs,
        so the code writes it as a string, first in the call."""
        for code, call in (
            (f'name = "{HEAT}"\nrows = curio_load_data(name)\nreturn rows', "curio_load_data"),
            (f'rows = curio_load_data(dataset_id="{HEAT}")\nreturn rows', "curio_load_data"),
            ('photos = curio_load_collection(f"data.x.{year}")\nreturn photos', "curio_load_collection"),
            ('model = curio_load_model(MODEL_ID)\nreturn model', "curio_load_model"),
            ('key = curio_secret(names[0])\nreturn key', "curio_secret"),
        ):
            refusal = _gate(code, catalog_ids=[HEAT], secrets={"census": CENSUS})
            assert refusal and f"{call} (line " in refusal and "as a string in the call" in refusal, (code, refusal)

    def test_the_content_builders_rule_names_every_call_the_gate_reads_an_id_from(self, tmp_curio, monkeypatch):
        """The rule Solve hands a content builder (``sourceGrounding``) names
        the calls the gate reads a Data Catalog id from, as the page gives
        them, and code that follows it is grounded."""
        from utk_curio.backend.app.agents.domain import node_functions

        ctx = sg.GroundingContext(catalog_ids={HEAT: sg.CatalogRef(HEAT, "Heat", "csv", "")})

        def loaders():
            return [f.name for f in node_functions.read() if f.arguments and f.arguments[0].catalog in ("dataset", "collection")]

        rule = grounding._source_grounding_inputs(ctx)["rule"]
        assert loaders(), "the page gives the loaders"
        for name in loaders():
            assert f'{name}("<id>")' in rule, (name, rule)
            assert _gate(f'x = {name}("{HEAT}")\nreturn x', catalog_ids=[HEAT]) is None, name
        # It follows the page.
        functions = node_functions.parse(_page() + MORE_FUNCTIONS)
        monkeypatch.setattr(node_functions, "read", lambda: functions)
        rule = grounding._source_grounding_inputs(ctx)["rule"]
        assert 'curio_open_table("<id>")' in rule and 'curio_open_photos("<id>")' in rule, rule


class TestChips:
    """A chip in a catalog argument is read as the run writes it before the
    node runs, from the node's widgets, inputs and tags. One the gate cannot
    resolve leaves that argument unjudged."""

    def test_a_chip_names_the_model_its_widget_holds(self, app, tmp_curio):
        _add_package(verified_rounds.KEY, f"{DDRNET}@1")
        code = "model = curio_load_model([!! model !!])\nreturn curio_segment(input_0, model)"

        def solve(model_id):
            node = {
                "id": "n1", "type": CA, "goal": "segment the photos", "content": "",
                "metadata": {"widgets": [{"name": "model", "type": "text", "default": model_id}]},
            }
            exec_fn = verified_rounds._Exec()
            _events, outcome, _inputs = verified_rounds._rounds(
                app, node, replies=[code, "df = input_0[0]\nreturn df"], exec_fn=exec_fn,
            )
            return outcome, exec_fn

        outcome, exec_fn = solve("model.curio.ghost-segmenter")
        first = outcome["attempts"][0]
        assert first["kind"] == "ungrounded-code" and "model.curio.ghost-segmenter" in first["detail"], first
        assert len(exec_fn.calls) == 1, "only the correction reached the sandbox"
        outcome, _exec_fn = solve(DDRNET)
        assert outcome["attempts"][0]["verdict"] == "pass", outcome["attempts"][0]

    def test_a_chip_the_gate_cannot_resolve_is_not_judged(self, tmp_curio):
        """Here the gate has no dataflow to resolve the chips with: their
        arguments are neither refused as computed nor checked as ids, while an
        id the code writes beside them still is."""
        code = (
            "model = curio_load_model([!! model !!])\n"
            'rows = curio_load_data("[!! dataset !!]")\n'
            'other = curio_load_model("model.curio.ghost-segmenter")\n'
            "return rows"
        )
        refusal = _gate(code)
        assert refusal and "curio_load_model('model.curio.ghost-segmenter') (line 3)" in refusal, refusal
        assert "(line 1)" not in refusal and "(line 2)" not in refusal, refusal
        # A loader whose id is such a chip reads a source: the node is not refused for having none.
        assert _gate("rows = curio_load_data([!! dataset !!])\nreturn rows", node_type=DL, is_data_loading=True) is None


class TestLayerGroups:
    """A layer group's own id (an OSM extract's, a GeoPackage's), which
    ``curio_load_data`` loads as its layers and a Data widget holds once such
    a file is dropped on its node, is known to the gate when its layers are
    the account's."""

    GROUP = "osm.x1a2b3c4d"
    LAYERS = [
        {"id": "imported.xbuildings", "groupId": "osm.x1a2b3c4d", "title": "Manhattan (buildings)",
         "format": "parquet", "path": "/store/imported.xbuildings@1/data/buildings.parquet", "layerName": "buildings"},
        {"id": "imported.xroads", "groupId": "osm.x1a2b3c4d", "title": "Manhattan (roads)",
         "format": "parquet", "path": "/store/imported.xroads@1/data/roads.parquet", "layerName": "roads"},
    ]

    def test_code_that_loads_a_group_whose_layers_are_listed_passes(self, tmp_curio):
        _by_path, by_id = grounding._catalog_grounding_refs(PROJECT, self.LAYERS)
        group = by_id.get(self.GROUP)
        assert group is not None, sorted(by_id)
        assert (group.title, group.format) == ("Manhattan", "osm")
        code = f'layers = curio_load_data("{self.GROUP}")\nreturn layers'
        assert _gate(code, node_type=DL, catalog_ids=list(by_id), is_data_loading=True) is None

    def test_a_group_none_of_whose_layers_is_listed_is_refused(self, tmp_curio):
        _by_path, by_id = grounding._catalog_grounding_refs(PROJECT, self.LAYERS)
        refusal = _gate(
            'layers = curio_load_data("osm.x99999999")\nreturn layers',
            node_type=DL, catalog_ids=list(by_id), is_data_loading=True,
        )
        assert refusal and "osm.x99999999" in refusal, refusal


class TestImports:
    """A module a package ships is handed only to the nodes of that package and
    of the packages that depend on it, as a run hands it out; a built-in node
    gets none. An import of any other module, a library's, is not judged."""

    def test_a_module_the_nodes_template_does_not_get_is_refused(self, app, tmp_curio):
        _add_package(USER, "curio.scout@1")
        refusal = _gate(RASTERS, node_type=CA)
        assert refusal and "import scout_rasters (line 1)" in refusal, refusal
        # The refusal names the nodes that import it.
        assert "Raster Calculator" in refusal and RASTER_CALCULATOR in refusal, refusal
        assert _gate(RASTERS, node_type=RASTER_CALCULATOR) is None
        # A library is the sandbox's to judge.
        assert _gate("import pandas as pd\nimport numpy\nreturn pd.DataFrame()", node_type=CA) is None
        # A module of a package the account has not added is refused too.
        refusal = _gate("from deep_umbra.deep_umbra import season_factor\nreturn season_factor(1)", node_type=CA)
        assert refusal and "import deep_umbra (line 1)" in refusal and "has not added" in refusal, refusal

    def test_solve_refuses_the_import_before_the_sandbox(self, app, tmp_curio):
        routes_proposals.TestNodeCreate()._write_builtin_package(verified_rounds.KEY, templates=verified_rounds.TEMPLATES)
        _add_package(verified_rounds.KEY, "curio.scout@1")
        node = {"id": "n1", "type": CA, "goal": "subtract the two rasters", "content": ""}
        exec_fn = verified_rounds._Exec()
        _events, outcome, inputs = verified_rounds._rounds(
            app, node, replies=[RASTERS, "df = input_0[0]\nreturn df"], exec_fn=exec_fn,
        )
        first = outcome["attempts"][0]
        assert first["kind"] == "ungrounded-code" and "scout_rasters" in first["detail"], first
        assert outcome["verdict"] == "pass" and len(exec_fn.calls) == 1
        assert "scout_rasters" not in exec_fn.calls[0]["code"]
        assert "import scout_rasters (line 1)" in inputs[1]["validationError"]


class TestTheCodesOwnRefusal:
    """A Solve round the gate refuses only for the code's own calls and
    imports fails as ``ungrounded-code``: no source is missing, so the node's
    failure does not send the user to the Dataset Finder."""

    def test_a_loader_refused_for_its_model_alone_fails_without_the_dataset_finder(
        self, client, user_and_token, tmp_curio, project, monkeypatch,
    ):
        user, token = user_and_token
        dataset_id = routes_turns.TestDatasetFinderTools()._seed_dataset(user, filename="heat_tracts.csv")
        loader = (
            'import pandas as pd\nmodel = curio_load_model("model.curio.ghost-segmenter")\n'
            f'df = pd.read_csv(curio_data_path("{dataset_id}"))\nreturn df'
        )

        def child(frame):
            return loader if f'"nodeType": "{DL}"' in frame else "df = input_0[0]\nreturn df.describe()"

        ran: list = []
        monkeypatch.setattr(
            "utk_curio.backend.app.execution.runner._http_exec",
            lambda endpoint, payload: ran.append(payload) or {
                "stdout": [], "stderr": "", "output": {"path": "art-1", "dataType": "dataframe"}},
        )
        solve = grounding_routes.TestSolveSourceGrounding()
        att, applied, _calls = solve._applied_plan(client, user, token, project, monkeypatch, child)
        body = solve._solve(client, token, project, att)
        load = next(n["id"] for n in applied["appliedGraph"]["nodes"] if str(n.get("type", "")).startswith(DL))
        result = body["results"][load]
        assert result["status"] == "failed", result
        assert result["attempts"] and all(a["kind"] == "ungrounded-code" for a in result["attempts"]), result
        assert "model.curio.ghost-segmenter" in result["error"], result["error"]
        assert "Dataset Finder" not in result["error"], result["error"]
        # Nothing it refused reached the sandbox.
        assert all("ghost-segmenter" not in payload["code"] for payload in ran)
