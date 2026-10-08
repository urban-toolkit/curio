"""New node from a Python function (#662, step 21: SCOUT's Compute Catalog, the Curio way).

- Reading a module: its public functions, with each parameter's name, kind,
  default and annotation, read from the source with ``ast``, never by
  importing or running it. ``*args``, ``**kwargs`` and ``async`` are refused
  with a message, and so is a module that does not parse.
- The widget a parameter suggests, from its annotation or its default, in the
  Widgets tab's own shape: every suggestion passes the tab's check.
- The written template: its code imports the function and returns its call,
  with ``[!! name !!]`` for a widget, ``[!! input k !!]`` for an input and a
  literal for a fixed value.
- The listing and the template the routes answer with, read from the store.
- The template runs: added to a new package through the factory install, its
  node imports the function from the package it depends on, runs in the
  sandbox, and a new widget value gives a new result.

New code is imported inside each test, so a checkout without it fails each
test on its own instead of the whole module at collection.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from utk_curio.backend.app.packages.application.store_install import install_package_from_archive

SOURCE_ID = "ai.test.fnsrc"
NODE_PACKAGE = "ai.test.fnnode"

OPS = (
    '"""Scaling helpers."""\n'
    "import json\n"
    "\n"
    "def scale(value: float, factor: int = 2, *, label: str = \"x\"):\n"
    '    """Scale a value.\n'
    "\n"
    '    The label leads the result."""\n'
    "    return f\"{label}:{value * factor}\"\n"
    "\n"
    "def _hidden(x):\n"
    "    return x\n"
)
MODULES = {
    "fn_scale/__init__.py": "def version():\n    return 1\n",
    "fn_scale/ops.py": OPS,
    "fn_broken.py": "def broken(:\n    pass\n",
}


def _manifest(package_id: str) -> dict:
    return {
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test",
        "description": "Test package", "license": "MIT",
        "compatibility": {"curioRuntime": ">=0.5.0", "major": 1},
        "permissions": [], "dependencies": {"packages": {}, "python": {}, "js": {}},
        "createdAt": "2026-06-01T12:00:00Z",
        "templates": [{
            "id": "caller", "label": "Caller", "category": "computation", "engine": "python",
            "editor": "code", "hasCode": True, "hasWidgets": False, "hasGrammar": False,
            "inputPorts": [], "outputPorts": [{"types": ["JSON"], "cardinality": "1"}],
            "source": "sources/caller.py",
        }],
    }


def _archive(package_id: str = SOURCE_ID, modules=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest(package_id)))
        zf.writestr("sources/caller.py", "return 1\n")
        for relative, text in (MODULES if modules is None else modules).items():
            zf.writestr(f"sources/{relative}", text)
    return buf.getvalue()


def _read(source: str, module: str = "m"):
    from utk_curio.backend.app.packages.domain.function_nodes import read_functions

    return {f.name: f for f in read_functions(source, module)}


def _param(source: str, name: str):
    from utk_curio.backend.app.packages.domain.function_nodes import read_functions

    (function,) = read_functions(source, "m")
    return next(p for p in function.parameters if p.name == name)


# ---------------------------------------------------------------------------
# Reading a module
# ---------------------------------------------------------------------------

