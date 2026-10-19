"""Which shipped dataflows are use cases: the index beside them says.

``docs/examples/use-cases.json`` names, by key, the numbered dataflows the
Projects page files under Use cases. Every other numbered dataflow is an
example, and every dataflow in ``dataflows/`` a test. A dataflow's source comes
from its key through the index (``projects/shipped.py``) and is never stored
in its file, so a copy of a use case under another name is not one. The
modules under test are imported inside each test, so a checkout without a name
fails each test on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
EXAMPLES = REPO / "docs" / "examples"
USE_CASE = "09-heterogeneous-data-linked-views"


def _spec(key: str) -> dict:
    return json.loads((EXAMPLES / f"{key}.json").read_text(encoding="utf-8"))


def test_the_index_beside_the_shipped_dataflows_names_the_use_cases():
    raw = json.loads((EXAMPLES / "use-cases.json").read_text(encoding="utf-8"))
    assert raw["useCases"] == [USE_CASE]
    for key in raw["useCases"]:
        assert (EXAMPLES / f"{key}.json").is_file(), f"{key} is not a numbered dataflow that ships"


def test_the_index_is_no_dataflow_and_gives_each_shipped_one_its_source():
    from utk_curio.backend.app.projects.shipped import (
        SOURCE_EXAMPLE,
        SOURCE_TEST,
        SOURCE_USE_CASE,
        shipped_dataflows,
    )

    shipped = {entry.key: entry for entry in shipped_dataflows()}
    assert "use-cases" not in shipped
    assert all(entry.path.name != "use-cases.json" for entry in shipped.values())
    by_source: dict[str, list[str]] = {}
    for entry in shipped.values():
        by_source.setdefault(entry.source, []).append(entry.key)
    assert by_source[SOURCE_USE_CASE] == [USE_CASE]
    assert all(not key.startswith("dataflows/") for key in by_source[SOURCE_EXAMPLE])
    assert all(key.startswith("dataflows/") for key in by_source[SOURCE_TEST])


def test_a_dataflows_source_comes_from_its_key_through_the_index(tmp_path):
    from utk_curio.backend.app.projects.shipped import (
        SOURCE_EXAMPLE,
        SOURCE_TEST,
        SOURCE_USE_CASE,
        shipped_dataflows,
    )

    text = json.dumps(_spec(USE_CASE))
    (tmp_path / "01-first.json").write_text(text, encoding="utf-8")
    (tmp_path / "02-copy-of-first.json").write_text(text, encoding="utf-8")
    (tmp_path / "dataflows").mkdir()
    (tmp_path / "dataflows" / "probe.json").write_text(text, encoding="utf-8")
    (tmp_path / "use-cases.json").write_text(json.dumps({"useCases": ["01-first"]}), encoding="utf-8")

    def sources() -> dict[str, str]:
        return {entry.key: entry.source for entry in shipped_dataflows(tmp_path)}

    assert sources() == {
        "01-first": SOURCE_USE_CASE,
        "02-copy-of-first": SOURCE_EXAMPLE,
        "dataflows/probe": SOURCE_TEST,
    }

    (tmp_path / "use-cases.json").unlink()
    assert sources() == {
        "01-first": SOURCE_EXAMPLE,
        "02-copy-of-first": SOURCE_EXAMPLE,
        "dataflows/probe": SOURCE_TEST,
    }


def test_the_use_case_keeps_its_source_out_of_its_file():
    spec = _spec(USE_CASE)
    assert "source" not in spec["dataflow"].get("categories", {})
    assert "use_case" not in json.dumps(spec)
