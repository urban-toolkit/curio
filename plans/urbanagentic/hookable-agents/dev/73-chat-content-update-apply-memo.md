# Implementation Memo 73: Chat-Initiated Node Content Updates Must Mint the Review — Not Depend on the Model's Second Step

Date: 2026-08-12
Status: implemented 2026-08-12 — COMMIT-95f7fc27 (runtime mint + honest cap +
roster/prompt contracts + tests, one commit; the memo's commits 1–3 landed
together because the DFB roster test depends on all three). Verification:
backend 1167 passed (8 skipped); no frontend changes required (the
`review_required.attachmentId` key is additive, the cutoff card renders
through the generic card shell, delegation entries already link homes).
BL-P5-20260812-17. Recorded deviations: (1) the cutoff card is minted-parts
plumbing (`minted`), not a session-only line — it persists with the turn and
renders through the existing card shell; (2) NB instruction step 6 also
dropped its mention of `node.read` (never granted to the Node Builder — a
pre-existing instruction/grant mismatch found during implementation);
(3) the blocking client path reloads attachments only for local proposals —
recorded as follow-up, the stream is the primary transport.

## 1. Problem Statement

In a solved dataflow session, asking either the node's attached Node Builder
or the Dataflow Builder to fix/change a node's content fails in two visible
ways: the agent CLAIMS the change was applied while the node is untouched,
or it prints the code (whole or fragment) in prose with no Apply button.
Three root causes compound, all in the chat loop (`run_attachment` /
`stream_attachment`); the Solve/validate paths are unaffected:

- **RC1 — the tool-round budget contradicts the Node Builder's own
  instructions.** `MAX_TOOL_ROUNDS = 2` (services.py:4447), but
  `node_build_instruction.txt` step 6 prescribes a THREE-round modify flow:
  read the node (`node.read` / `node.runtime.read`) → delegate
  `node.content.generate` → propose `node.content.write`. A model that
  follows its instructions is structurally blocked: after its 2nd request
  the result message appends "No further tool calls are available this turn
  — answer with what you have" (`_delegate_result_message`), forcing prose
  code with no Apply; and if it emits the write request anyway, the loop
  SILENTLY drops it at the cap ("dangling request at the cap: dropped, text
  kept" — services.py:5159-5160 and :5425-5426) while keeping the reply's
  confident prose. The user reads "I've applied the fix", nothing minted.
  When the model happens to skip the read round, the two-step flow fits the
  budget and works — exactly the intermittent behavior observed.
- **RC2 — chat delegations mint nothing applyable.** Only the Solve/propose
  drain (services.py:3134) and validate-node turn a child's generated
  content into a reviewed `node.content.write` proposal. In CHAT, a
  successful `node.content.generate` delegation feeds the code back to the
  parent model as an untrusted text message and appends the child's raw
  reply to the delegation home's transcript (dev/72) — visible code in the
  node agent's chat, no proposal part, no Apply button. Applyability hangs
  entirely on the model performing the second toolRequest step (the exact
  fragile contract the fix-primary-paths rule forbids).
- **RC3 — the Dataflow Builder has no working update path and its offered
  path invites the false claim.** Its grants are `dataflow.read`,
  `dataflow.plan.write`, `node.runtime.read` — no content write, and plans
  are content-free by contract (dev/67-5). Its instruction says to REDIRECT
  content changes (step 6), but its delegation paragraph offers `node.build`
  → delegating "fix node X" to a DEC-046 tool-less child whose reply is
  never parsed produces text only; `node.content.generate` also resolves
  (capability-first fallback, NCB installed) but hits RC2. Either way the
  parent model then summarizes success.

Why it matters: this is the primary post-solve iteration loop — the user's
day-two workflow. Today it produces false "applied" claims (trust damage),
dead-end code dumps, and a review model (DEC-006: no mutation without
review) that silently fails instead of failing loud.

## Expected Behavior (user-visible walkthrough)

1. In the node's Node Builder chat: "the date parsing is wrong, fix it" →
   the agent reads/delegates as needed, and a **reviewed content proposal
   with Apply/Dismiss appears in that chat** — every time generation
   succeeds, regardless of how many read rounds preceded it or whether the
   model remembers its second step. The reply summarizes the change and
   points at the review; it never restates the full code and never claims
   application.
2. In the Dataflow Builder chat: "update the Analyze node to use median" →
   the DFB delegates content generation; the runtime mints the review **on
   that node's attached Node Builder** (dev/72 home), the DFB's reply
   carries the delegation entry whose icon-link opens it, and the plan row
   chip (when a plan is showing) links the same place. No claim of
   application — the truthful line is "a reviewed change awaits your Apply
   in <node>'s Node Builder."
3. If the model runs out of tool rounds holding a mutate request, the user
   sees an honest system note that the proposal step was cut off — never a
   silent drop under confident prose.
4. Applying the minted proposal writes the node content live (existing
   apply/bridge path, unchanged) — after which, and only after which, the
   transcripts may say "applied".
5. What no longer happens: "changes applied" with an untouched node; code
   fragments in prose as the final answer; the Apply button existing only
   when the model performed a fragile copy-back step.

## 2. Scope

In scope (backend — services.py chat loop, BOTH blocking and stream):
- **Runtime-minted content reviews from chat delegations (RC2, the primary
  fix):** after a successful `node.content.generate` delegation whose node
  id resolves (the request's `inputs.nodeId` or the attachment's node
  target — the same resolution `_enriched_delegate_inputs` already uses),
  the loop mints the `node.content.write` proposal directly from the
  child's content (reusing `_mint_node_content_write` + the dev/72 home:
  the node's Node Builder attachment when it exists, else the current
  attachment), appends the proposal part at the home and the delegation
  part on the parent turn (already present), and feeds the model a result
  message that states a reviewed proposal now awaits the user — instruct it
  to summarize, link, and NOT restate content or claim application. The
  stream emits `review_required` for the minted proposal as it already
  does for loop-minted proposals.