class TestReadingAModule:
    def test_names_kinds_defaults_and_annotations(self):
        from utk_curio.backend.app.packages.domain.function_nodes import (
            KEYWORD_ONLY, POSITIONAL, POSITIONAL_ONLY,
        )

        (fn,) = _read(
            "def f(a, /, b: int, c: float = 2.5, *, d: 'str' = 'x', e=os.sep):\n    pass\n"
        ).values()
        assert [(p.name, p.kind, p.annotation) for p in fn.parameters] == [
            ("a", POSITIONAL_ONLY, None),
            ("b", POSITIONAL, "int"),
            ("c", POSITIONAL, "float"),
            ("d", KEYWORD_ONLY, "'str'"),
            ("e", KEYWORD_ONLY, None),
        ]
        a, b, c, d, e = fn.parameters
        assert (a.has_default, b.has_default) == (False, False)
        assert (c.default_text, c.default, c.literal_default) == ("2.5", 2.5, True)
        assert (d.default_text, d.default, d.literal_default) == ("'x'", "x", True)
        # A default that is not a literal is kept as written, with no value.
        assert (e.has_default, e.default_text, e.literal_default) == (True, "os.sep", False)
        assert "default" not in e.to_json() and e.to_json()["defaultText"] == "os.sep"

    def test_keyword_only_parameters_keep_their_defaults(self):
        (fn,) = _read("def f(*, zoom: int = 16, mode='fast', flag: bool):\n    pass\n").values()
        assert [(p.name, p.has_default, p.default) for p in fn.parameters] == [
            ("zoom", True, 16), ("mode", True, "fast"), ("flag", False, None),
        ]

    def test_only_public_top_level_functions_and_the_first_paragraph_of_the_docstring(self):
        found = _read(
            "def a():\n    '''First line\n    goes on.\n\n    Second paragraph.'''\n"
            "    def inner():\n        pass\n"
            "def _private():\n    pass\n"
            "class C:\n    def method(self):\n        pass\n"
            "def b():\n    return 1\n"
            "def b(x):\n    return x\n"
        )
        assert list(found) == ["a", "b"]
        assert found["a"].doc == "First line goes on."
        # A later definition replaces an earlier one, as it does when the module runs.
        assert [p.name for p in found["b"].parameters] == ["x"]

    @pytest.mark.parametrize("source, words", [
        ("def f(a, *rest):\n    pass\n", "takes *rest"),
        ("def f(a, **options):\n    pass\n", "takes **options"),
        ("async def f(a):\n    pass\n", "async"),
    ])
    def test_args_kwargs_and_async_are_listed_with_why_and_refused(self, source, words):
        from utk_curio.backend.app.packages.domain.function_nodes import FunctionSourceError, read_function

        (fn,) = _read(source).values()
        assert fn.problem and words in fn.problem
        with pytest.raises(FunctionSourceError, match=words.replace("*", r"\*")):
            read_function(source, "m", "f")

    def test_a_module_that_does_not_parse_says_where(self):
        from utk_curio.backend.app.packages.domain.function_nodes import FunctionSourceError, read_functions

        with pytest.raises(FunctionSourceError, match=r"^fn_broken does not parse: line 1: "):
            read_functions("def broken(:\n    pass\n", "fn_broken")

    def test_a_function_it_does_not_define_is_refused(self):
        from utk_curio.backend.app.packages.domain.function_nodes import FunctionSourceError, read_function

        with pytest.raises(FunctionSourceError, match="defines no public function named '_hidden'"):
            read_function(OPS, "fn_scale.ops", "_hidden")

    def test_the_module_is_never_imported_or_run(self, tmp_path):
        marker = tmp_path / "ran.txt"
        source = (
            "import a_library_nobody_installed\n"
            f"open({str(marker)!r}, 'w').write('ran')\n"
            "raise SystemExit(3)\n"
            "def f(x: int = 1):\n    return x\n"
        )
        assert list(_read(source)) == ["f"]
        assert not marker.exists()


# ---------------------------------------------------------------------------
# The widget a parameter suggests
# ---------------------------------------------------------------------------

