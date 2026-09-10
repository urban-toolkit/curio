"""The automated approval an evaluation needs, granted narrowly (dev/123).

``DEC-048`` makes every phase boundary of the plan lifecycle an explicit human
action, and it is right to: applying a proposal changes the user's dataflow. An
evaluation cannot wait for clicks, so it applies proposals itself — which is an
automated approval, and therefore a decision rather than a detail.

The grant, and every bound on it:

- **One project.** The service marks the project it created with
  ``dataflow.evaluation = {runId, fixtureId, createdAt}`` (graph-backed state,
  ``DEC-040``). :func:`assert_may_auto_apply` refuses unless that marker exists.
- **One run.** The marker's ``runId`` must equal the run doing the applying, so
  a later run — or a person — cannot reuse an old evaluation project as a
  standing permission.
- **A closed set of kinds.** Only what the shared policy may apply at all
  (``policy.APPLICABLE_TOOLS``). A content write, a package draft or a node
  template creation is refused here even if some future policy allowed it.
- **Nothing global.** No agent's ``review_policy`` is edited, no grant is
  widened, and ``apply_proposal`` keeps its drift re-check. Outside an
  evaluation project this function refuses every time — which is the assertion
  that keeps the grant honest, and it is a test.
- **Recorded.** The caller appends an ``auto-applied`` event naming the tool,
  the target, the proposal and the run, so a reader can see exactly what was
  approved on the user's behalf and why it was allowed.

The same marker answers a second question, and it is the other half of keeping
a run's result real: **who may replace the graph the run built.** A canvas save
is a whole-spec ``PUT`` carrying the browser's live nodes and no revision
basis, so a canvas that loaded this project before the plan was applied will,
on its next save, write its empty graph over the run's work — which is exactly
how a finished run came to have a score and an empty canvas. Nodes are not a
backend-owned section the way ``dataflow.agents``, ``packages`` and
``datasets`` are (a person's canvas *is* the authority for them), so the answer
cannot be a blanket carry-forward. :func:`assert_client_may_replace_graph`
narrows it to the two cases where the client cannot be the authority:

- while the run is still writing (the run owns its project until it finishes),
- and a save that would leave a run-built graph with no nodes at all, whenever
  it arrives — the stale-canvas wipe, which is loss rather than editing.

Editing a finished evaluation project is otherwise untouched: the project is
the user's to change or delete, which is what the panel promises.

Pure: values in, values out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

from utk_curio.backend.app.agents.evaluation import policy as policy_mod

#: Where the marker lives in a project's spec.
MARKER_KEY = "evaluation"


class AutoApplyRefused(Exception):
    """This proposal may not be applied without a person, and this says why."""


class ClientSaveRefused(Exception):
    """A client save would destroy an evaluation run's graph, and this says why.

    Raised at the projects domain's request; it translates this into its own
    error type so the caller sees a 409 with this sentence.
    """


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


def is_evaluation_project(spec: Mapping) -> bool:
    return marker_of(spec) is not None


def assert_may_auto_apply(spec: Mapping, *, run_id: str, proposal: Mapping) -> None:
    """Raise :class:`AutoApplyRefused` unless this exact run may apply this
    proposal in this project."""
    marker = marker_of(spec)
    if marker is None:
        raise AutoApplyRefused(
            "this project is not an evaluation project, so nothing may be "
            "applied without a person: an evaluation's automated approval is "
            "scoped to the project it created"
        )
    if marker.run_id != str(run_id):
        raise AutoApplyRefused(
            f"this project belongs to evaluation {marker.run_id!r}, not "
            f"{run_id!r}: an evaluation project is not a standing permission"
        )
    tool = str((proposal or {}).get("tool") or "")
    if tool not in policy_mod.APPLICABLE_TOOLS:
        raise AutoApplyRefused(
            f"{tool or 'this proposal'} is not one of the kinds an unattended "
            "evaluation may apply"
        )


def _node_count(spec: Mapping) -> int:
    dataflow = (spec or {}).get("dataflow")
    nodes = (dataflow or {}).get("nodes") if isinstance(dataflow, Mapping) else None
    return len(nodes) if isinstance(nodes, list) else 0


def assert_client_may_replace_graph(
    existing_spec: Mapping,
    incoming_spec: Mapping,
    *,
    run_in_flight: bool,
) -> None:
    """Raise :class:`ClientSaveRefused` when a client save would destroy the
    graph an evaluation run built (see the module docstring for why).

    *existing_spec* is what is on disk, *incoming_spec* what the client sent,
    and *run_in_flight* whether that project's run has yet to reach a terminal
    phase — the caller reads the record, so this stays pure.

    Silent on every project that is not an evaluation project, and on every
    save that adds to or edits a finished run's graph rather than emptying it.
    """
    marker = marker_of(existing_spec)
    if marker is None:
        return
    if run_in_flight:
        raise ClientSaveRefused(
            f"evaluation {marker.run_id} is still building this project, so its "
            "dataflow cannot be saved over yet — the run writes the graph, and "
            "the project is yours to edit once it finishes"
        )
    if _node_count(existing_spec) > 0 and _node_count(incoming_spec) == 0:
        raise ClientSaveRefused(
            f"this save would leave the dataflow evaluation {marker.run_id} "
            "built with no nodes at all, which is how a canvas opened before "
            "the run finished erases it — reload the project to see the "
            "dataflow, then edit it, or delete the project if you are done "
            "with it"
        )
