# dev/95 — Dataflow Builder → Researcher delegation (dev/90 Follow-up D): runtime-gathered findings, schema replies, grant-gated note minting; Follow-up C (agent recolor) deferred demand-driven

**Status: IMPLEMENTED (2026-08-23) — commits 1–4 landed (`af88f1d1`, `ee9c3371`, `9d5efc56`, + docs); DEC-065 minted; BL-P5-20260823-38. Follow-up D delivered; Follow-up C deferred with re-open conditions.**
Prereqs: dev/90 (Researcher, DEC-060), dev/93 (one template vocabulary + the reuse ladder, DEC-062), dev/94 (executable-instruction rule, DEC-063), A16 (jointly-pending same-run proposal sequences).

---

## 0. Evidence — what wiring D actually requires (code audit, 2026-08-23)

- **The wiring gap is one tuple and one pinned prompt.** The Dataflow Builder's `delegates_to` (builtin.py:229-244) lists twelve specialists — `agent.researcher` is not among them, so a research question asked in the DFB chat cannot reach the notes scenario at all (the reference recording's flow ran through the DFB chat; dev/90 parked exactly this). The DFB prompt is byte-pinned (`test_builtin.py:428/476`, sha256 `02cad07d…`); teaching the new delegation updates that pin **deliberately** — the recorded dev/48 D4 precedent (connection-builder's delegatesTo did the same to the thirteen-manifest byte-identity regression).
- **The Researcher's capability is `research.notes.compose`** (builtin.py:326) — the delegation intent already exists and no second capability is needed. Its tools (`web.search/web.fetch/node.create/package.install/package.draft.apply`) are attachment-run tools; **none of them exist on the delegate path**, because DEC-046 children are structurally tool-less.
- **The tool-less constraint has a standing answer, applied four times already** (DEC-063's own list): the runtime supplies what an instruction depends on as INPUTS — deterministic validator results for `research.verify` (dev/67-4, where the runtime *executes real verification* pre-child), the composed `nodeContext` (dev/67-6), the `buildRequestContract` (dev/90 A8), and `existingPackages` (dev/94). All four live in ONE seam, `_enriched_delegate_inputs` (services.py:6299). D is the **fifth application**: the runtime runs the deployment-configured search (`tools._execute_web_search` — egress-policed, provider-shaped, honest when unconfigured) for the delegated question and injects the results, so the tool-less Researcher synthesizes over REAL evidence exactly as `research.verify` children do.
- **Schema replies from delegates are established** (DEC-063: "recognized by SCHEMA and never by reading intent out of prose"): the delegate-draft mint parses `packageDraft`/toolRequest shapes; dev/94 added `reuseExisting`. A notes reply — `{"answer": …, "notes": [{title, content, color}]}` — is the same species; the Researcher's own A12/A13 contract already defines the notes row shape verbatim.
- **Minting a multi-note sequence at one attachment is solved**: A16's `mintSequenceId` + `queuedProposals` made same-run mints jointly pending (built for precisely the question-note-then-answer-note row). The delegate-mint gate precedent (`_mint_package_draft_from_delegate`) is **the PARENT's grant** — and the DFB's tools today are `dataflow.read / dataflow.plan.write / node.runtime.read`: **no `node.create`**, so note proposals cannot mint at the DFB attachment without adding it (a reviewed lane — the dev/93-D4 posture that gave the Researcher `package.install`: reviewed mutate lanes are additive-safe because nothing lands without the user's Apply).
- **Depth-1 bounds the slice honestly**: a delegated Researcher can never itself delegate to the Package Builder (no cascading, DEC-046) — so the enlist/author rungs of the reuse ladder are structurally out of reach on this path. When no notes template is installed+enlisted, the delegation can still return the ANSWER; only the notes must degrade, with the handback naming the way out (ask the Researcher directly — its attachment runs own the full ladder).
- **Follow-up C (`node.appearance.write` agent recolor) has zero demand evidence**: the manual `NodeColorControl` ships since dev/89 commit 8, agent-selected color at creation works (A12/A13 notes carry colors), and no user ask, recorded scenario, or live transcript has requested an agent recoloring an *existing* node. C is exactly a DEC-056/DEC-064-shaped descope candidate.

### Evidence-backed decision summary

- *Follow-up C — defer demand-driven (RECOMMENDED, and the owner's instruction)*: the two real color surfaces (creation-time agent color, manual recolor) exist; the reviewed `node.appearance.write` mutation would be a third lane with no recorded demand. Re-open conditions: (a) a user or recorded scenario asks an agent to recolor existing nodes; (b) its own memo (the mutation's digest-pinning design in dev/89 Follow-up C's text stays the starting point). Recorded in DEC-065 — a decision, never a silent omission.
- *D Option 1 — full handoff / cascading delegation* (child Researcher runs its own tools or delegates onward): rejected — it breaks DEC-046's depth-1, tool-less structure, the roster's core safety shape.
- *D Option 2 — chat-only answer* (delegate returns prose, no notes): rejected — the notes ARE the reference recording's point; a DFB user would get a strictly worse Researcher than the node-attachment one with no stated reason.
- *D Option 3 (RECOMMENDED) — the standing patterns, composed*: runtime-gathered search inputs (dev/67-4 posture, 5th `_enriched_delegate_inputs` application) + a schema notes-reply contract taught via inputs (A8 posture) + a grant-gated runtime mint of the A16 jointly-pending note sequence (the dev/73/dev/90 one-mint-policy extended once more) + honest degradation when no notes template resolves. Everything below is Option 3.

## 1. Problem Statement

A research question asked in the Dataflow Builder's chat — the surface the reference recording actually shows — dead-ends: the DFB cannot delegate to the Researcher (not in `delegates_to`), and even if it could, a DEC-046 child holds no web tools, no reply schema exists for notes, and the DFB attachment cannot mint `node.create` proposals (no grant). Expected: the DFB delegates `research.notes.compose` with the question; the runtime gathers real search results and hands them (plus the reply contract and the resolved notes template) to the tool-less child; the child's schema reply becomes the A13 note row — one yellow question note, green markdown answer notes — minted as an A16 jointly-pending reviewed sequence at the DFB attachment; the DFB's own reply states the answer in prose. When no notes template is installed+enlisted, the answer still arrives and the handback honestly names the Researcher's attachment (which owns the enlist/author ladder) instead of pretending. Follow-up C is deferred by decision, with re-open conditions on record.

## 2. Scope

Included:

- **Roster**: `agent.researcher` appended to the DFB's `delegates_to` (builtin.py — one tuple entry, commented with this memo); DFB `tools` gains `node.create` (the reviewed creation lane the mint is gated on). The byte-pin test's sha256 updates deliberately with the prompt edit (D4 precedent, stated in the test comment).
- **Enrichment** (`_enriched_delegate_inputs`, the one seam): for `research.notes.compose` — (1) `searchResults`: the runtime runs `tools._execute_web_search` on the delegation's `question` input (egress-policed exactly as attachment runs; unconfigured search rides in honestly as its error text — the child must SAY search was unavailable, never invent findings); (2) `notesReplyContract`: the server-owned reply schema (`{"answer": "<prose>", "notes": [{"title", "content", "color"}]}` + the A13 row rules — yellow question note first, green markdown answer notes, sources as https links); (3) `notesTemplate`: the resolved installed+enlisted presentation template's canonical id via dev/93's `resolve_template` vocabulary — or an honest `null` with the reason. Model-supplied keys always win (the standing rule).
- **Reply mint**: `_mint_notes_from_delegate` — parses the child reply by SCHEMA (a `notes` list of valid rows; never prose intent), validates rows against the A12 bounds, and mints one `node.create` proposal per note as a same-run A16 sequence at the parent attachment, **gated on the parent's `node.create` grant** (no grant → the reply lands as text with the gate named, the `_mint_package_draft_from_delegate` posture). No template resolved → no mint, and the delegation handback carries `notesSkipped: {reason}` so the parent's prose names the Researcher's attachment as the way to enlist/author one.
- **Prompts**: `orchestration_instruction.txt` gains one delegation paragraph (research questions → delegate `research.notes.compose` with the question verbatim; never answer research questions from memory; the reply states the answer, the reviewed notes mirror it; when the handback says notes were skipped, say why and point at the Researcher). `researcher_notes_instruction.txt` gains the DELEGATE posture section (the PB precedent): tool-less, findings arrive as `inputs.searchResults`, reply with EXACTLY the `notesReplyContract` JSON, state search-unavailable honestly when the inputs say so.
- **Tests**: enrichment (search injected, unconfigured-search honesty, template resolution/null, model keys win); mint (schema recognition, A16 jointly-pending sequence, grant gate, template-missing skip with named reason, injection resistance — notes-shaped prose outside the delegation path never mints); the DFB E2E lane (fake provider: delegate → child schema reply → two pending cards → both apply → nodes in spec); byte-pin update test; roster/prompt marker tests.
- **Docs**: DEC-065 (D shipped + C deferred with re-open conditions), ledger BL-P5-…-38, `docs/AGENTS.md`/roster docs delegation row, memo flip.

Out of scope: cascading delegation (depth-1 stands); the enlist/author rungs on the delegate path (structurally unreachable — the handback points at the Researcher's attachment instead); `node.appearance.write` (Follow-up C — deferred by DEC-065); any Researcher-attachment behavior change (its own runs are untouched); web.fetch on the delegate path (one search, no fetches — the ≤4-call budget stays an attachment-run concept; the runtime performs exactly one policed search per delegation).

## 3. Recommended Implementation Approach

One seam per concern, all of them existing: enrichment in `_enriched_delegate_inputs` beside its four siblings; the mint beside `_mint_package_draft_from_delegate` reusing `_store_proposal` (A16 queueing comes free — same `loop_ctx`, same run); template resolution through dev/93's `resolve_template`/`canonical_template_id` (never a second vocabulary); the search through `tools._execute_web_search` (never a second provider adapter — one search, executed server-side, its JSON parsed into bounded rows before injection, capped at the A6 tail budget). The child reply parser is schema-first and bounded (the `_extract_draft_params` conventions: fenced or bare JSON, required keys, arbitrary chat JSON never matches). Colors default per A13 (question yellow, answers green) when rows omit them; `node_appearance` normalization owns validity (one color truth).

## 4. Data and State Handling

No new stores. The search result is request-scoped (never persisted beyond the delegation trace's existing bounds); proposals persist through the standard mirror/queue; the handback's `notesSkipped` is part of the delegation result text, not new state. Grants stay requested ∩ registry ∩ policy — `node.create` on the DFB manifest is a declaration; per-attachment policy can still withhold it, and the mint gate honors whatever was actually granted.

## 5. UI and UX Requirements

No new components: the note proposals render as the existing A16 jointly-pending review cards at the DFB chat (apply in any order); the DFB's reply prose states the answer (A13's "notes mirror the chat"). Refusals/skips surface in the parent's text with the way out named (A4). Accessibility unchanged — existing card surfaces only.

## 6. Edge Cases

1. `CURIO_SEARCH_URL` unconfigured: the child receives the honest error as `searchResults`, must answer "search is not configured" — never memory-invented findings (test-pinned).
2. No notes template installed/enlisted: answer lands, notes skipped, handback names the Researcher's attachment; nothing half-mints.
3. Parent lacks `node.create` (policy withheld): reply lands as text; the gate is named — never a silent drop.
4. Child replies prose or malformed rows: no mint; the delegation result stays text (schema-or-nothing, DEC-063).
5. Empty `notes` with an `answer`: valid — answer-only handback, zero proposals.
6. Oversized/many notes: A12 bounds cap rows; over-cap refuses naming the bound.
7. A second research question while the first sequence is pending: the later-run mint supersedes the whole earlier sequence (A16 semantics, already tested).
8. Injection: notes-shaped JSON in ordinary chat or tool results never reaches the mint (the delegation-result-only path, dev/41 posture).
9. The question note duplicates the answer note's color when the model sets both: user-supplied colors win rows; defaults only fill absences (A13).

## 7. Testing Strategy

Backend unit (enrichment matrix, reply parser, mint gate/skip/sequence), the DFB E2E fake-provider lane (delegate → schema reply → two jointly-pending cards → apply both → spec nodes with A13 colors), byte-pin + roster + prompt markers, injection resistance; regression: full agents+packages suites; the Researcher's own attachment suites unamended.

## 8. Acceptance Criteria

1. A research question in the DFB chat yields: prose answer + the reviewed question/answer note sequence, applying in any order onto the canvas.
2. Tool-less delegation throughout — the child never holds tools; the runtime's single policed search is the only egress.
3. Every degraded path (no search, no template, no grant, bad reply) lands honestly with the fix named; nothing silently drops or half-mints.
4. The DFB prompt pin updates once, deliberately, with the D4-precedent comment; all other manifests byte-identical.
5. Follow-up C's deferral is recorded in DEC-065 with re-open conditions; no `node.appearance.write` code ships.

## 9. Recommended Commit Breakdown

- Commit 1 — roster + enrichment + reply contract (builtin delegates_to/tools, `_enriched_delegate_inputs` fifth branch, `_NOTES_REPLY_CONTRACT`); unit tests.
- Commit 2 — `_mint_notes_from_delegate` + wiring into both run loops; mint/gate/skip/sequence/injection tests.
- Commit 3 — prompts (DFB paragraph + pin update; Researcher delegate posture) + the DFB E2E lane + marker tests.
- Commit 4 — docs: DEC-065 (D + C deferral), ledger BL-38, roster docs, memo flip.

## 10. Engineering Quality Checklist

- [ ] Fifth enrichment lives in the ONE seam; no parallel enrichment path.
- [ ] One template vocabulary (dev/93), one search adapter, one color truth — nothing re-implemented.
- [ ] Reply recognition is schema-only; injection resistance test-pinned.
- [ ] The mint is grant-gated on the PARENT and reuses `_store_proposal`'s A16 queue untouched.
- [ ] The byte-pin update is deliberate, commented, and singular.
- [ ] C's deferral is a recorded decision with re-open conditions.