- **Honest cap behavior (RC1):** raise `MAX_TOOL_ROUNDS` to 3 (the
  documented modify flow is read → generate → write; with the primary fix
  the write round becomes unnecessary, but read+read+generate still needs
  3), and replace the silent drop of a dangling MUTATE toolRequest at the
  cap with a visible outcome: an error-kind card part on the final turn
  ("ran out of tool rounds before the proposal — ask me to continue")
  instead of keeping only the prose. Read-tool dangles may keep the
  current text-kept behavior.
- **Instruction contracts (RC1/RC3):** `node_build_instruction.txt` step 6
  — after delegating generation, the runtime mints the review; do not
  re-emit the content, summarize and point to the review, never claim
  application. `orchestration_instruction.txt` step 6 — for an existing
  node's content change, delegate `node.content.generate` with the node's
  id (the review appears at that node's agent); never delegate `node.build`
  for edits, never claim application. builtin.py: add
  `agent.node-content-builder` to the Dataflow Builder's `delegates_to` so
  the capability is OFFERED in its delegation paragraph (today it resolves
  only through the silent capability-first fallback).

In scope (tests): loop tests for both call sites (chat delegate → minted
homed proposal + review_required + parent delegation part), cap honesty
(dangling write surfaces the card), DFB paragraph offering, prompt-digest
pin updates.

Out of scope: the Solve/validate mint paths (already correct); the apply
endpoint and canvas bridge (unchanged); DEC-046 invariants (children stay
tool-less, replies stay unparsed BY THE MODEL — the runtime minting from
the child's returned content is the same sanctioned pattern the Solve
drain already uses); reply-text lie detection (no fallback heuristics —
the fix is making the primary path unable to lie).

## 3. Recommended Implementation Approach

- **One mint helper, three callers.** Extract the Solve drain's
  content→proposal sequence (extract_node_content → home resolution →
  `_mint_node_content_write` at the home → proposal turn at the home →
  parent delegation-part turn when homes differ) into a
  `_mint_content_review_from_delegate(...)` used by the drain and both
  chat-loop delegate branches. The chat loops pass their `minted` list so
  the proposal part rides the parent turn exactly like loop-minted
  proposals do today.
- **The delegate-result message is the new contract:** on a minted review,
  the fed-back text becomes "the generated content was minted as reviewed
  proposal <id> at <home> — it awaits the user's explicit Apply; summarize
  the change in one or two sentences, do NOT restate the code, do NOT say
  it was applied." (mirrors `_mint_node_content_write`'s existing warning.)
- **Cap honesty is a classification, not a heuristic:** at the break, if
  the dropped request's `tool` is one of the mutate kinds `_mint_proposal`
  dispatches, append the error card part; otherwise keep today's behavior.
- **Roster/prompt changes ride the existing materialization** (prompt
  files + builtin.py tuples); pinned digests in tests update deliberately.

## 4. Data and State Handling

- No new stores. Proposals use the existing single-activeProposal +
  dev/67-9 parking + dev/72 homing semantics: a chat-minted content review
  on the node's agent parks nothing on the builder; on the SAME attachment
  it supersedes a pending older proposal exactly as loop mints do today.
- `nodeProposals` is untouched (that ledger belongs to plan-driven
  solves); a chat-initiated review is an ordinary proposal.
- Race safety: the mint re-reads the spec (existing `_mint_node_content_write`
  behavior) and digest-pins against current content; a stale pin still
  surfaces as the existing "stale" outcome at apply time.
- The solved builder session is untouched by chat updates until Apply
  writes content through the existing path.

## 5. UI and UX Requirements

- No new frontend surfaces: the review card, the dev/72 delegation entry
  with icon-link, and the `review_required` strip already render everything
  minted here. Verify the node-agent home path shows the proposal card on
  arrival (session refresh on `review_required` / `proposalAttachmentId`).
- The cap-cutoff card renders through the existing error-kind card shell.
- Wording stays honest and consistent: "review and apply below" at the
  home; "the review lives in <node>'s Node Builder" on the parent.

## 6. Edge Cases

- Delegation returns empty/unusable content → no mint; the result message
  says so; the model reports failure honestly (existing refusal text path).
- Node id unresolvable (canvas-target parent, no nodeId input) → no mint;
  result message tells the model to name the node id and retry (fits the
  raised round budget).
- The node's NB attachment missing → home falls back to the current
  attachment (existing `_delegation_home` create/find semantics; chat may
  create — unlike solve workers, the loop owns the spec write).
- Two updates in one conversation → second mint supersedes the first
  pending review at the same home (existing `_store_proposal`).
- A pending plan on the DFB when a content review mints on the DFB itself
  → the plan parks (existing dev/67-9 mechanics, unchanged).
- Guest/keyless and blocking (non-stream) runs behave identically — the
  mint lives in shared loop code, not the transport.
- MAX_TOOL_ROUNDS=3 cost ceiling: worst case one extra provider round per
  run; the ledger reserve/settle path is per-run and unchanged.

## 7. Testing Strategy

- Backend loop (blocking + stream): NB node-target attachment, scripted
  model does read → delegate generate → prose; assert a pending
  `node.content.write` proposal exists at the home, the parent turn carries
  proposal/delegation parts, `review_required` fired (stream), and the
  fed-back message contains the do-not-claim contract.
- DFB canvas attachment delegating generate with `nodeId` → proposal homed
  at the node's NB attachment; parent gets the linkable delegation part.
- Cap honesty: scripted model emits a 4th-round `node.content.write` →
  final turn carries the cutoff error card, never silence.
- Roster: DFB `delegates_to` includes NCB; delegation paragraph offers
  `node.content.generate`; pinned lists/digests updated deliberately.
- Regression: Solve/propose drain still mints once (no double-mint through
  the shared helper); dev/72 suites stay green.

## 8. Acceptance Criteria

- [x] Any successful chat-initiated `node.content.generate` delegation with
      a resolvable node yields a pending reviewed proposal with Apply — in
      the node agent's chat when attached, else the current chat — with no
      dependence on the model emitting a follow-up toolRequest.
- [x] The Dataflow Builder path routes edits through delegation and
      produces the homed review + icon-linked delegation entry; it can no
      longer "apply" anything in prose.
- [x] A mutate toolRequest dropped at the round cap surfaces as a visible
      cutoff note; instructed 3-round flows fit the budget.
- [x] Agents' replies for these flows summarize and link; the transcripts
      never claim application before the user applies.

## 9. Recommended Commit Breakdown

1. Backend: `_mint_content_review_from_delegate` extraction + both chat
   call sites + result-message contract + tests.
2. Backend: MAX_TOOL_ROUNDS=3 + mutate-dangle cutoff card + tests.
3. Roster/prompts: DFB delegates_to + instruction step-6 rewrites (NB +
   DFB) + pinned-test updates.
4. Docs: memo flip + BL-P5 entry.

## 10. Engineering Quality Checklist

- The primary path is runtime-owned: generation success ⇒ review exists
  (no model-dependent copy-back step, no fallback heuristics).
- One content→review sequence shared by solve and chat (no duplication).
- DEC-006/DEC-046 preserved: nothing mutates without review; children stay
  tool-less; the MODEL still never parses child replies.
- Failures are loud: cap cutoffs and unusable content are visible outcomes.
- Prompt/roster pins updated deliberately with the reasons recorded.
