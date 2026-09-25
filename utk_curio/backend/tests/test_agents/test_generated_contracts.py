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


def test_every_output_names_its_generator_and_source():
    for render in contracts.GENERATED_OUTPUTS.values():
        head = render()[:400]
        assert contracts.GENERATOR in head
        assert contracts.SOURCE_MODULE in head
        assert "Do not edit by hand" in head


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
