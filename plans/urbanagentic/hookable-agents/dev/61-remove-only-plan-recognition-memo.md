# Implementation Memo: Remove-Only Plan Recognition — the Scanner Learns dev/59's Grammar (dev/56 + dev/59 follow-up)

Date: 2026-08-05
Status: proposed (implementing in the same session — explicit fix request: "clear the canvas"
now produces a plan whose JSON leaks raw into the transcript, no Apply button, pills stuck)

## 1. Problem Statement

Asking the Dataflow Builder to clear the canvas produces a remove-only plan — and everything
downstream of it fails at once (user screenshot, 3:36 PM):

- The plan JSON (`removeNodes` with every node id, `"removeEdges": []`) renders as a **raw
  code block** in the transcript instead of a review card.
- **No Apply button** appears (card or strip), and asking to apply in chat gets "Please review
  and apply the plan on your canvas" — the model believes it proposed; nothing was minted.
- The **builder pills stay on the previous session's state** (READY + old solved/skipped
  nodeRuns) — the phase never flips to plan_review because no proposal exists.

Root cause, confirmed in code: the dev/56 fence-agnostic scanner predates dev/59 and was never
taught that remove-only plans exist. `content.extract_plan_attempt` recognizes a plan block by
(a) the markers `"dataflowPlan"` / `"dataflow.plan.write"`, or (b) the bare shape
`'"goal"' AND '"nodes"'` (content.py:488-489), and claims a bare payload only when
`"goal" in payload and "nodes" in payload` (content.py:509). A remove-only bare plan —
`{"goal": …, "removeNodes": […]}` — legitimately carries **no `nodes` key** (the dev/59
grammar synthesizes `nodes: []` for it, content.py:352-353), so an unmarked ```json block
passes both checks unrecognized. `_handle_plan_reply` returns `("none", …)`: no mint, no
corrective round, no loud cap card — the exact fail-open leak dev/54 closed for additive
plans, reopened for the dev/59 removal grammar. `plan_tail_diagnosis` (content.py:522-523)
has the same marker blindness for broken-JSON remove-only bodies.

Everything downstream already works: the grammar accepts remove-only plans
(`test_remove_only_plan_is_valid`), the mint pins victims and flips builderSession to
plan_review, apply removes and prunes (`test_remove_only_plan_applies`), and the review card
renders the Removes section + destructive effect line (dev/59). Only recognition is broken.

Why it matters: the model composes exactly what its instruction (step 2b) tells it to, the
runtime silently ignores it, and the model then hallucinates that a proposal exists — the
worst trust posture (dev/54's founding principle: never fail silently).

## 2. Scope

In scope:
- `utk_curio/backend/app/agents/content.py` — `extract_plan_attempt` (marker + bare-claim
  predicates), `plan_tail_diagnosis` (marker predicate), docstrings.
- `utk_curio/backend/tests/test_agents/test_content.py` — `TestExtractPlanAttempt`,
  `TestPlanTailDiagnosis` additions.
- `utk_curio/backend/tests/test_agents/test_routes.py` — one route-level regression in
  `TestFenceAgnosticPlanRecognition` reusing `TestDestructiveReplan`'s seeded spec.

Out of scope (verified working or deliberate):
- `_mint_dataflow_plan` / `_apply_dataflow_plan` — remove-only already covered (dev/59).
- Frontend: card, strip, pills, canvas bridge — all react correctly once a proposal exists;
  the stale READY pills were the *absence* of a mint, not a frontend defect. (The card's
  "0 nodes · 0 connections" header line on a remove-only plan is factual; polish only if the
  user asks.)
- builderSession persisting across a chat-transcript clear — by design: nodeRuns describe
  canvas state, which survives the transcript.
- `orchestration_instruction.txt` — step 2b is correct; the model followed it.

## 3. Recommended Implementation Approach

Teach every recognition predicate the dev/59 keys — they are curio-plan-specific strings, as
distinctive as `dataflowPlan` itself:

1. `extract_plan_attempt` markers: `marked = "dataflowPlan" in body or "dataflow.plan.write"
   in body or '"removeNodes"' in body or '"removeEdges"' in body`. A broken-JSON remove-only
   block thereby takes the diagnose path (returns the body string) instead of leaking.
2. Bare-payload claim: `("goal" in payload and "nodes" in payload) or "removeNodes" in
   payload or "removeEdges" in payload`. A remove-only payload missing `goal` is still
   CLAIMED — the verbose parser's "goal …" field error then feeds the corrective round
   (dev/54's self-correcting contract) instead of the block leaking.
3. `plan_tail_diagnosis` marker predicate gains the same two keys, so a terminal curio.v1
   tail carrying a broken remove-only attempt is diagnosed with the JSON error detail rather
   than returning None (its valid-JSON bare path still returns None — the scanner claims
   those, unchanged division of labor).

No new code paths: recognition widens, then the existing dev/54 correction loop, dev/55
toolRequest form, dev/56 strip-the-block mint, and dev/59 mint validation do what they
already do. The scanner is consulted only for plan-granted agents (unchanged), so the new
markers cannot affect chat-only agents.

## 4. Data and State Handling

Unchanged. The recognized payload flows through `parse_dataflow_plan_verbose` →
`_mint_dataflow_plan` (victim existence + digest pins) → proposal part + activeProposal
mirror → builderSession.phase = plan_review. The visible reply persists with the JSON block
stripped (the card is the plan's home, dev/56).

## 5. UI and UX Requirements

All existing surfaces, now actually reached: review card with the Removes section naming
every victim (+ content warnings, cascade count), destructive effect line, Apply/Dismiss on
card and strip, pills flipping READY → REVIEW on mint and back to READY after apply.

## 6. Edge Cases

- Remove-only bare block, `removeEdges: []` present but empty (the user's exact payload) —
  recognized via `"removeNodes"` marker and claimed via `removeNodes` key.
- Remove-only block missing `goal` — claimed; corrective round demands the goal.
- Broken JSON containing `removeNodes` — diagnose path with the JSON error, not a leak.
- `{"removeEdges": […]}` only (rewire-only) — recognized and claimed.
- Additive plans — byte-identical behavior (predicates only widened).
- Non-plan JSON fences in plan-granted agents that merely mention neither marker — untouched.
- Ungranted agents — scanner not consulted (existing guard), fences stay verbatim.

## 7. Testing Strategy

- `TestExtractPlanAttempt`: remove-only bare ```json fence (goal + removeNodes +
  removeEdges: []) → payload claimed, block stripped; remove-only without `goal` → still
  claimed; broken-JSON remove-only body → body string returned (diagnose path).
