"""dev/134: what kind of content a node kind carries — derived, never listed.

The owner's `e72c7080` wrote the sentence "not controllable" into a merge-flow,
a data-pool and an autk-grammar node, and an invalid Vega document into a
vis-vega node, because the write gate only knew one question ("can the sandbox
run this?"). The gate needs three answers, and the manifest already declares
which is which — so the routing is a derivation over the roster (`DEC-076`),
tested here against the real builtin manifest.
"""

from __future__ import annotations

from utk_curio.backend.app.execution import workflow_spec as ws
from utk_curio.backend.app.packages import services as pkg_services

BUILTIN = "curio.builtin"


def _templates() -> dict:
    """The builtin package's own templates, read from the shipped manifest."""
    from pathlib import Path

    from utk_curio.backend.app.packages.manifest import load_packageage_manifest

    root = Path(__file__).resolve().parents[4] / "packages" / "curio.builtin@1"
    manifest = load_packageage_manifest(root)
    return {t.template_id: t for t in manifest.templates}


class TestTemplateContentKind:
    def test_every_builtin_template_lands_in_the_right_kind(self):
        kinds = {
            tid: pkg_services.template_content_kind(t) for tid, t in _templates().items()
        }
        assert kinds["data-loading"] == "code"
        assert kinds["computation-analysis"] == "code"
        assert kinds["js-computation"] == "code"
        assert kinds["data-export"] == "code"
        assert kinds["data-summary"] == "code"
        assert kinds["data-transformation"] == "code"
        # A document: authored, validated, never executed.
        assert kinds["vis-vega"] == "grammar"
        assert kinds["autk-grammar"] == "grammar"
        # Wired, not written — the three nodes the field log found holding prose
        # plus the two that would have been next.
        assert kinds["merge-flow"] == "none"      # containerStyle.noContent
        assert kinds["data-pool"] == "none"       # editor none + an input port
        assert kinds["vis-simple"] == "none"
        assert kinds["spatial-join"] == "none"

    def test_a_presentation_template_with_no_input_is_a_note(self):
        """dev/90 A14's post-it profile: authored content, no validator. The
        discriminator is the INPUT — a node that renders its input is not
        authoring anything."""
        template = next(iter(_templates().values()))

        class _Fake:
            has_code = False
            has_grammar = False
            editor = "none"
            container_style = None
            input_ports: list = []
            grammar_id = None

        assert pkg_services.template_content_kind(_Fake()) == "note"
        _Fake.input_ports = [object()]
        assert pkg_services.template_content_kind(_Fake()) == "none"
        # And the real templates are unaffected by the fake.
        assert pkg_services.template_content_kind(template) in ("code", "grammar", "none", "note")

    def test_no_content_wins_over_an_editor(self):
        class _Fake:
            has_code = False
            has_grammar = False
            editor = "grammar"
            container_style = {"noContent": True}
            input_ports = [object()]
            grammar_id = "vega-lite"

        # hasGrammar is what makes a document, not the editor: an explicit
        # noContent template authors nothing whatever its editor says.
        assert pkg_services.template_content_kind(_Fake()) == "none"


class TestContentKindOverTheRoster:
    ROSTER = {
        "curio.builtin/data-loading": {"executable": True, "contentKind": "code"},
        "curio.builtin/vis-vega": {"executable": False, "contentKind": "grammar",
                                   "grammar": "vega-lite"},
        "curio.builtin/autk-grammar": {"executable": False, "contentKind": "grammar",
                                       "grammar": "autk-grammar"},
        "curio.builtin/data-pool": {"executable": False, "contentKind": "none"},
        "pkg.custom/plotly-view": {"executable": False, "contentKind": "grammar",
                                   "grammar": "plotly"},
    }

    def test_the_roster_answers_and_a_version_suffix_is_tolerated(self):
        assert ws.content_kind("curio.builtin/data-loading", self.ROSTER) == "code"
        assert ws.content_kind("curio.builtin/vis-vega@1", self.ROSTER) == "grammar"
        assert ws.content_kind("curio.builtin/data-pool@2", self.ROSTER) == "none"
        assert ws.grammar_id_of("curio.builtin/autk-grammar", self.ROSTER) == "autk-grammar"
        # A package's OWN visualization kind needs no backend edit.
        assert ws.content_kind("pkg.custom/plotly-view", self.ROSTER) == "grammar"
        assert ws.grammar_id_of("pkg.custom/plotly-view", self.ROSTER) == "plotly"

    def test_without_a_roster_the_legacy_tables_answer(self):
        assert ws.content_kind("curio.builtin/data-loading") == "code"
        assert ws.content_kind("curio.builtin/vis-vega") == "grammar"
        assert ws.content_kind("curio.builtin/merge-flow") == "none"
        assert ws.content_kind("curio.builtin/data-pool") == "none"
        assert ws.grammar_id_of("curio.builtin/vis-vega") == "vega-lite"
        assert ws.grammar_id_of("curio.builtin/data-loading") is None

    def test_an_unknown_type_authors_nothing_and_nothing_raises(self):
        assert ws.content_kind("nope/unknown", self.ROSTER) == "none"
        assert ws.content_kind("", self.ROSTER) == "none"
        assert ws.content_kind(None) == "none"  # type: ignore[arg-type]
        assert ws.grammar_id_of(None) is None  # type: ignore[arg-type]

    def test_the_roster_snapshot_carries_the_kind(self, tmp_curio, monkeypatch):
        rows = [
            {"id": "curio.builtin/vis-vega", "executable": False, "engine": "python",
             "contentKind": "grammar", "grammar": "vega-lite"},
        ]
        monkeypatch.setattr(pkg_services, "available_templates", lambda *a, **k: rows)
        snapshot = pkg_services.roster_templates("1", "p-134")
        assert snapshot["curio.builtin/vis-vega"]["contentKind"] == "grammar"
        assert snapshot["curio.builtin/vis-vega"]["grammar"] == "vega-lite"
