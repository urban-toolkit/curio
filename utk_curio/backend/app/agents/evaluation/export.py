"""Fine-tuning export (memo dev/121, ``DEC-077``).

Turns approved fixtures into prompt -> expected-dataflow pairs, one JSON object
per line, for a split the caller names. That is the whole feature: there is no
train verb here and no provider call anywhere in this module, because Curio has
no fine-tuning contract to call (``providers.py`` exposes completions and a
model listing, nothing else) and building one is its own memo with its own
consent, redaction, cost, cancellation, versioning, evaluation and rollback
questions.

Two refusals are the point of the module.

*Unapproved prompts never export.* A prompt drafted by a model and not yet
reviewed by a person is fine for measuring; it is not fine as training data
that shapes a model's behaviour.

*Held-out fixtures are never training data.* A held-out set that leaked into
training measures nothing afterwards, and the leak is invisible in the
resulting numbers -- so the request is refused rather than filtered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SPLITS = ("train", "validation", "heldout")

#: Splits a training export may draw from. ``heldout`` is deliberately absent.
TRAINABLE_SPLITS = ("train",)


class ExportRefused(Exception):
    """The export would have leaked evaluation data or unreviewed prompts."""


@dataclass(frozen=True)
class ExportRow:
    fixture_id: str
    prompt: str
    context: str | None
    expected: dict
    required: dict
    split: str
    fixture_sha256: str
    source_path: str

    def as_dict(self) -> dict:
        return {
            "fixtureId": self.fixture_id,
            "prompt": self.prompt,
            "context": self.context,
            "expected": self.expected,
            "required": self.required,
            "split": self.split,
            "fixtureSha256": self.fixture_sha256,
            "source": self.source_path,
        }


def rows_for_split(
    fixtures: Iterable,
    *,
    split: str,
    purpose: str = "evaluation",
    require_approved: bool = True,
) -> list:
    """The export rows for one split.

    ``purpose`` is ``"training"`` or ``"evaluation"``. A training export may
    only draw from :data:`TRAINABLE_SPLITS`; asking it for the held-out split
    is refused, not silently narrowed.
    """
    if split not in SPLITS:
        raise ExportRefused(
            f"unknown split {split!r}; expected one of {', '.join(SPLITS)}"
        )
    if purpose not in ("training", "evaluation"):
        raise ExportRefused(f"unknown purpose {purpose!r}")
    if purpose == "training" and split not in TRAINABLE_SPLITS:
        raise ExportRefused(
            f"a training export may not draw from the {split!r} split: held-out "
            "and validation fixtures are how a trained model is judged, and a "
            "set that leaked into training cannot judge anything (DEC-077)"
        )
    rows: list = []
    unapproved: list = []
    for fixture in fixtures:
        if fixture.split != split:
            continue
        if require_approved and not fixture.approved:
            unapproved.append(fixture.fixture_id)
            continue
        rows.append(
            ExportRow(
                fixture_id=fixture.fixture_id,
                prompt=fixture.prompt,
                context=fixture.context,
                expected=fixture.expected,
                required=fixture.required,
                split=fixture.split,
                fixture_sha256=fixture.fixture_sha256(),
                source_path=str(fixture.data.get("source", {}).get("path") or ""),
            )
        )
    if unapproved and require_approved and not rows:
        raise ExportRefused(
            "nothing to export: every fixture in this split is still awaiting "
            "review — "
            + ", ".join(sorted(unapproved))
            + ". A model may draft a prompt; a person approves it before it "
            "becomes training or evaluation data."
        )
    return rows


def write_jsonl(rows: Iterable, path: Path) -> int:
    """Write the rows and return how many were written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.as_dict(), sort_keys=True) + "\n")
            written += 1
    return written


def split_summary(fixtures: Iterable) -> dict:
    """``{split: {"total": n, "approved": n}}`` -- what an export would find."""
    summary: dict = {split: {"total": 0, "approved": 0} for split in SPLITS}
    for fixture in fixtures:
        bucket = summary.setdefault(fixture.split, {"total": 0, "approved": 0})
        bucket["total"] += 1
        if fixture.approved:
            bucket["approved"] += 1
    return summary
