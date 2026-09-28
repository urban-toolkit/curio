"""A grammar document's ``$schema`` is a format declaration, not a source.

The Vega-Lite spec every chart node holds opens with
``"$schema": "https://vega.github.io/schema/vega-lite/v6.json"``. Scanned as a
data source it made the gate probe vega.github.io on every document the agent
wrote — and, because an unverifiable URL refuses the whole candidate, an
install with no route to that host could not write a Vega document at all.
"""

from __future__ import annotations

import json

from utk_curio.backend.app.agents import source_grounding as sg

VEGA_SCHEMA = "https://vega.github.io/schema/vega-lite/v6.json"


class TestSchemaDeclarationIsNotASource:
    def test_the_schema_url_is_not_scanned_as_a_source(self):
        doc = json.dumps({"$schema": VEGA_SCHEMA, "mark": "bar"})
        # Both scanners: a document parses as a dict literal, so it reaches the
        # AST walk, and falls back to the regex only when it does not.
        for engine in ("python", "vega-lite"):
            assert sg.scan_sources(doc, engine) == [], engine

    def test_a_real_data_url_in_the_same_document_still_is(self):
        # The exclusion is the `$schema` KEY, not the vega.github.io host and
        # not "documents are exempt": a spec that names data still grounds it.
        doc = json.dumps({
            "$schema": VEGA_SCHEMA,
            "data": {"url": "https://example.org/rows.csv"},
            "mark": "bar",
        })
        refs = sg.scan_sources(doc, "python")
        assert [(r.kind, r.literal) for r in refs] == [
            ("url", "https://example.org/rows.csv"),
        ]

    def test_a_schema_url_under_any_other_key_is_still_a_source(self):
        # Only the declaration is exempt. The same URL sitting in `data.url`
        # is a fetch the node will make.
        doc = json.dumps({"data": {"url": VEGA_SCHEMA}, "mark": "bar"})
        assert [r.literal for r in sg.scan_sources(doc, "python")] == [VEGA_SCHEMA]

    def test_the_regex_scanner_skips_it_too(self):
        # A document that does NOT parse as Python falls through to the regex
        # scanner, which has to apply the same rule.
        broken = '{"$schema": "%s", "mark": "bar",}{' % VEGA_SCHEMA
        assert sg.scan_sources(broken, "vega-lite") == []
