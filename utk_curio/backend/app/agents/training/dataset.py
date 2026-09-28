"""The training set: the oracle's answer, for approved fixtures only (dev/122).

One row per eligible fixture, in the chat shape a fine-tuning surface takes:

    {"messages": [{"role": "system",    "content": "<the runtime's own system turn>"},
                  {"role": "user",      "content": "<the fixture's prompt>"},
                  {"role": "assistant", "content": "<the plan block the parser accepts>"}]}

Four properties, each deliberate and each test-pinned:

1. **The target is the runtime's own contract.** It comes from
   ``evaluation.oracle.plan_for`` — the same bytes the deterministic harness
   drives the real mint with — and every row is re-parsed through the
   production parser before it is kept. A target that would not parse cannot be
   written, because teaching a model to emit blocks the runtime refuses is
   worse than teaching it nothing.
2. **What the contract cannot express is excluded by construction.** An
   interaction edge raises ``Unrepresentable``, so those fixtures are omitted
   *with their reason recorded* rather than trained on a weakened graph.
3. **The system turn is composed by the runtime's own composer**
   (``contracts.compose_system``, with ``services.roster_block`` and the
   coordinate's own prompt bytes), so the model is trained against the prompt
   shape it will actually be served.
4. **Approval and split are gates, not filters.** The rows come from
   ``evaluation.export.rows_for_split(..., purpose="training")``, which already
   refuses the held-out and validation splits by name and refuses a prompt no
   person has approved. Nothing here works around either.

Pure: values in, values out. No store, no provider, no network.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable, Mapping

from utk_curio.backend.app.agents import contracts
from utk_curio.backend.app.agents.evaluation import export as export_mod
from utk_curio.backend.app.agents.evaluation import oracle

#: The coordinate whose prompt bytes and roster a plan is produced under.
DFB_COORD = "agent.dataflow-builder@1.0.0"

#: Bound on one training set. The corpus is 31 fixtures; this exists so a
#: future corpus cannot silently become an upload nobody looked at.
MAX_ROWS = 500

#: The only data classification eligible for upload (memo dev/122 §3.3, and
#: ``OQ-010``'s default posture: nothing unclassified is eligible).
ELIGIBLE_DATA_CONTENT = "identifiers-only"


class TrainingSetRefused(Exception):
    """The set cannot be built, and this says why."""


@dataclass(frozen=True)
class ExcludedFixture:
    fixture_id: str
    reason: str

    def as_dict(self) -> dict:
        return {"fixtureId": self.fixture_id, "reason": self.reason}


@dataclass(frozen=True)
class TrainingSet:
    """What would be uploaded, and everything needed to describe it honestly."""

    rows: tuple = ()
    fixture_ids: tuple = ()
    excluded: tuple = ()
    instruction_sha256: str = ""
    roster_digest: str = ""
    split: str = "train"

    @property
    def jsonl(self) -> str:
        return "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
            for row in self.rows
        )

    @property
    def content(self) -> bytes:
        return self.jsonl.encode("utf-8")

    @property
    def bytes_len(self) -> int:
        return len(self.content)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def as_dict(self) -> dict:
        return {
            "split": self.split,
            "rows": len(self.rows),
            "bytes": self.bytes_len,
            "sha256": self.sha256,
            "fixtureIds": list(self.fixture_ids),
            "excluded": [e.as_dict() for e in self.excluded],
            "instructionSha256": self.instruction_sha256,
            "rosterDigest": self.roster_digest,
        }


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def system_turn(
    *,
    preamble: str | None,
    instruction: str,
    tail: str,
    roster: str | None,
) -> str:
    """The system content a run would carry, composed as a run composes it.

    The caller supplies each piece from the production source rather than
    letting this module invent any of them.
    """
    return contracts.join_system(contracts.compose_system(
        preamble=preamble, instruction=instruction, tool_protocol=tail, runtime=[roster],
    ))


def data_content_of(fixture) -> str:
    """A fixture's declared data classification.

    Absent means ``identifiers-only`` for the shipped corpus, whose rows carry
    catalog ids and repo-authored text — but the declaration is what a test
    asserts, so a future fixture cannot become eligible by omission.
    """
    consent = fixture.data.get("consent")
    if not isinstance(consent, Mapping):
        return ELIGIBLE_DATA_CONTENT
    value = consent.get("dataContent")
    return str(value) if isinstance(value, str) and value.strip() else ELIGIBLE_DATA_CONTENT


def licence_of(fixture) -> str:
    consent = fixture.data.get("consent")
    if isinstance(consent, Mapping) and isinstance(consent.get("licence"), str):
        return consent["licence"]
    return ""


def build_training_set(
    fixtures: Iterable,
    *,
    split: str = "train",
    instruction: str,
    preamble: str | None,
    tail: str,
    roster: str | None,
    roster_digest: str = "",
    scrub=None,
    credential_finder=None,
    parse_reply=None,
) -> TrainingSet:
    """Build the rows for *split*, or refuse and say why.

    Every collaborator is injected so this module stays pure and every rule can
    be tested on its own: ``scrub`` is ``evaluation.report.scrub``,
    ``credential_finder`` is ``source_grounding.credential_literals``, and
    ``parse_reply`` is the production reply-level plan recognition (see
    :func:`plan_target_check`).
    """
    if not (instruction or "").strip():
        raise TrainingSetRefused(
            f"{DFB_COORD} has no instruction prompt on disk; a training example "
            "composed without it would not match what a run is served."
        )

    # Approval and split are the export's gates; a training purpose additionally
    # refuses the held-out and validation splits by name.
    try:
        rows_for_split = export_mod.rows_for_split(
            fixtures, split=split, purpose="training", require_approved=True
        )
    except export_mod.ExportRefused as refusal:
        raise TrainingSetRefused(str(refusal)) from refusal

    eligible = {row.fixture_id: row for row in rows_for_split}
    by_id = {f.fixture_id: f for f in fixtures}

    composed = system_turn(
        preamble=preamble, instruction=instruction, tail=tail, roster=roster
    )
    rows: list = []
    kept: list = []
    excluded: list = []

    for fixture_id, row in eligible.items():
        fixture = by_id.get(fixture_id)
        if fixture is None:
            excluded.append(ExcludedFixture(fixture_id, "fixture not loaded"))
            continue
        classification = data_content_of(fixture)
        if classification != ELIGIBLE_DATA_CONTENT:
            # OQ-010's posture: unclassified or user content is ineligible for
            # remote egress until it has a consent surface of its own (F2).
            excluded.append(
                ExcludedFixture(
                    fixture_id,
                    f"data classification {classification!r} is not "
                    f"{ELIGIBLE_DATA_CONTENT!r}",
                )
            )
            continue
        try:
            plan = oracle.plan_for(fixture.expected, intents=fixture.intents)
        except oracle.Unrepresentable as gap:
            excluded.append(ExcludedFixture(fixture_id, gap.need))
            continue

        target = plan.as_reply()
        if parse_reply is not None:
            ok, detail = parse_reply(target)
            if not ok:
                excluded.append(
                    ExcludedFixture(fixture_id, f"target does not parse: {detail}")
                )
                continue

        user_content = row.prompt + (f"\n\n{row.context}" if row.context else "")
        message_row = {
            "messages": [
                {"role": "system", "content": composed},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": target},
            ]
        }
        if scrub is not None:
            message_row = _scrub_row(message_row, scrub)
        _refuse_if_credentialed(message_row, fixture_id, credential_finder)
        rows.append(message_row)
        kept.append(fixture_id)

    if not rows:
        raise TrainingSetRefused(
            "nothing to train on: "
            + (
                "; ".join(f"{e.fixture_id} ({e.reason})" for e in excluded)
                or f"no fixture in the {split!r} split is approved"
            )
        )
    if len(rows) > MAX_ROWS:
        raise TrainingSetRefused(
            f"{len(rows)} rows exceeds the {MAX_ROWS}-row bound for one training set"
        )

    return TrainingSet(
        rows=tuple(rows),
        fixture_ids=tuple(kept),
        excluded=tuple(excluded),
        instruction_sha256=_sha256_text(instruction),
        roster_digest=roster_digest or _sha256_text(roster or ""),
        split=split,
    )


def plan_target_check(reply: str) -> tuple:
    """``(ok, detail)`` — would the runtime accept this reply's plan?

    Two steps, the runtime's own: recognise the payload in the reply
    (``content.extract_plan_attempt``, which is fence-agnostic exactly as a
    live run is), then validate it with the mint's verbose parser
    (``content.parse_dataflow_plan_verbose``, which returns the same
    field-level errors a correction round feeds back). A target that fails
    either step is not a training example — it is a lesson in producing
    something the product refuses.
    """
    from utk_curio.backend.app.agents import content as content_mod

    try:
        _stripped, payload = content_mod.extract_plan_attempt(reply)
        if payload is None:
            return False, "no plan block was recognised in the target"
        plan, errors = content_mod.parse_dataflow_plan_verbose(payload)
    except Exception as exc:  # noqa: BLE001 - a refusal is a refusal
        return False, str(exc)
    if plan:
        return True, ""
    return False, "; ".join(str(e) for e in (errors or [])) or "the parser returned no plan"


def _scrub_row(row: dict, scrub) -> dict:
    return {
        "messages": [
            {"role": message["role"], "content": scrub(message["content"])}
            for message in row["messages"]
        ]
    }


def _refuse_if_credentialed(row: dict, fixture_id: str, credential_finder) -> None:
    """Refuse a row that still looks credentialed after scrubbing.

    A prompt is repo-authored text, so this should be impossible. If it ever
    happens, something is wrong that an upload must not paper over — the
    build stops rather than sending a redacted-looking row.
    """
    if credential_finder is None:
        return
    for message in row["messages"]:
        for engine in ("python", "text"):
            found = credential_finder(message["content"], engine)
            if found:
                names = ", ".join(sorted({name for name, _line in found}))
                raise TrainingSetRefused(
                    f"{fixture_id}: a credential-shaped literal ({names}) survived "
                    "scrubbing; refusing to upload rather than sending it redacted"
                )
