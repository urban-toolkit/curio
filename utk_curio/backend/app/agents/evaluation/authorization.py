"""The marker an evaluation writes into the project it builds.

``dataflow.evaluation = {runId, fixtureId, createdAt}`` names the run and the
shipped example it is scored against (graph-backed state, ``DEC-040``).
``application/turns/examples.py`` reads ``fixtureId`` so that no run in the
project is shown that example among its worked examples. ``live.py`` and the
in-process reconstruction driver in the tests write it.

Pure: values in, values out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

#: Where the marker lives in a project's spec.
MARKER_KEY = "evaluation"


@dataclass(frozen=True)
class EvaluationMarker:
    run_id: str
    fixture_id: str
    created_at: str

    def as_dict(self) -> dict:
        return {
            "runId": self.run_id,
            "fixtureId": self.fixture_id,
            "createdAt": self.created_at,
        }


def new_marker(run_id: str, fixture_id: str) -> EvaluationMarker:
    return EvaluationMarker(
        run_id=run_id,
        fixture_id=fixture_id,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def mark_spec(spec: Mapping, marker: EvaluationMarker) -> dict:
    """Return *spec* with the marker written into its dataflow."""
    out = dict(spec or {})
    dataflow = dict(out.get("dataflow") or {})
    dataflow[MARKER_KEY] = marker.as_dict()
    out["dataflow"] = dataflow
    return out


def marker_of(spec: Mapping) -> EvaluationMarker | None:
    dataflow = (spec or {}).get("dataflow")
    raw = (dataflow or {}).get(MARKER_KEY) if isinstance(dataflow, Mapping) else None
    if not isinstance(raw, Mapping) or not raw.get("runId"):
        return None
    return EvaluationMarker(
        run_id=str(raw.get("runId")),
        fixture_id=str(raw.get("fixtureId") or ""),
        created_at=str(raw.get("createdAt") or ""),
    )
