# Implementation Memo: The Plan's toolRequest Form — Instruction Contradiction Resolved (dev/52 follow-up)

Date: 2026-08-05
Status: proposed (implementing in the same session — explicit fix request, third round; the
user's transcript shows the model apologizing that it "cannot directly apply a plan" and
directing the user to a nonexistent button)

## 1. Problem Statement (root cause, reproduced from the runtime's own prompt)

The run's system turn CONTRADICTS itself. The grants paragraph (dev/41, generated for every
granted tool) teaches: *"To use one, end your reply with exactly one fenced block of this form:
`{"toolRequest": {"tool": "<tool id>", "params": {}}}`"* — and lists `dataflow.plan.write` right
above it. A model that follows this (reasonably!) emits the plan as
`{"toolRequest": {"tool": "dataflow.plan.write", "params": {…plan…}}}`. Two dead ends, both
reproduced:

1. A small plan in that form parses as a toolRequest → `_mint_proposal` has **no
   `dataflow.plan.write` branch** → the model is refused ("no proposal flow exists"), concludes
   it cannot apply plans, and instructs the user to click an Apply button that was never
   created — the reported transcript verbatim.
2. A realistic-size plan in that form (> 1,024-byte params) fails `_parse_tool_request`'s params
   cap → the WHOLE block fails open as raw text (the dev/54 hold only matches `dataflowPlan`
   part payloads, not this shape).

dev/54's correction rounds work — for the `dataflowPlan` block form. The toolRequest form the
prompt itself advertises was a hole.

## 2. Approach — the toolRequest form becomes a first-class equivalent (no fallback: the prompt teaches it, so the runtime honors it)

- `content.py`: per-tool params budget — `dataflow.plan.write` params get the plan budget
  (`PLAN_TAIL_MAX_BYTES`), every other tool keeps 1,024 bytes byte-identically; the enlarged
  whole-tail budget also admits bodies carrying `"dataflow.plan.write"`; the dev/54 stream hold
  covers the toolRequest form too. `parse_dataflow_plan_verbose` becomes public for the mint.
- `services._mint_proposal`: a `dataflow.plan.write` branch — the plan payload is
  `params.dataflowPlan ?? params`, validated by the SAME verbose parser; errors return as the
  tool refusal text (which the EXISTING tool-result round feeds back — self-correction shared
  with dev/54, one budget); a valid plan routes into `_mint_dataflow_plan` exactly like the
  block form (same proposal, same pins, same review card, same strip button).
- Both forms now mint identically; whichever paragraph the model follows, it cannot be wrong.

## 3. Tests / Acceptance

- content: the toolRequest form with a large plan parses (params budget); other tools' params
  cap regression-pinned; stream hold covers the form.
- routes: the toolRequest form mints (nested `params.dataflowPlan` AND direct `params`); an
  invalid toolRequest-form plan feeds errors back and corrects next round; the user's exact
  scenario — a model emitting the toolRequest form — ends in an applyable proposal.
- [ ] Whichever syntax the model chooses, a valid plan yields the Apply control; an invalid one
      self-corrects or fails loudly. The prompt and the runtime no longer disagree.

## 4. Commits

1. `Plan toolRequest form: first-class mint + params budget, resolving the grants-paragraph contradiction (dev/55)`
2. Docs: memo implemented + BL-P5 amendment.
