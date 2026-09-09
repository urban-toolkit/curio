"""Evaluation records and reports (memo dev/121).

A live run's value is its record, not its verdict: which provider and model
answered, against which prompt and which agent instruction (by digest), what
the agent produced, how it differed from the example, how long it took and how
many tokens it spent. The score rides along, and the header says plainly that
these are evaluation reports rather than release gates (``DEC-077``).

Two rules the writer enforces.

*Nothing secret is written.* Every transcript, every proposal payload and every
error string goes through :func:`scrub`, which redacts values the caller knows
(``utk_curio.common.redaction`` -- the ONE redactor, dev/116) and masks
credential-shaped literals the model may have typed, using
``source_grounding.credential_literals`` to decide WHICH lines carry a
credential so the rule about what counts as one stays in the gate.

*No cost is invented.* Curio has no price table, so ``cost`` is ``null`` unless
an operator supplied a rate on the command line, and then it is labelled as
theirs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from utk_curio.backend.app.agents import source_grounding
from utk_curio.backend.app.agents.evaluation.scoring import Score
from utk_curio.common.redaction import REDACTED_TEMPLATE, redact

#: A long quoted token on a line the credential rule flagged. Deliberately NOT
#: a second opinion about what a credential is -- that stays in
#: ``source_grounding`` -- only the masking of the value on a flagged line.
_QUOTED_LONG_TOKEN = re.compile(r"""(['"])((?:Bearer\s+)?[A-Za-z0-9_\-.~+/=]{20,})\1""")


def scrub(text: object, *, values: Mapping | None = None, engine: str = "python") -> object:
    """Redact known secret values, then mask credential-shaped literals.

    Non-strings pass through; a mapping or list is scrubbed element-wise so a
    whole proposal payload can be handed over in one call.
    """
    if isinstance(text, Mapping):
        return {key: scrub(value, values=values, engine=engine) for key, value in text.items()}
    if isinstance(text, (list, tuple)):
        return [scrub(item, values=values, engine=engine) for item in text]
    if not isinstance(text, str):
        return text
    out = redact(text, values) or text
    flagged = source_grounding.credential_literals(out, engine)
    if not flagged:
        # The regex form also catches JSON and prose the AST walk skips.
        flagged = source_grounding.credential_literals(out, "text")
    if not flagged:
        return out
    names = {line: name for name, line in flagged}
    lines = out.splitlines(keepends=True)
    for index, line in enumerate(lines):
        name = names.get(index + 1)
        if not name:
            continue
        lines[index] = _QUOTED_LONG_TOKEN.sub(
            lambda match: f"{match.group(1)}{REDACTED_TEMPLATE.format(name=name)}{match.group(1)}",
            line,
        )
    return "".join(lines)


@dataclass(frozen=True)
class ProviderRecord:
    """Who answered. The key is never read, never received, never written."""

    api_type: str = ""
    base_url_host: str = ""
    model: str = ""

    def as_dict(self) -> dict:
        return {
            "apiType": self.api_type,
            "baseUrlHost": self.base_url_host,
            "model": self.model,
        }


@dataclass(frozen=True)
class Digests:
    """What was pinned. A score without these cannot be reproduced or trusted
    later: the same prompt against a changed instruction is a different run."""

    fixture_sha256: str = ""
    prompt_sha256: str = ""
    agent_instruction_sha256: str = ""
    roster_digest: str = ""

    def as_dict(self) -> dict:
        return {
            "fixtureSha256": self.fixture_sha256,
            "promptSha256": self.prompt_sha256,
            "agentInstructionSha256": self.agent_instruction_sha256,
            "rosterDigest": self.roster_digest,
        }


@dataclass
class AttemptRecord:
    """One attempt at one fixture: what was asked, what came back, how it
    scored, and enough debugging material to see why."""

    fixture_id: str
    attempt: int = 1
    tier: str = "T0"
    needs: tuple = ()
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    latency_ms: int = 0
    usage: dict = field(default_factory=lambda: {"inputTokens": 0, "outputTokens": 0})
    digests: Digests = field(default_factory=Digests)
    score: Score | None = None
    comparison: dict = field(default_factory=dict)
    transcript: list = field(default_factory=list)
    proposals: list = field(default_factory=list)
    generated_spec: dict | None = None
    skipped: list = field(default_factory=list)
    review_status: str = "pending-owner-review"
    error: str | None = None

    def as_dict(self, *, secret_values: Mapping | None = None) -> dict:
        return {
            "fixtureId": self.fixture_id,
            "attempt": self.attempt,
            "tier": self.tier,
            "needs": list(self.needs),
            "startedAt": self.started_at,
            "latencyMs": self.latency_ms,
            "usage": dict(self.usage),
            "digests": self.digests.as_dict(),
            "score": self.score.as_dict() if self.score else None,
            "comparison": scrub(self.comparison, values=secret_values),
            "transcript": scrub(self.transcript, values=secret_values),
            "proposals": scrub(self.proposals, values=secret_values),
            "generatedSpec": scrub(self.generated_spec, values=secret_values),
            "skipped": list(self.skipped),
            "reviewStatus": self.review_status,
            "error": scrub(self.error, values=secret_values),
        }

    @property
    def categories(self) -> tuple:
        return self.score.categories if self.score else ("harness-error",)

    @property
    def total(self) -> float:
        return self.score.total if self.score else 0.0


@dataclass
class RunReport:
    """Every attempt of one evaluation run, plus how to read it."""

    run_id: str
    mode: str = "scripted"           # scripted | live
    provider: ProviderRecord = field(default_factory=ProviderRecord)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attempts: list = field(default_factory=list)
    price_per_mtoken: tuple | None = None   # (input, output), operator-supplied
    notes: list = field(default_factory=list)

    def add(self, attempt: AttemptRecord) -> None:
        self.attempts.append(attempt)

    def cost(self) -> dict | None:
        """``None`` unless an operator supplied a rate. Curio has no price
        table and will not invent one."""
        if not self.price_per_mtoken:
            return None
        input_rate, output_rate = self.price_per_mtoken
        tokens_in = sum(a.usage.get("inputTokens", 0) for a in self.attempts)
        tokens_out = sum(a.usage.get("outputTokens", 0) for a in self.attempts)
        return {
            "operatorSupplied": True,
            "ratePerMTokenInput": input_rate,
            "ratePerMTokenOutput": output_rate,
            "estimatedUsd": round(
                tokens_in / 1_000_000 * input_rate + tokens_out / 1_000_000 * output_rate, 4
            ),
        }

    def category_histogram(self) -> dict:
        histogram: dict = {}
        for attempt in self.attempts:
            for category in attempt.categories:
                histogram[category] = histogram.get(category, 0) + 1
        return dict(sorted(histogram.items()))

    def as_dict(self, *, secret_values: Mapping | None = None) -> dict:
        return {
            "runId": self.run_id,
            "mode": self.mode,
            "kind": "evaluation-report",
            "isReleaseGate": False,
            "provider": self.provider.as_dict(),
            "startedAt": self.started_at,
            "attempts": [a.as_dict(secret_values=secret_values) for a in self.attempts],
            "cost": self.cost(),
            "categoryHistogram": self.category_histogram(),
            "unreviewedPrompts": sum(
                1 for a in self.attempts if a.review_status != "approved"
            ),
            "notes": list(self.notes),
        }

    def write(self, out_dir: Path, *, secret_values: Mapping | None = None) -> tuple:
        directory = Path(out_dir) / self.run_id
        directory.mkdir(parents=True, exist_ok=True)
        json_path = directory / "report.json"
        json_path.write_text(
            json.dumps(self.as_dict(secret_values=secret_values), indent=2) + "\n",
            encoding="utf-8",
        )
        markdown_path = directory / "report.md"
        markdown_path.write_text(self.as_markdown(), encoding="utf-8")
        return json_path, markdown_path

    def as_markdown(self) -> str:
        provider = self.provider
        lines = [
            f"# Agent reconstruction evaluation — `{self.run_id}`",
            "",
            "**This is an evaluation report, not a release gate.** Scores here "
            "describe how a model did against the shipped examples on one run; "
            "nothing in Curio passes or fails because of them (memo dev/121, "
            "`DEC-077`).",
            "",
            f"- Mode: `{self.mode}`",
            f"- Provider: `{provider.api_type or 'unknown'}`"
            + (f" @ `{provider.base_url_host}`" if provider.base_url_host else ""),
            f"- Model: `{provider.model or 'unknown'}`",
            f"- Started: {self.started_at}",
            f"- Fixtures attempted: {len({a.fixture_id for a in self.attempts})}"
            f" ({len(self.attempts)} attempts)",
        ]
        unreviewed = sum(1 for a in self.attempts if a.review_status != "approved")
        if unreviewed:
            lines.append(
                f"- Prompts not yet owner-approved: {unreviewed} "
                "(the prompts are drafted and committed; a human has not signed them off)"
            )
        cost = self.cost()
        lines.append(
            f"- Cost: {cost['estimatedUsd']} USD at the operator's supplied rate"
            if cost
            else "- Cost: not computed (Curio has no price table)"
        )
        lines += ["", "## Per fixture", "",
                  "| Fixture | Tier | Score | Categories | Attempts | Latency (ms) | Tokens in/out |",
                  "|---|---|---|---|---|---|---|"]
        by_fixture: dict = {}
        for attempt in self.attempts:
            by_fixture.setdefault(attempt.fixture_id, []).append(attempt)
        for fixture_id, attempts in sorted(by_fixture.items()):
            best = max(attempts, key=lambda a: a.total)
            categories = sorted({c for a in attempts for c in a.categories})
            lines.append(
                f"| `{fixture_id}` | {best.tier} | {best.total:.2f} | "
                f"{', '.join(categories)} | {len(attempts)} | "
                f"{max(a.latency_ms for a in attempts)} | "
                f"{sum(a.usage.get('inputTokens', 0) for a in attempts)}/"
                f"{sum(a.usage.get('outputTokens', 0) for a in attempts)} |"
            )
        lines += ["", "## Failure categories", "", "| Category | Fixtures |", "|---|---|"]
        for category, count in self.category_histogram().items():
            lines.append(f"| `{category}` | {count} |")
        if self.notes:
            lines += ["", "## Notes", ""] + [f"- {note}" for note in self.notes]
        lines.append("")
        return "\n".join(lines)


def new_run_id(prefix: str = "eval") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def digest_of(values: Iterable) -> str:
    """A stable digest over a set of strings -- used for the roster snapshot,
    so a report can say whether two runs saw the same templates."""
    import hashlib

    joined = "\n".join(sorted(str(v) for v in values))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
