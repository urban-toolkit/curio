"""Approving a prompt from inside the product (memo dev/123).

A fixture's prompt is drafted by a model and **approved by a person**; that
approval is what lets it become evaluation or training data. Until now the only
way to record it was to hand-edit the JSON, and the owner's first attempt at
that produced ``"papproved"`` — a status the schema rejects, which broke every
suite at collection. A review that can be mistyped is a review that belongs in
the interface.

So: the panel that shows a prompt is the place its review is recorded. This
module writes the review block back into the fixture file, and refuses to write
anything the schema would reject.

Two things it deliberately does **not** do. It does not invent a reviewer: the
name recorded is the account performing the action. And it does not touch a
fixture's ``expected`` graph, digest, split or prompt — only the review block —
so approving cannot smuggle a change into what is being measured.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from utk_curio.backend.app.agents.evaluation.fixtures import (
    Fixture,
    fixture_paths,
    load_fixture,
    validate_fixture_dict,
)

#: The statuses this action can set. ``rejected`` is in the schema but has no
#: consumer yet, so it is not offered here.
SETTABLE = ("approved", "pending-owner-review")


class ReviewRefused(Exception):
    """The review could not be recorded, and this says why."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class ReviewOutcome:
    fixture_id: str
    status: str
    reviewed_by: str | None
    reviewed_at: str | None
    path: str

    def as_dict(self) -> dict:
        return {
            "fixtureId": self.fixture_id,
            "status": self.status,
            "reviewedBy": self.reviewed_by,
            "reviewedAt": self.reviewed_at,
            "path": self.path,
        }


def find_fixture(fixture_id: str) -> Fixture:
    for path in fixture_paths():
        if path.stem.replace(".prompt", "") == fixture_id or path.stem == fixture_id:
            return load_fixture(path)
    raise ReviewRefused(f"no prompt fixture {fixture_id!r}", 404)


def reviewer_name(user) -> str:
    """Who is recording this. The account, never a guess."""
    for attribute in ("username", "name", "email"):
        value = getattr(user, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    identifier = getattr(user, "id", None)
    return f"user {identifier}" if identifier is not None else "unknown"


def set_review(fixture_id: str, *, status: str, user) -> ReviewOutcome:
    """Record a review decision in the fixture file.

    Refuses a status the schema does not allow, a guest (a shared account
    cannot stand in for a named reviewer), and a checkout it cannot write to —
    each with its own reason, because each has a different fix.
    """
    if status not in SETTABLE:
        raise ReviewRefused(
            f"a review may be set to {' or '.join(SETTABLE)}, not {status!r}"
        )
    if getattr(user, "is_guest", False):
        raise ReviewRefused(
            "the shared guest account cannot approve a prompt: a review records "
            "who made it, and this account is not a person",
            403,
        )

    fixture = find_fixture(fixture_id)
    payload = json.loads(json.dumps(fixture.data))
    review = dict(payload.get("review") or {})
    review["status"] = status
    if status == "approved":
        review["reviewedBy"] = reviewer_name(user)
        review["reviewedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        # Back to pending: the reviewer fields go with it, because a pending
        # prompt with a reviewer's name on it is a lie about its state.
        review["reviewedBy"] = None
        review["reviewedAt"] = None
    payload["review"] = review

    # The file must still be a valid fixture afterwards — this is what makes a
    # mistyped status impossible rather than merely unlikely.
    validate_fixture_dict(payload, where=str(fixture.path))
    _assert_only_review_changed(fixture.data, payload)

    path = Path(fixture.path)
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise ReviewRefused(
            f"could not write {path.name}: {exc}. A prompt review is recorded in "
            "the repository, so this needs a writable checkout.",
            409,
        ) from exc

    return ReviewOutcome(
        fixture_id=fixture.fixture_id,
        status=status,
        reviewed_by=review.get("reviewedBy"),
        reviewed_at=review.get("reviewedAt"),
        path=str(path),
    )


def _assert_only_review_changed(before: Mapping, after: Mapping) -> None:
    """Approving may not smuggle a change into what is measured."""
    keys = set(before) | set(after)
    for key in sorted(keys - {"review"}):
        if before.get(key) != after.get(key):
            raise ReviewRefused(
                f"recording a review changed {key!r}, which it must not: only "
                "the review block may move"
            )