- `TestPlanTailDiagnosis`: broken-JSON tail mentioning `removeNodes` → error list, not None.
- Route regression (`TestFenceAgnosticPlanRecognition`): the user's exact scenario — prose +
  bare ```json remove-only block over a seeded 2-node spec → proposal minted with
  `plan.removals`, block stripped from the reply, `builderSession.phase == "plan_review"`.
- Full backend suite green.

## 8. Acceptance Criteria

- [ ] "Clear the canvas" yields a review card naming every node to remove, with the Apply
      button on card and strip, and pills on REVIEW — no raw JSON block in the transcript.
- [ ] A malformed remove-only attempt feeds the corrective rounds (loud cap card at budget),
      never a silent leak.
- [ ] Additive-plan recognition and ungranted-agent behavior are byte-identical.

## 9. Recommended Commit Breakdown

1. `Remove-only plan recognition: the dev/56 scanner learns the dev/59 grammar (dev/61)` —
   content.py predicates + content/route tests.
2. `Docs: dev/61 implemented + BL-P5 amendment`.

## 10. Engineering Quality Checklist

- No duplicated logic — predicates widened in place; parsing/minting untouched.
- Fail-loud preserved: unrecognized → now claimed → corrective rounds → cap card.
- No frontend change; no new state; no behavior change for non-plan agents.
- Regression tests pin the user's exact payload shape.