class TestTheWidgetAParameterSuggests:
    @pytest.mark.parametrize("signature, widget", [
        ("x: bool", {"type": "checkbox", "default": False}),
        ("x: bool = True", {"type": "checkbox", "default": True}),
        ("x: int = 16", {"type": "number", "default": 16, "options": {"step": 1}}),
        ("x: int = 2.5", {"type": "number", "default": 0, "options": {"step": 1}}),
        ("x: float = 0.5", {"type": "number", "default": 0.5}),
        ("x: int | float = 3", {"type": "number", "default": 3}),
        ("x: str = 'winter'", {"type": "text", "default": "winter"}),
        ("x: 'str'", {"type": "text", "default": ""}),
        ("x: Literal['spring', 'winter'] = 'winter'",
         {"type": "choice", "default": "winter", "options": {"choices": ["spring", "winter"]}}),
        ("x: typing.Literal['a', 'b'] = 'c'",
         {"type": "choice", "default": "a", "options": {"choices": ["a", "b"]}}),
        ("x: Optional[int] = None", {"type": "number", "default": 0, "options": {"step": 1}}),
        ("x: int | None = None", {"type": "number", "default": 0, "options": {"step": 1}}),
        ("x: list[str] = ['a']", {"type": "text-list", "default": ["a"]}),
        ("x: List[float]", {"type": "number-list", "default": []}),
        ("x: tuple[int, ...] = (1, 2)", {"type": "number-list", "default": [1, 2]}),
        ("x: datetime.datetime = None", {"type": "datetime", "default": "1970-01-01T00:00:00"}),
        ("x=True", {"type": "checkbox", "default": True}),
        ("x=16", {"type": "number", "default": 16, "options": {"step": 1}}),
        ("x=0.25", {"type": "number", "default": 0.25}),
        ("x='fast'", {"type": "text", "default": "fast"}),
        ("x=['a', 'b']", {"type": "text-list", "default": ["a", "b"]}),
        ("x=[1, 2.5]", {"type": "number-list", "default": [1, 2.5]}),
    ])
    def test_from_the_annotation_else_the_default(self, signature, widget):
        from utk_curio.backend.app.packages.domain.function_nodes import suggest_widget

        assert suggest_widget(_param(f"def f({signature}):\n    pass\n", "x")) == {
            "name": "x", "label": "X", **widget,
        }

    @pytest.mark.parametrize("signature", [
        "x",
        "x=None",
        "x=[]",
        "x: gpd.GeoDataFrame",
        "x: list",
        "x: Literal[1, 2]",
        "x: dict[str, int] = {}",
        "x=os.sep",
        "höhe: int = 1",
    ])
    def test_none_when_nothing_fits(self, signature):
        from utk_curio.backend.app.packages.domain.function_nodes import read_functions, suggest_widget

        (fn,) = read_functions(f"def f({signature}):\n    pass\n", "m")
        assert suggest_widget(fn.parameters[0]) is None

    def test_every_suggestion_passes_the_widgets_tab_check(self):
        from utk_curio.backend.app.execution.code_references import check_widget_def
        from utk_curio.backend.app.packages.domain.function_nodes import read_functions, suggest_widget

        (fn,) = read_functions(
            "def f(a: bool, b: int = 3, c: float = 1.5, d: str = 'q', e: Literal['x', 'y'] = 'y',"
            " g: list[str] = ['k'], h: list[int] = [1], i: datetime = None, j=2, k=2.5, l='t',"
            " m=['u'], n=[1.5], o: int = 2.5, p: Literal['x'] = 'z'):\n    pass\n",
            "m",
        )
        suggestions = [suggest_widget(p) for p in fn.parameters]
        assert all(suggestions)
        for widget in suggestions:
            assert check_widget_def(widget) is None, widget

    def test_the_label_reads_like_a_label(self):
        from utk_curio.backend.app.packages.domain.function_nodes import widget_label

        assert widget_label("max_height") == "Max height"
        assert widget_label("_zoom_") == "Zoom"

    def test_what_the_dialog_starts_a_parameter_at(self):
        from utk_curio.backend.app.packages.domain.function_nodes import read_functions, suggested_use

        (fn,) = read_functions("def f(gdf, zoom: int = 16, out=os.sep):\n    pass\n", "m")
        assert [suggested_use(p) for p in fn.parameters] == ["input", "widget", "default"]


# ---------------------------------------------------------------------------
# The template's code
# ---------------------------------------------------------------------------

