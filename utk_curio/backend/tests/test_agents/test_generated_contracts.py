"""Every generated contract output matches a fresh render of its source.

``contracts.py`` is the one definition of each contract; the files listed in
``contracts.GENERATED_OUTPUTS`` are copies written by
``scripts/generate_contracts.py``. A hand edit to a copy, or a change to the
source that was never regenerated, is exactly the drift the module exists to
prevent, so it fails here.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from utk_curio.backend.app.agents import contracts

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize("relative", sorted(contracts.GENERATED_OUTPUTS))
def test_the_committed_output_matches_its_source(relative):
    path = REPO_ROOT / relative
    expected = contracts.GENERATED_OUTPUTS[relative]()
    assert path.is_file(), (
        f"{relative} is missing: run python {contracts.GENERATOR}"
    )
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        diff = "".join(difflib.unified_diff(
            expected.splitlines(keepends=True), actual.splitlines(keepends=True),
            fromfile="rendered", tofile=relative,
        ))
        pytest.fail(
            f"{relative} is out of date with {contracts.SOURCE_MODULE}: run "
            f"python {contracts.GENERATOR}\n{diff}"
        )


def test_the_check_and_the_registry_agree():
    assert contracts.stale_outputs(REPO_ROOT) == []


def test_every_code_output_names_its_generator_and_source():
    for relative, render in contracts.GENERATED_OUTPUTS.items():
        if relative.startswith(contracts.PROMPTS_DIR):
            continue  # sent to the model verbatim, so it carries no header
        head = render()[:400]
        assert contracts.GENERATOR in head
        assert contracts.SOURCE_MODULE in head
        assert "Do not edit by hand" in head


def test_every_generated_prompt_has_its_template_beside_it():
    prompts = [r for r in contracts.GENERATED_OUTPUTS if r.startswith(contracts.PROMPTS_DIR)]
    assert prompts
    for relative in prompts:
        assert (REPO_ROOT / relative.replace(".txt", ".template.txt")).is_file()


class TestTheRenderCauseTable:
    def test_the_cause_names_and_their_order(self):
        assert contracts.EMPTY_RENDER_CAUSES == (
            "no-layers", "no-input-rows", "nothing-drawn", "empty-source",
        )

    def test_only_no_input_rows_spares_the_document(self):
        at_fault = {c.name: c.document_at_fault for c in contracts.RENDER_CAUSES}
        assert at_fault == {
            "no-layers": True, "no-input-rows": False,
            "nothing-drawn": True, "empty-source": True,
        }

    def test_an_unknown_cause_is_still_the_documents_fault(self):
        assert contracts.is_document_at_fault("teleported") is True
        assert contracts.is_document_at_fault("") is True
        assert contracts.is_document_at_fault(None) is True

    def test_every_cause_is_described_in_one_line(self):
        for cause in contracts.RENDER_CAUSES:
            assert cause.description and "\n" not in cause.description


class TestTheAutarkRenderers:
    """The schema is rendered twice: a one-line shape for refusals and a
    preamble region. Both read the vendored file, never a hand-kept copy."""

    def test_the_shape_names_every_family_and_fits_a_refusal_whole(self):
        from utk_curio.backend.app.agents import document_validation as dv

        schema = contracts.load_autk_schema()
        shape = contracts.render_autk_shape(schema)
        assert "\n" not in shape
        for family in contracts.autk_families(schema):
            assert f'"{family}"' in shape
        assert f'"dataRef": "{contracts.AUTK_UPSTREAM_LAYER}"' in shape
        # The whole shape survives the refusal's 600-character cut.
        assert shape in dv.validate(contracts.AUTK_TEMPLATE, "not controllable")["detail"]

    def test_the_region_names_what_the_schema_requires(self):
        schema = contracts.load_autk_schema()
        region = contracts.render_autk_region(schema, "AUTK_GRAMMAR")
        assert schema["$id"] in region
        assert contracts.AUTK_TEMPLATE in region
        assert f'"{contracts.AUTK_UPSTREAM_LAYER}"' in region
        for union, key in (("DataSourceSpec", "type"), ("PlotSpec", "mark")):
            for values, _ in contracts._variants(schema, union, key):
                for value in values:
                    assert f'"{value}"' in region, (union, value)

    def test_the_preamble_rows_come_from_the_manifest(self):
        import json

        manifest = json.loads((REPO_ROOT / contracts.BUILTIN_MANIFEST).read_text(encoding="utf-8"))
        template = contracts._builtin_template(manifest, contracts.AUTK_TEMPLATE)
        fields = contracts.preamble_fields(manifest, contracts.load_autk_schema())
        assert fields["autk.node"] == f"- AUTK_GRAMMAR: {template['description']}"
        assert fields["autk.control"] == "- AUTK_GRAMMAR: controllable through grammar."

    def test_the_preamble_fills_every_field_and_names_no_retired_node(self):
        text = contracts.render_default_preamble()
        assert "{{" not in text
        assert "AUTK_MAP" not in text
        assert "initialView" not in text
