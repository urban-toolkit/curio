"""The evaluation gate: activate what you have evaluated (dev/122, ``DEC-078``).

A trained model cannot be activated until an evaluation of **that exact model
id**, on the **held-out** split, with **matching fixture digests**, exists. Four
refusals, each with its own message, because each has a different fix.

What the gate deliberately is **not**: a threshold. Curio does not compute a
pass mark for a trained model, rank it against the base model, or recommend
activation — no such mark is justifiable today, and a platform-set one would be
Curio judging model quality on the user's behalf. The gate says *"you have
evaluated this exact model on data it did not train on, and here is what it
scored"*; the decision is the person's.

And the score in it comes from dev/121's **deterministic comparator**. No agent
and no model — least of all the candidate — participates in the approval path,
so ``DEC-055``'s report-only boundary and ``DEC-028``'s self-certification
firewall stand, and dev/11's *"a candidate cannot judge/approve itself"*
survives into training exactly as written.

Pure: values in, values out. The record's file lives beside its job's.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from utk_curio.backend.app.agents.training.records import (
    JOB_ID_RE,
    TrainingRecordError,
    training_dir,
)

GATE_VERSION = 1

#: The only split an activation gate may be computed on. Measuring on the data
#: a model trained on measures memorisation, and the leak is invisible in the
#: numbers afterwards (``DEC-077``).
GATE_SPLIT = "heldout"


class GateRefused(Exception):
    """Activation is refused, and this says which of the four reasons."""


@dataclass(frozen=True)
class GateRecord:
    """One evaluation of one trained model, as the harness produced it."""

    trained_model: str
    split: str
    run_id: str
    fixture_digests: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    categories: dict = field(default_factory=dict)
    evaluated_at: str = ""
    evaluated_via: str = ""
    comparator: str = "deterministic"
    provider: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "gateVersion": GATE_VERSION,
            "trainedModel": self.trained_model,
            "split": self.split,
            "runId": self.run_id,
            "fixtureDigests": dict(self.fixture_digests),
            "scores": dict(self.scores),
            "categories": dict(self.categories),
            "evaluatedAt": self.evaluated_at
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "evaluatedVia": self.evaluated_via,
            # Recorded so a reader never has to wonder whether a model graded
            # itself: it did not, and this says which mechanism scored it.
            "comparator": self.comparator,
            "provider": dict(self.provider),
        }

    @classmethod
    def from_dict(cls, payload: Mapping) -> "GateRecord":
        return cls(
            trained_model=str(payload.get("trainedModel") or ""),
            split=str(payload.get("split") or ""),
            run_id=str(payload.get("runId") or ""),
            fixture_digests=dict(payload.get("fixtureDigests") or {}),
            scores=dict(payload.get("scores") or {}),
            categories=dict(payload.get("categories") or {}),
            evaluated_at=str(payload.get("evaluatedAt") or ""),
            evaluated_via=str(payload.get("evaluatedVia") or ""),
            comparator=str(payload.get("comparator") or "deterministic"),
            provider=dict(payload.get("provider") or {}),
        )


def gate_path(user_key: str, job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id or ""):
        raise TrainingRecordError(f"invalid training job id: {job_id!r}")
    return training_dir(user_key) / f"{job_id}.gate.json"


def write_gate(user_key: str, job_id: str, gate: GateRecord) -> Path:
    path = gate_path(user_key, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(gate.as_dict(), handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    return path


def read_gate(user_key: str, job_id: str) -> GateRecord | None:
    try:
        payload = json.loads(gate_path(user_key, job_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise TrainingRecordError(
            f"could not read the evaluation for {job_id}: {exc}"
        ) from exc
    return GateRecord.from_dict(payload) if isinstance(payload, dict) else None


def heldout_digests(fixtures: Iterable) -> dict:
    """``{fixtureId: fixtureSha256}`` for the held-out split as it is today."""
    return {
        fixture.fixture_id: fixture.fixture_sha256()
        for fixture in fixtures
        if fixture.split == GATE_SPLIT
    }


def check(
    *,
    gate: GateRecord | None,
    trained_model: str | None,
    corpus_digests: Mapping,
) -> GateRecord:
    """Return the gate, or refuse with the reason that applies.

    The four refusals, in the order they are checked:

    1. **No evaluation.** Activating what nobody evaluated is the single thing
       this gate exists to prevent.
    2. **A different model.** A report about the base model, or about another
       job's model, says nothing about this one.
    3. **The wrong split.** Validating on what was trained on measures
       memorisation (``DEC-077``).
    4. **Stale digests.** The examples moved since the evaluation, so the
       evaluation describes a corpus that no longer exists.
    """
    if not (trained_model or "").strip():
        raise GateRefused(
            "this job has no trained model yet, so there is nothing to activate"
        )
    if gate is None:
        raise GateRefused(
            "no evaluation exists for this model. Run the held-out evaluation "
            "first — activating a model you have not evaluated is exactly what "
            "this refusal is for."
        )
    if gate.trained_model != trained_model:
        raise GateRefused(
            f"the evaluation on file is for {gate.trained_model!r}, not "
            f"{trained_model!r}: a report about another model says nothing "
            "about this one"
        )
    if gate.split != GATE_SPLIT:
        raise GateRefused(
            f"the evaluation used the {gate.split!r} split; an activation gate "
            f"must use {GATE_SPLIT!r}, because measuring on data a model "
            "trained on measures memorisation"
        )
    expected = dict(corpus_digests)
    recorded = dict(gate.fixture_digests)
    if not recorded:
        raise GateRefused(
            "the evaluation recorded no fixture digests, so it cannot be "
            "checked against the corpus it claims to describe"
        )
    if recorded != expected:
        moved = sorted(
            set(recorded) ^ set(expected)
        ) or sorted(k for k in expected if expected[k] != recorded.get(k))
        raise GateRefused(
            "the held-out examples changed since this evaluation "
            f"({', '.join(moved[:4])}): re-run it against the current corpus"
        )
    return gate


def summary(gate: GateRecord) -> dict:
    """What the panel shows beside Activate: the numbers, never a verdict."""
    scores = [float(v) for v in gate.scores.values() if isinstance(v, (int, float))]
    return {
        "trainedModel": gate.trained_model,
        "split": gate.split,
        "runId": gate.run_id,
        "evaluatedAt": gate.evaluated_at,
        "fixtures": len(gate.fixture_digests),
        "scores": dict(gate.scores),
        "categories": dict(gate.categories),
        "meanScore": round(sum(scores) / len(scores), 4) if scores else None,
        "comparator": gate.comparator,
        # Said out loud, because the absence of a verdict is the design.
        "note": (
            "Scores come from the deterministic comparator, on examples this "
            "model did not train on. Curio does not decide whether they are "
            "good enough — that is your call."
        ),
    }
