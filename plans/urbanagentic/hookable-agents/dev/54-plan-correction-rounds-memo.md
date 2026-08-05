# Implementation Memo: Plan Correction Rounds — the Primary Path Made Self-Correcting (dev/52 follow-up)

Date: 2026-08-05
Status: proposed (implementing in the same session — explicit fix request: "still not working.
Do not create fallbacks!")

## 1. Problem Statement (root cause, reproduced)

The plan proposal only mints when the model emits a **byte-perfect `dataflowPlan` JSON tail with
exact canonical template ids in one shot**. Anything less is a silent one-shot dead end:

1. **Any grammar slip kills the block silently.** One intent over 300 chars, one malformed JSON
   character, a missing field — the T2 fail-open rule drops the WHOLE tail back into visible
   text: the user watches raw plan JSON stream into the chat ("showing the planned nodes and
   connections") and no proposal exists anywhere — no review card, no strip button (both render
   from a proposal that was never minted). Reproduced directly.
2. **A parseable plan with a wrong template id dies after the loop.** The mint refuses
   (post-loop, `_maybe_mint_plan`) into an error card with no opportunity to correct — the round
   budget is still available but unreachable.

Local providers (llama4/gemma-class) rarely deliver strict large JSON with exact
`<packageId>/<templateId>` ids first-try. The dev/53 changes fixed real defects but not this:
the proposal was never created server-side.

**This is not a fallback request**: the fix makes the PRIMARY path work — the existing bounded
loop already re-prompts on tool results; plan validation failures must use the same machinery.

## 2. Approach — corrective rounds inside the loop (no new budget, no fallback path)

- `content.py`: the plan parser becomes verbose — `_parse_dataflow_plan` gains a sibling that
  returns **precise field-level errors** ("nodes[0].intent is 301 chars (max 300)",
  "edges[2].from references unknown ref 'ghost'", "the block is not valid JSON: …").
  `plan_tail_diagnosis(tail_body)` classifies a terminal tail: not-a-plan-attempt (None) /
  valid ([]) / a plan attempt with errors ([…]) — JSON breakage included.
- `services` (both loop paths): when the agent holds the `dataflow.plan.write` grant and a reply
  carries a plan **attempt** that fails (parse errors OR mint refusal), the runtime feeds the
  errors back as a corrective message (`[plan validation] … fix these problems and resend the
  complete corrected block`) and re-rounds — consuming the SAME `MAX_TOOL_ROUNDS` budget as tool
  and delegate rounds (one bound, no second knob). A valid plan mints exactly as today. At the
  budget cap the failure is LOUD, never silent: the raw tail is released (fail-open transparency
  — model text is never lost) plus the "Plan not proposable" error card carrying the errors.
- **No raw-tail leak while correcting**: the streaming round holds an invalid plan-ish tail
  (payload mentions `dataflowPlan`) instead of flushing it as deltas; it is released only at the
  cap. Corrective-round prose is not folded into the persisted reply (the final round's text is
  the transcript truth — same shape as the visible outcome of tool rounds).
- SSE: a `plan_revision` event per corrective round (skip-tolerant clients ignore it); the chat
  shows a transient "revising the plan …" line via the existing tool-activity path.
- Non-plan agents and every other tail keep byte-identical fail-open behavior (regression-pinned).

## 3. Tests / Acceptance

- content: verbose errors name field, index, and bound; diagnosis classifies JSON breakage /
  valid / non-plan tails; generic fail-open untouched.
- routes (non-stream): invalid-then-corrected mints the proposal (correction message carries the
  precise errors; raw tail never in the persisted reply); wrong-template-id-then-corrected mints
  (the previously dead mint refusal now corrects); persistent failure at the cap → raw tail
  visible + error card with reasons; budget shared with tool rounds; non-granted agents leak the
  tail as before (regression).
- stream: no raw-tail deltas during correction; `plan_revision` then `review_required` ordering;
  cap path releases the tail then the card.
- [ ] A realistic imperfect first attempt ends in a minted, applyable plan proposal — or a loud,
      explained failure. Nothing silent, no fallback paths.

## 4. Commits

1. `Plan correction rounds: verbose plan diagnosis + self-correcting loop, loud cap failure (dev/54)`
2. Docs: memo implemented + BL-P5 amendment.