class TestTheTemplateCode:
    def test_it_imports_the_function_and_returns_its_call(self):
        from utk_curio.backend.app.packages.domain.function_nodes import read_function, template_code

        fn = read_function(OPS, "fn_scale.ops", "scale")
        code = template_code("fn_scale.ops", fn, {
            "value": {"use": "input", "slot": 0},
            "factor": {"use": "widget"},
            "label": {"use": "fixed", "value": " 'scaled' "},
        })
        assert code == (
            "from fn_scale.ops import scale\n"
            "\n"
            "return scale(\n"
            "    value=[!! input_0 !!],\n"
            "    factor=[!! factor !!],\n"
            "    label='scaled',\n"
            ")\n"
        )

    def test_a_parameter_left_at_its_default_is_left_out(self):
        from utk_curio.backend.app.packages.domain.function_nodes import read_function, template_code

        fn = read_function(OPS, "fn_scale.ops", "scale")
        code = template_code("fn_scale.ops", fn, {
            "value": {"use": "widget"}, "factor": {"use": "default"}, "label": {"use": "default"},
        })
        assert code == "from fn_scale.ops import scale\n\nreturn scale(value=[!! value !!])\n"

    def test_positional_only_parameters_go_by_position(self):
        from utk_curio.backend.app.packages.domain.function_nodes import read_function, template_code

        source = "def f(a, b=3, /, c=4):\n    pass\n"
        fn = read_function(source, "m", "f")
        assert template_code("m", fn, {
            "a": {"use": "input", "slot": 0},
            "b": {"use": "default"},
            "c": {"use": "fixed", "value": "5"},
        }) == "from m import f\n\nreturn f(\n    [!! input_0 !!],\n    c=5,\n)\n"
        # A skipped positional-only parameter before a given one is written out.
        source = "def f(a=3, b=0, /):\n    pass\n"
        fn = read_function(source, "m", "f")
        assert template_code("m", fn, {"a": {"use": "default"}, "b": {"use": "widget"}}) == (
            "from m import f\n\nreturn f(\n    3,\n    [!! b !!],\n)\n"
        )

    def test_a_skipped_positional_only_default_that_is_not_a_literal_is_refused(self):
        from utk_curio.backend.app.packages.domain.function_nodes import (
            FunctionSourceError, read_function, template_code,
        )

        fn = read_function("def f(a=os.sep, b=0, /):\n    pass\n", "m", "f")
        with pytest.raises(FunctionSourceError, match="a comes before b, which is passed by position"):
            template_code("m", fn, {"a": {"use": "default"}, "b": {"use": "widget"}})

    @pytest.mark.parametrize("value, words", [
        ("winter", "is not a Python literal"),
        ("os.sep", "is not a Python literal"),
        ("", "Give label a value"),
        (None, "Give label a value"),
    ])
    def test_a_fixed_value_must_be_a_literal(self, value, words):
        from utk_curio.backend.app.packages.domain.function_nodes import (
            FunctionSourceError, read_function, template_code,
        )

        fn = read_function(OPS, "fn_scale.ops", "scale")
        with pytest.raises(FunctionSourceError, match=words):
            template_code("fn_scale.ops", fn, {
                "value": {"use": "widget"}, "factor": {"use": "default"},
                "label": {"use": "fixed", "value": value},
            })

    def test_a_parameter_without_a_default_cannot_keep_it(self):
        from utk_curio.backend.app.packages.domain.function_nodes import (
            FunctionSourceError, read_function, template_code,
        )

        fn = read_function(OPS, "fn_scale.ops", "scale")
        with pytest.raises(FunctionSourceError, match="value has no default"):
            template_code("fn_scale.ops", fn, {
                "value": {"use": "default"}, "factor": {"use": "default"}, "label": {"use": "default"},
            })

    def test_a_function_named_like_an_input_does_not_hide_it(self):
        from utk_curio.backend.app.packages.domain.function_nodes import read_function, template_code

        fn = read_function("def input_0(x):\n    return x\n", "m", "input_0")
        assert template_code("m", fn, {"x": {"use": "input", "slot": 0}}) == (
            "from m import input_0 as input_0_function\n\nreturn input_0_function(x=[!! input_0 !!])\n"
        )
        # `arg`, a name the input once had, is an ordinary name now.
        fn = read_function("def arg(x):\n    return x\n", "m", "arg")
        assert template_code("m", fn, {"x": {"use": "input", "slot": 0}}) == (
            "from m import arg\n\nreturn arg(x=[!! input_0 !!])\n"
        )

    def test_the_code_is_a_node_body_once_its_references_resolve(self):
        import ast
        import textwrap

        from utk_curio.backend.app.execution.workflow_spec import resolve_code_references
        from utk_curio.backend.app.packages.domain.function_nodes import read_function, template_code

        fn = read_function(OPS, "fn_scale.ops", "scale")
        code = template_code("fn_scale.ops", fn, {
            "value": {"use": "input", "slot": 0}, "factor": {"use": "widget"},
            "label": {"use": "fixed", "value": "'scaled'"},
        })
        resolved = resolve_code_references(
            code, [{"name": "factor", "type": "number", "default": 2, "value": 3}], "python", input_slots=[0],
        )
        assert "factor=3" in resolved and "value=input" in resolved
        ast.parse("def node(input):\n" + textwrap.indent(resolved, "    "))


