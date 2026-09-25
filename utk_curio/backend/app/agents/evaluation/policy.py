"""The one user policy an evaluation plays (memo dev/123, ``DEC-079``).

An evaluation has to decide what its "user" does with each proposal the agent
returns, and that decision cannot vary between callers: a UI run, a remote CLI
run and a CI run that answered differently would be measuring three different
things while reporting one number.

The policy, written once:

1. Send the fixture's prompt once. Never rephrase.
2. Apply a plan proposal whole — no per-node edits.
3. Apply a dataset, package or project install **only** when the fixture
   required that resource. Anything else is left pending, with its reason.
4. Add no correction rounds; the runtime's bound is the bound.
5. Solve every pending node once, with verification on.
6. Read the persisted spec, canonicalize, compare, score.

This module owns rules 2 and 3 — the per-proposal decision. The rest is the
caller's sequence, and every caller runs the same one.

Pure: values in, values out. Before this existed the rule lived in two places
(``evaluation/live.py`` and the deterministic test driver), which is one rule
that will drift; a test now asserts every caller resolves the same decision for
the same proposal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

#: Proposal kinds an evaluation may apply at all. Everything else — a content
#: write, a package draft, a node-template creation — is a decision a person
#: makes, so an unattended run leaves it pending and says so.
APPLICABLE_TOOLS = (
    "dataflow.plan.write",
    "dataset.install",
    "package.install",
    "project.install",
)

#: Which pin names the resource each install kind targets. Read from the
#: proposal's PINS — the revision-safety basis the apply endpoint re-checks —
#: never from a params echo, which is not on the part at all (dev/122 F-c).
_TARGET_PIN = {
    "dataset.install": "datasetId",
    "package.install": "dirName",
}


@dataclass(frozen=True)
class Decision:
    """What the policy does with one proposal, and why."""

    apply: bool
    tool: str
    target: str = ""
    reason: str = ""

    @property
    def pending(self) -> bool:
        return not self.apply

    def as_dict(self) -> dict:
        return {
            "apply": self.apply,
            "tool": self.tool,
            "target": self.target,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class UserPolicy:
    """The evaluation's stand-in for a person clicking Apply."""

    required_datasets: frozenset = frozenset()
    required_packages: frozenset = frozenset()

    @classmethod
    def for_fixture(cls, fixture) -> "UserPolicy":
        required = fixture.required
        return cls(
            required_datasets=frozenset(str(d) for d in required.get("datasets") or ()),
            required_packages=frozenset(str(p) for p in required.get("packages") or ()),
        )

    def decide(self, proposal: Mapping) -> Decision:
        """Apply, or leave pending with a reason a report can print."""
        tool = str((proposal or {}).get("tool") or "")
        pins = (proposal or {}).get("pins") or {}
        if tool == "dataflow.plan.write":
            return Decision(apply=True, tool=tool)
        if tool == "project.install":
            # dev/106 (DEC-068): a specialist the run needs but the project
            # lacks. Refusing it would fail the run for a reason the fixture
            # did not ask about.
            return Decision(apply=True, tool=tool, reason="a required specialist")
        if tool not in APPLICABLE_TOOLS:
            return Decision(
                apply=False, tool=tool,
                reason=f"{tool} is a decision a person makes, not an unattended run",
            )
        pin = _TARGET_PIN[tool]
        target = str(pins.get(pin) or "")
        wanted = (
            self.required_datasets if tool == "dataset.install"
            else self.required_packages
        )
        if target and target in wanted:
            return Decision(apply=True, tool=tool, target=target)
        return Decision(
            apply=False, tool=tool, target=target,
            reason=(
                f"{target or 'an unnamed resource'} is not required by this fixture"
            ),
        )

    def decide_all(self, proposals: Iterable) -> tuple:
        return tuple(self.decide(proposal) for proposal in proposals)
