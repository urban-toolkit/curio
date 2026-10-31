"""The Vega-Lite charts that compare scenarios (``docs/examples/vega-lite-charts``):
each chart's entry in ``charts.json`` (its label, widgets and spec file) and its
spec. They were the Scout package's chart templates until #1270; a test that
read a chart's template from that manifest reads it here."""
from __future__ import annotations

import json
from pathlib import Path

CHARTS_DIR = Path(__file__).resolve().parents[4] / "docs" / "examples" / "vega-lite-charts"


def chart(chart_id: str) -> dict:
    """The chart's entry: ``id``, ``label``, ``spec`` (its file), ``description``
    and ``widgets``."""
    listed = json.loads((CHARTS_DIR / "charts.json").read_text(encoding="utf-8"))["charts"]
    (found,) = [c for c in listed if c["id"] == chart_id]
    return found


def spec(chart_id: str) -> str:
    """The chart's spec, as its file holds it."""
    return (CHARTS_DIR / chart(chart_id)["spec"]).read_text(encoding="utf-8")