# ---------------------------------------------------------------------------
# What the routes answer, read from the store
# ---------------------------------------------------------------------------

class TestTheListingAndTheWrittenTemplate:
    def test_every_store_package_that_ships_modules_with_its_functions(self, tmp_curio):
        from utk_curio.backend.app.packages.application.function_nodes import package_functions

        install_package_from_archive("guest", _archive())
        install_package_from_archive("guest", _archive("ai.test.plain", modules={}))
        listed = [p for p in package_functions("guest") if p["packageId"].startswith("ai.test.")]
        assert [p["dirName"] for p in listed] == [f"{SOURCE_ID}@1"]
        (package,) = listed
        assert package["readOnly"] is False
        modules = {m["module"]: m for m in package["modules"]}
        assert sorted(modules) == ["fn_broken", "fn_scale", "fn_scale.ops"]
        assert modules["fn_broken"]["functions"] == []
        assert modules["fn_broken"]["problem"].startswith("fn_broken does not parse: line 1")
        assert [f["name"] for f in modules["fn_scale"]["functions"]] == ["version"]
        (scale,) = modules["fn_scale.ops"]["functions"]
        assert scale["doc"] == "Scale a value."
        assert [(p["name"], p["use"]) for p in scale["parameters"]] == [
            ("value", "widget"), ("factor", "widget"), ("label", "widget"),
        ]
        assert scale["parameters"][1]["widget"] == {
            "name": "factor", "type": "number", "label": "Factor", "default": 2, "options": {"step": 1},
        }

    def test_the_template_it_writes(self, tmp_curio):
        from utk_curio.backend.app.packages.application.function_nodes import write_function_template

        install_package_from_archive("guest", _archive())
        written = write_function_template("guest", f"{SOURCE_ID}@1", "fn_scale.ops", "scale", "Scale it", {
            "value": {"use": "input"},
            "factor": {"use": "widget", "widget": {"name": "factor", "type": "slider", "label": "Factor",
                                                   "default": 2, "options": {"min": 1, "max": 5}, "value": 4}},
            "label": {"use": "fixed", "value": "'scaled'"},
        })
        template = written["template"]
        assert template["id"] == "scale-it" and template["label"] == "Scale it"
        assert template["source"] == "sources/scale-it.py"
        assert (template["engine"], template["editor"], template["behavior"]) == ("python", "code", "code")
        assert template["description"] == "Scale a value. Calls scale from fn_scale.ops."
        assert template["inputPorts"] == [{
            "types": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON", "RASTER"], "cardinality": "1",
        }]
        # The widget the dialog sent, in the template's shape: no value.
        assert template["widgets"] == [{"name": "factor", "type": "slider", "label": "Factor", "default": 2,
                                        "options": {"min": 1, "max": 5}}]
        assert written["source"] == {"filename": "scale-it.py", "code": (
            "from fn_scale.ops import scale\n\nreturn scale(\n    value=[!! input_0 !!],\n"
            "    factor=[!! factor !!],\n    label='scaled',\n)\n"
        )}
        assert written["package"] == {"dirName": f"{SOURCE_ID}@1", "packageId": SOURCE_ID, "major": 1,
                                      "readOnly": False}
        assert written["dependency"] == {f"{SOURCE_ID}@1": "*"}

    def test_no_input_no_input_port_and_a_label_from_the_function(self, tmp_curio):
        from utk_curio.backend.app.packages.application.function_nodes import write_function_template

        install_package_from_archive("guest", _archive())
        written = write_function_template("guest", f"{SOURCE_ID}@1", "fn_scale", "version", None, {})
        assert written["template"]["inputPorts"] == [] and "widgets" not in written["template"]
        assert (written["template"]["id"], written["template"]["label"]) == ("version", "Version")
        assert written["source"]["code"] == "from fn_scale import version\n\nreturn version()\n"

    @pytest.mark.parametrize("bindings, words", [
        ({"value": {"use": "widget", "widget": {"name": "factor", "type": "number", "default": 1}},
          "factor": {"use": "default"}, "label": {"use": "default"}}, "must be named value"),
        ({"value": {"use": "widget", "widget": {"name": "value", "type": "slider", "default": 1}},
          "factor": {"use": "default"}, "label": {"use": "default"}}, "A slider needs a minimum and a maximum"),
        ({"value": {"use": "input"}, "factor": {"use": "default"}}, "Choose what label is given"),
        ({"value": {"use": "input"}, "factor": {"use": "default"}, "label": {"use": "nothing"}},
         "Choose what label is given"),
        ({"value": {"use": "input"}, "factor": {"use": "default"}, "label": {"use": "default"},
          "extra": {"use": "input"}}, "scale has no parameter named extra"),
        ({"value": {"use": "input"}, "factor": {"use": "fixed", "value": "two"}, "label": {"use": "default"}},
         "is not a Python literal"),
    ])
    def test_a_binding_it_cannot_call_the_function_with_is_refused(self, tmp_curio, bindings, words):
        from utk_curio.backend.app.packages.application.function_nodes import write_function_template
        from utk_curio.backend.app.packages.domain.errors import PackageServiceError

        install_package_from_archive("guest", _archive())
        with pytest.raises(PackageServiceError, match=words) as raised:
            write_function_template("guest", f"{SOURCE_ID}@1", "fn_scale.ops", "scale", None, bindings)
        assert raised.value.status == 400

    @pytest.mark.parametrize("dir_name, module, function, words, status", [
        (f"{SOURCE_ID}@1", "fn_scale.missing", "scale", "ships no module named 'fn_scale.missing'", 404),
        (f"{SOURCE_ID}@1", "caller", "scale", "ships no module named 'caller'", 404),
        ("ai.test.absent@1", "fn_scale.ops", "scale", "is not installed", 404),
        (f"{SOURCE_ID}@1", "fn_broken", "broken", "fn_broken does not parse", 400),
        (f"{SOURCE_ID}@1", "fn_scale.ops", "_hidden", "defines no public function", 400),
    ])
    def test_it_reads_the_store_not_the_request(self, tmp_curio, dir_name, module, function, words, status):
        from utk_curio.backend.app.packages.application.function_nodes import write_function_template
        from utk_curio.backend.app.packages.domain.errors import PackageServiceError

        install_package_from_archive("guest", _archive())
        with pytest.raises(PackageServiceError, match=words) as raised:
            write_function_template("guest", dir_name, module, function, None, {})
        assert raised.value.status == status

    def test_the_routes(self, client, user_and_token):
        from utk_curio.backend.app.projects.services import _user_dir_key

        user, token = user_and_token
        install_package_from_archive(_user_dir_key(user), _archive())
        headers = {"Authorization": f"Bearer {token}"}

        listed = client.get("/api/packages/factory/functions", headers=headers)
        assert listed.status_code == 200, listed.get_data(as_text=True)
        assert f"{SOURCE_ID}@1" in [p["dirName"] for p in listed.get_json()["packages"]]

        body = {"dirName": f"{SOURCE_ID}@1", "module": "fn_scale.ops", "function": "scale",
                "bindings": {"value": {"use": "input"}, "factor": {"use": "default"}, "label": {"use": "default"}}}
        written = client.post("/api/packages/factory/function-template", headers=headers, json=body)
        assert written.status_code == 200, written.get_data(as_text=True)
        assert written.get_json()["source"]["code"] == (
            "from fn_scale.ops import scale\n\nreturn scale(value=[!! input_0 !!])\n"
        )
        for bad, words in (
            ({**body, "module": "../etc"}, "dotted module name"),
            ({**body, "dirName": "nope"}, "valid 'dirName'"),
            ({**body, "bindings": []}, "'bindings'"),
        ):
            refused = client.post("/api/packages/factory/function-template", headers=headers, json=bad)
            assert refused.status_code == 400 and words in refused.get_json()["error"], refused.get_json()
        assert client.get("/api/packages/factory/functions").status_code == 401


