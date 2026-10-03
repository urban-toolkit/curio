"""Every built-in prompt names only things that exist.

The prompts in ``utk_curio/llm-prompts/`` name tools, capabilities, node
templates, package folders, sandbox helpers and Data Catalog datasets, and they
carry Vega-Lite examples. Each of those is defined somewhere else: the tool
registry, the built-in agents, the shipped manifests, the sandbox, the shipped
catalogs and the Vega-Lite schema. A rename or a removal there leaves the prompt
pointing at nothing, and the model copies what the prompt shows. These tests
read every prompt a built-in agent receives and check each name against the
code or the catalog that defines it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utk_curio.backend.app.agents.application.tools import REGISTRY
from utk_curio.backend.app.agents.domain import builtin
from utk_curio.backend.app.agents.domain.document_validation import (
    STATUS_VALID,
    validate_vega_lite,
)
from utk_curio.backend.app.agents.domain.manifest import CAPABILITY_ID_RE
from utk_curio.backend.app.datasets.domain.code_refs import (
    DATASET_PATH_CALL_RE,
    MODEL_CALL_RE,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Every prompt file a built-in agent receives, the shared preamble included.
PROMPT_FILES = sorted({f for spec in builtin.BUILTIN_AGENTS for f in spec.prompt_files().values()})

#: Words a prompt uses that look like an id but are not one, each with the
#: reason. An entry no prompt uses any more fails ``test_every_exception_is_still_used``.
NOT_IDS = {
    "dataset.height": "a rasterio dataset's attribute, in the code of the preamble's example",
    "dataset.width": "a rasterio dataset's attribute, in the code of the preamble's example",
    "dataset.transform": "a rasterio dataset's attribute, in the code of the preamble's example",
    "curio.notes@1": "the notes package the Researcher writes into a user's store, "
                     "shown as the shape of a versioned dirName",
}

# A tool or capability id, by the manifest's own grammar, standing alone: not
# part of a longer dotted name, a path, a URL or a call.
_ID_RE = re.compile(
    r"(?<![\w@/.\\-])(" + CAPABILITY_ID_RE.pattern.strip("^$") + r")(?![\w@/(-]|\.[a-z])"
)
# A node type, ``<package id>/<template id>``; a URL's host never matches
# because it follows a slash.
_TEMPLATE_RE = re.compile(r"(?<![\w@/.:\\-])([a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+/[a-z0-9][a-z0-9-]*)")
# A versioned folder name, ``<id>@<major>``: a package or a dataset.
_DIR_NAME_RE = re.compile(r"(?<![\w@/.\\-])([a-z][a-z0-9-]*(?:\.[a-z0-9-]+)+@\d+)(?![\w.-])")
_HELPER_RE = re.compile(r"\bcurio_[a-z][a-z0-9_]*\b")
_SECRET_INJECTION_RE = re.compile(
    r"""\[\s*["']curio_secret["']\s*\]\s*=\s*make_curio_secret\("""
)


def _text(name: str) -> str:
    return (builtin.PROMPT_SOURCE_DIR / name).read_text(encoding="utf-8")


def _manifests(folder: str) -> list[tuple[str, dict]]:
    return [
        (path.parent.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((REPO_ROOT / folder).glob("*/manifest.json"))
    ]


def _known_ids() -> set[str]:
    capabilities = {c for spec in builtin.BUILTIN_AGENTS for c in spec.capabilities}
    return set(REGISTRY) | capabilities


def _shipped_templates() -> set[str]:
    return {
        f"{manifest['id']}/{template['id']}"
        for _dir, manifest in _manifests("packages")
        for template in manifest.get("templates", [])
    }


def _injected_helpers() -> set[str]:
    """The ``curio_*`` names node code can call: the catalog helpers the sandbox
    installs (the renamed ones only raise), plus ``curio_secret``, which both
    execution paths inject beside them."""
    from utk_curio.sandbox.util.catalog_helpers import install_catalog_helpers

    namespace: dict = {}
    install_catalog_helpers(
        namespace, data_path=str, formats=None, collections=None, media_dir=None, models=None,
    )
    names = {
        name for name, value in namespace.items()
        if name.startswith("curio_") and "_renamed" not in getattr(value, "__qualname__", "")
    }
    for path in ("utk_curio/sandbox/app/worker.py", "utk_curio/sandbox/isolation/child.py"):
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert _SECRET_INJECTION_RE.search(source), f"{path} no longer injects curio_secret"
    return names | {"curio_secret"}


def _ids(name: str) -> list[str]:
    namespaces = {i.split(".")[0] for i in _known_ids()}
    return [
        token for token in _ID_RE.findall(_text(name))
        if token.split(".")[0] in namespaces
    ]


def _json_values(text: str):
    """Every JSON object the text spells out, outermost first."""
    decoder = json.JSONDecoder()
    position = text.find("{")
    while position != -1:
        try:
            value, end = decoder.raw_decode(text, position)
        except ValueError:
            position = text.find("{", position + 1)
            continue
        yield value
        position = text.find("{", end)


def _vega_specs(value):
    """The Vega-Lite documents in a JSON value, including those a node's
    ``content`` holds as a string."""
    if isinstance(value, dict):
        if "vega-lite" in str(value.get("$schema", "")):
            yield value
        for child in value.values():
            yield from _vega_specs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _vega_specs(child)
    elif isinstance(value, str) and value.lstrip().startswith("{"):
        try:
            yield from _vega_specs(json.loads(value))
        except ValueError:
            pass


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_no_template_marker_is_left(name):
    assert "{{" not in _text(name), f"{name} still holds a {{{{field}}}} marker"


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_every_tool_and_capability_it_names_is_declared(name):
    known = _known_ids()
    unknown = sorted({i for i in _ids(name) if i not in known and i not in NOT_IDS})
    assert not unknown, (
        f"{name} names {unknown}, which is neither a tool in tools.REGISTRY nor "
        f"a capability a built-in agent declares"
    )


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_every_node_type_it_names_ships(name):
    shipped = _shipped_templates()
    unknown = sorted(set(_TEMPLATE_RE.findall(_text(name))) - shipped)
    assert not unknown, f"{name} names node types no shipped package defines: {unknown}"


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_every_package_or_dataset_folder_it_names_ships(name):
    shipped = {d for d, _m in _manifests("packages")} | {d for d, _m in _manifests("datasets")}
    unknown = sorted(set(_DIR_NAME_RE.findall(_text(name))) - shipped - set(NOT_IDS))
    assert not unknown, f"{name} names folders that ship in neither packages/ nor datasets/: {unknown}"


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_every_helper_it_names_is_injected(name):
    unknown = sorted(set(_HELPER_RE.findall(_text(name))) - _injected_helpers())
    assert not unknown, f"{name} names helpers the sandbox does not inject: {unknown}"


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_every_dataset_and_model_it_loads_ships(name):
    text = _text(name)
    datasets = {m["id"] for _d, m in _manifests("datasets")}
    models = {m["id"] for _d, m in _manifests("models")}
    missing = sorted(
        [i for _q, i in DATASET_PATH_CALL_RE.findall(text) if i not in datasets]
        + [i for _q, i in MODEL_CALL_RE.findall(text) if i not in models]
    )
    assert not missing, (
        f"{name} loads ids the shipped Data and Model Catalogs do not hold: {missing}"
    )


@pytest.mark.parametrize("name", PROMPT_FILES)
def test_every_vega_lite_example_validates(name):
    for value in _json_values(_text(name)):
        for spec in _vega_specs(value):
            result = validate_vega_lite(json.dumps(spec))
            assert result["status"] == STATUS_VALID, (
                f"{name} shows a Vega-Lite document Curio refuses: "
                f"{result.get('detail') or result.get('why')}\n{json.dumps(spec)[:400]}"
            )


def test_the_checks_find_what_the_prompts_name():
    """Each check above passes trivially if its scan finds nothing, so the scans
    must find what the prompts are known to name."""
    every_id = {i for name in PROMPT_FILES for i in _ids(name)}
    assert {"catalog.search", "node.content.generate", "dataflow.plan.write"} <= every_id
    corpus = "\n".join(_text(name) for name in PROMPT_FILES)
    assert "curio.builtin/merge-flow" in _TEMPLATE_RE.findall(corpus)
    assert "curio_load_data" in _HELPER_RE.findall(corpus)
    assert DATASET_PATH_CALL_RE.findall(corpus)
    preamble_specs = [s for v in _json_values(_text(builtin.PREAMBLE_FILE)) for s in _vega_specs(v)]
    assert len(preamble_specs) >= 3


def test_every_exception_is_still_used():
    corpus = "\n".join(_text(name) for name in PROMPT_FILES)
    stale = sorted(word for word in NOT_IDS if word not in corpus)
    assert not stale, f"NOT_IDS lists words no prompt uses any more: {stale}"
