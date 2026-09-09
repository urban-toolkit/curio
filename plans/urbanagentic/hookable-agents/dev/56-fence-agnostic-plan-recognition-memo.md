# Implementation Memo: Fence-Agnostic Plan Recognition (dev/52 follow-up, fourth round)

Date: 2026-08-05
Status: implemented 2026-08-05 — COMMIT-a59447a3. Verification: backend `pytest tests
--ignore=tests/test_frontend` → 1022 passed; the reported scenario (a valid plan in a ```json
fence with trailing prose) is regression-pinned end-to-end, run and stream, including the
persisted-text strip and the strip-button mirror.

## 1. Problem Statement (root cause, reproduced)

dev/54 made imperfect `curio.v1` plan tails self-correct; dev/55 honored the toolRequest form.
Both only recognize a plan inside a ` ```curio.v1 ` fence **at the very end of the reply**
(`split_tail`'s terminal contract). Real models overwhelmingly emit JSON in ` ```json ` (or
bare ` ``` `) fences, frequently mid-reply with explanatory prose after — reproduced: a
**perfectly valid** plan in a ```json fence followed by "Click the Apply button…" produces NO
part, NO diagnosis, NO correction, NO card. The runtime is blind to the attempt; the plan JSON
renders as chat text; the model believes it delivered a plan and directs the user to a button
that does not exist. This matches the report exactly and explains why the dev/54/55 correction
machinery never engaged.

## 2. Approach — recognize the attempt wherever the model writes it (plan-granted agents only)

- `content.extract_plan_attempt(reply)`: for a reply that mentions `dataflowPlan` /
  `dataflow.plan.write`, scan ALL fenced blocks (any info string, any position, newest last —
  bounded by the plan budget) for a plan payload: `{"dataflowPlan": …}`, the toolRequest form,
  or the bare plan object (`goal` + `nodes`). Returns the reply with that block stripped plus
  the raw payload — or the unparseable block body when the fence is plan-ish but its JSON is
  broken (so the JSON error still feeds back). Non-plan replies and every other agent are
  byte-identical (the function is only consulted by the plan handler, and only when the
  terminal-tail paths found nothing).
- `services._handle_plan_reply`: when the tail paths yield nothing, consult the scanner —
  valid → the SAME mint (same proposal/card/strip button), with the fence block stripped from
  the persisted text (the review card is the plan's home, not raw JSON); invalid → the SAME
  corrective round, with one added instruction: put the block in a ` ```curio.v1 ` fence as the
  very last thing in the reply. Streaming: a ```json fence has already streamed by the time the
  round ends — the persisted transcript is stripped and the card still arrives; corrected
  retries use the proper tail and get withheld normally.
- No new budgets, no fallback paths: the scanner is attempt *recognition* feeding the existing
  mint and correction machinery.

## 3. Tests / Acceptance

- content: ```json fence + trailing prose → payload extracted, block stripped; bare-fence and
  bare-plan-object shapes; broken-JSON plan-ish fence returns the body for diagnosis; non-plan
  fences untouched.
- routes: a valid ```json-fenced plan mints (persisted reply keeps the prose, drops the JSON);
  an invalid one corrects (feedback includes the curio.v1 fence guidance) then mints; ungranted
  agents keep byte-identical text (regression); stream variant mints with `review_required`.
- [x] A plan emitted in ANY common shape — curio.v1 tail, toolRequest form, ```json fence,
      bare fence, mid-reply — ends in an applyable proposal or an explained failure.

## 4. Commits

1. `Fence-agnostic plan recognition: the runtime meets the model where it writes (dev/56)`
2. Docs: memo implemented + BL-P5 amendment.
