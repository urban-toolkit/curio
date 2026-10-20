"""The files that hold these rules name no artifact Curio ships.

Built-in nodes are known by what their templates declare (the template
manifests' reader, the dashboard payload, a run's plan, a scenario's parts and
a dataset's consumers), a dataset of the shared catalog by its origin (a layer
group's card and the Data Catalog's ``isSharedCatalogDataset``), a use case by
the index beside the shipped dataflows, and a dataflow's declared packages are
all installed with it. So none of these files names a shipped package (aside
from ``curio.builtin``, the base every store holds), a shipped dataset or a
shipped dataflow, or the ``data.`` namespace the shipped datasets' ids share,
and no list holds a package back from the dataflows that declare it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
APP = "utk_curio/backend/app"
FRONTEND_SRC = "utk_curio/frontend/urban-workflows/src"

SCANNED = [
    f"{APP}/projects/template_grammars.py",
    f"{APP}/projects/dashboard_payload.py",
    f"{APP}/execution/run_plan.py",
    f"{APP}/scenario_catalog/domain/parts.py",
    f"{APP}/datasets/application/export.py",
    f"{APP}/datasets/domain/layer_group.py",
    f"{FRONTEND_SRC}/services/datasetCatalog/datasetCatalogTypes.ts",
    f"{APP}/projects/shipped.py",
    f"{APP}/packages/application/workflow_deps.py",
]

#: The package every store is seeded with, which core code may name.
BASE_PACKAGE = "curio.builtin"


def _ids(folder: str) -> set[str]:
    return {
        json.loads(manifest.read_text(encoding="utf-8"))["id"]
        for manifest in (REPO / folder).glob("*/manifest.json")
    }


def _named(text: str) -> list[str]:
    """The shipped packages, datasets and dataflows *text* names."""
    examples = REPO / "docs" / "examples"
    ids = (_ids("packages") - {BASE_PACKAGE}) | _ids("datasets")
    ids |= {path.stem for path in examples.glob("[0-9][0-9]-*.json")}
    named = sorted(
        artifact for artifact in ids
        if re.search(rf"(?<![\w.-]){re.escape(artifact)}(?![\w-])", text)
    )
    for path in sorted((examples / "dataflows").glob("*.json")):
        named += [spelled for spelled in (f"dataflows/{path.stem}", path.name) if spelled in text]
    return named


def test_the_scan_sees_what_it_looks_for():
    assert len(_ids("packages")) > 1 and BASE_PACKAGE in _ids("packages")
    assert _ids("datasets")
    assert _named('id = "09-heterogeneous-data-linked-views"') == ["09-heterogeneous-data-linked-views"]
    assert _named("see dataflows/regression") == ["dataflows/regression"]
    assert _named("(``curio.scout@1``)") == ["curio.scout"]
    assert _named("curio.builtin/vis-vega") == []


@pytest.mark.parametrize("relative", SCANNED)
def test_the_file_names_no_shipped_artifact(relative):
    text = (REPO / relative).read_text(encoding="utf-8")
    assert not _named(text), f"{relative} names {_named(text)}"
    assert not re.search(r"[\"'`]data\.", text), f"{relative} names the data. namespace"


def test_no_list_holds_a_package_back_from_the_dataflows_that_declare_it():
    found = [
        path.relative_to(REPO).as_posix()
        for root in (APP, FRONTEND_SRC)
        for path in sorted((REPO / root).rglob("*"))
        if path.suffix in {".py", ".ts", ".tsx"} and path.is_file() and "/tests/" not in path.as_posix()
        and "INSTALL_ON_DEMAND" in path.read_text(encoding="utf-8")
    ]
    assert not found, found