# ---------------------------------------------------------------------------
# The written template runs
# ---------------------------------------------------------------------------

def _draft_into_a_new_package(written: dict) -> dict:
    """What the dialog sends ``/factory/install`` for a new package (the
    frontend's ``buildFunctionInstallDraft``): the template, its source, and
    the function's package as a dependency."""
    template = written["template"]
    return {
        "manifest": {
            "id": NODE_PACKAGE, "version": "0.1.0", "name": "Function nodes", "publisher": "Local palette",
            "description": "Nodes made from Python functions.", "license": "MIT",
            "compatibility": {"curioRuntime": ">=0.5.0", "major": 1}, "permissions": [],
            "dependencies": {"packages": dict(written["dependency"]), "python": {}, "js": {}},
            "templates": [template],
        },
        "sources": {template["id"]: written["source"]},
    }


def test_the_template_runs_in_the_sandbox_and_a_new_widget_value_gives_a_new_result(tmp_curio, monkeypatch):
    from utk_curio.backend.app.execution import runner
    from utk_curio.backend.app.packages.application.factory_install import install_draft
    from utk_curio.backend.app.packages.application.function_nodes import write_function_template
    from utk_curio.backend.app.packages.repositories.store import package_dir
    from utk_curio.backend.app.packages.service import modules_for_node
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db, release_connection
    from utk_curio.sandbox.util.package_modules import shape
    from utk_curio.sandbox.util.parsers import load_from_duckdb

    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_curio / ".curio" / "data"))
    release_connection()
    init_db()
    try:
        install_package_from_archive("guest", _archive())
        written = write_function_template("guest", f"{SOURCE_ID}@1", "fn_scale.ops", "scale", "Scale it", {
            "value": {"use": "input"},
            "factor": {"use": "widget", "widget": {"name": "factor", "type": "number", "label": "Factor", "default": 2}},
            "label": {"use": "fixed", "value": "'scaled'"},
        })
        built, _ = install_draft("guest", _draft_into_a_new_package(written), replace=False)
        # The function's module is the package's dependency, not a library to pip-install.
        assert built.manifest.python_deps == {}
        assert built.manifest.package_deps == {f"{SOURCE_ID}@1": "*"}
        node_type = f"{NODE_PACKAGE}/scale-it"
        assert modules_for_node("guest", node_type) == {
            "root": str(package_dir("guest", f"{SOURCE_ID}@1") / "sources"),
            "names": ["fn_broken", "fn_scale"],
        }

        _worker_init()

        def exec_fn(endpoint, payload):
            assert endpoint == "/exec"
            return execute_code(
                payload["code"], payload["file_path"], payload["nodeType"], payload["dataType"],
                save_dataset=False, package_modules=shape(payload.get("package_modules")),
            )

        def run(factor):
            spec = {"dataflow": {"nodes": [
                {"id": "a", "type": "curio.builtin/computation-analysis", "content": "return 21"},
                {"id": "b", "type": node_type, "content": written["source"]["code"],
                 "metadata": {"widgets": [{**written["template"]["widgets"][0], "value": factor}]}},
            ], "edges": [{"id": "e1", "source": "a", "target": "b"}]}}
            roster = {
                "curio.builtin/computation-analysis": {"executable": True, "engine": "python"},
                node_type: {"executable": True, "engine": "python"},
            }
            report = runner.run_through_node("guest", "p-function-node", spec, "b", exec_fn=exec_fn, templates=roster)
            assert report["ok"] is True, report
            return load_from_duckdb(report["nodes"]["b"]["output"]["path"])

        assert run(2) == "scaled:42"
        assert run(3) == "scaled:63"
    finally:
        release_connection()
