# Implementation Memo: P2 Runtime Maturation — Tranche 2: Tool Contracts + Structured Content

Date: 2026-07-27
Status: implemented 2026-07-28 (`BL-P2-20260728-07`, `DEC-043`; commits `65fec1c1`, `b087535e`, `896b09e7`, `204fa397`)
Feature slice: v2 runtime maturation, second tranche (`DEC-038`; the dev/37 tranche map)
Design sources: `DEC-006` (review-before-apply gates mutations), `DEC-017` ("imported manifests may reference only server-allowlisted typed tool IDs … manifest-supplied executable code is never run"), `ADR-AG-006` (typed event log as execution truth — direction, not fully realized here), `ADR-AG-007` (domain tools remain domain-owned; agent infrastructure wraps them as authorized typed tools), `REQ-PERM-001` (manifest declarations grant no permission), `REQ-REVIEW-001` (no mutation without explicit revision-safe review), `REQ-SEC-002`/`RISK-RENDER-001` (one centralized allowlist renderer, hostile-content tested), `RISK-SEC-001` (unsafe tool invocation → allowlists + review gates); `docs/08` (card anatomy, SUGGESTED PROMPTS, "actions are suggested prompts, not buttons"), `docs/03` §"Chat feedback visual system" (the canonical card/chip visual contract), `docs/11` + `docs/schemas/agent-package.v1.json` (`tools` manifest section) + `dev/05` blueprint (:247 tools field, :344 normalized event vocabulary, `SafeAgentContent`/`sanitizeAgentContent.ts` planned modules); memo `dev/37` (the T1 envelope this rides on), memos `dev/22`/`dev/19` (the deferred "chat structured-content cards + SUGGESTED PROMPTS — no fabricated content" item this closes)
New decision required: **`DEC-043`** (next free number) — the structured-content contract + tail protocol + tool-grant pipe below; to be added to the canonical dev/03 decision table and the 2.1 traceability ledger with this memo (the tranche currently has no DEC/REQ of its own — it inherits the sources above).

## 1. Position in the Maturation Program

The dev/37 tranche map, tranche 2 of 4: **"Tool contracts + structured content — typed tool/card events over the Tranche-1 envelope; unlocks the chat suggestion/preview/result cards, SUGGESTED PROMPTS, and review-before-apply mutations."**

"Unlocks", not "ships": the Dataset-Finder suggestions/preview cards and actual mutating tools belong to the P5 composite agents (demand-gated, `DEC-038`). This tranche delivers the *substrate they require* plus the one structured behavior that is generic to every agent today: **SUGGESTED PROMPTS**. Concretely:

1. **Typed content parts** on agent turns (persisted, versioned contracts) + the runtime protocol that produces them from a plain LLM completion.
2. **The typed SSE `content` event** + enriched `done`/blocking-run payloads over the T1 envelope.
3. **Tool contracts**: manifest `tools` parsing (untrusted declarations), a server-authoritative typed tool registry + grant resolution, granted tools pinned on the execution record, fail-closed handling of unsatisfiable requirements. No tool *execution* loop yet — the registry ships empty; the first real tool arrives with its first consumer (T2b/P5), which is when the review-before-apply application flow becomes implementable.
4. **Frontend**: safe markdown rendering for agent text, the generic card shell + result-card rendering, and the SUGGESTED PROMPTS chip row + prefilled primary prompt per the approved concept.

**LangChain check (the standing dev/37 question):** still not needed. The structured-tail protocol below is a prompt-and-parse pattern over the existing provider port; no agent executor, chain, or tool loop is involved. The decision point moves to T2b (first executing tool).

## 2. Problem Statement

Agent replies are opaque text. Consequences, each grounded in an approved design requirement:

- **No follow-ups**: `docs/08`/`docs/03` mandate that *"agent workflow actions are suggested prompts, not bespoke buttons"* — a primary prompt prefilled in the input plus a "SUGGESTED PROMPTS" chip row. The runtime cannot express them: a reply is one string, so the concept's central interaction pattern (and the `dev/22` deferred item) is unimplementable today.
- **No cards**: the transcript cannot carry the concept's inline suggestion/behavior/preview/result cards (`docs/08` drawer anatomy), so the P5 composites would have nothing to land on.
- **No tool story**: `DEC-017` says imported manifests may reference only server-allowlisted typed tool IDs, `REQ-PERM-001` says declarations grant no permission, and the canonical package schema defines the `tools` section ("typed, allowlisted tool requirements — not executable code or permission grants") — but the backend validator ignores the section entirely, nothing resolves grants, and the T1 execution pins can't record what a run was allowed to touch (`REQ-CAP-002` expects tools among the persisted execution pins).
- **Unsafe rendering posture**: `REQ-SEC-002` — *"agent/model/tool rich content is rendered only through a centralized allowlist sanitizer with active HTML, scripts, unsafe URL schemes, event handlers, and unapproved embeds disabled and tested"* — is specified (`RISK-RENDER-001`, dev/03:707, the blueprint's `SafeAgentContent`) and not implemented anywhere: the agent chat panel renders raw strings (inert but unformatted), the legacy `LLMChat` renders markdown with no centralized policy, and there is no shared safe renderer to point new content parts at.

## 3. Scope

**Included**

- Backend: typed content-part contracts + the structured-tail parser (`app/agents/content.py`); runtime integration in both run paths (strip → validate → persist parts on the agent turn, stream-withhold the tail); SSE `event: content` + `content` on the enriched `done` and the blocking response; manifest `tools` parsing; the tool registry + grant resolution (`app/agents/tools.py`); `pins.tools` on the execution record; required-tool fail-closed admission.
- Frontend: `AgentContentPart` types; a centralized safe markdown renderer used by the agent chat; the generic card shell (per the `docs/03` visual contract) with `result`-kind rendering; SUGGESTED PROMPTS chips + prefilled primary; stream/`done` content handling.
- Tests throughout (contract, runtime, SSE both-direction compatibility, rendering, chip behavior).

**Out of scope (explicitly deferred, with owners)**

- Tool *execution* (the agentic loop), any mutating tool, and the review-before-apply *application* flow — T2b/P5, with the first composite that needs them (`dev/15`).
- The suggestions/behavior/preview card *producers* (Dataset Finder lanes, quick-reply behavior chips) — P5 composites; this memo defines and renders the generic card contract they will emit.
- Server-supplied `inputs.reads` grounding for attachment chat (the dev/38 manifests declare e.g. `nodeContext`/`dataflowContext`, but attachment runs currently send only the conversation; feeding target context into `_prepare_run` is its own memo — it changes prompt composition and has privacy/size questions).
- Ledgers/pricing (T3), provider profiles/secret store (T4), leases/background execution.
- The legacy `LLMChat.tsx` surface (untouched; it is not the unified chat).

## 4. Design

### 4.1 Content parts — the typed contract (`contractVersion: 1`)

An agent turn gains an additive `content` key: an ordered list of typed parts. `text` remains exactly the *visible* reply text (backward compatibility: old clients and `context_messages` keep working unchanged; the transcript stays the single history).

```json
{"role": "agent", "text": "<visible text>", "ts": "...", "execution": {...},
 "content": [
   {"type": "suggestedPrompts", "primary": "Build the NOAA node and install it",
    "alternatives": ["Show me the fetch code first", "Use the Data Catalog copy instead"]},
   {"type": "card", "kind": "result", "title": "Created dataset node",
    "lines": ["noaa_stations.parquet → DATA palette", "Provenance: agent-created"]}
 ]}
```

Part types in v1 (all others are dropped at validation):

| Part | Shape | Bounds | Producer today |
|---|---|---|---|
| `suggestedPrompts` | `{primary: str, alternatives: [str]}` | primary + each alternative ≤ 200 chars; ≤ 3 alternatives; ≤ 1 such part per turn | any agent, via the tail protocol |
| `card` | `{kind: str, title: str, lines: [str]}` | title ≤ 120; ≤ 10 lines ≤ 300 chars; ≤ 4 cards per turn | contract + renderer only; producers arrive with P5 (`result` renders now; unknown kinds render as the generic shell) |

Rules: parts carry **no actions** (the concept's cards are informational; actions are suggested prompts); parts are plain data — no markup interpreted inside card fields (rendered as text); the whole `content` list ≤ 8 parts. The contract is versioned by the tail fence tag (below), so v2 parts can coexist later.

### 4.2 Producing parts — the structured tail protocol

No provider "function calling" and no framework: the runtime appends one bounded, runtime-owned instruction to the system turn (after the preamble + intent composition, dev/38) telling the model it MAY end its reply with a single fenced block:

````text
```curio.v1
{"suggestedPrompts": {"primary": "...", "alternatives": ["...", "..."]}}
```
````

- The server strips the block from the reply, validates it against §4.1 (JSON, bounds, known types), and attaches the resulting parts to the turn. The remaining text is the visible reply (`turn.text`, `done.reply`).
- **Fail-open to text**: a malformed/oversized/unknown block is *not* stripped — it stays visible exactly as the model wrote it, and no parts attach. Nothing the model says is ever silently discarded; a bad block is visibly bad rather than invisibly lost.
- Only a block that terminates the reply (trailing whitespace allowed) counts; fenced blocks mid-reply (e.g. the model quoting the syntax) are body text.
- The tail instruction is appended for every attachment run (all current attachments are foreground/report-only chat surfaces). It is phrased as optional ("when a follow-up would help…"), costs a few hundred prompt tokens, and JSON-contract agents (the planners, whose entire reply is already machine JSON for legacy consumers) simply won't use it — their replies parse as before (edge case §6).
- Provider context on later turns uses `turn.text` (the visible reply) — the tail block is not replayed into context, so the protocol adds no compounding token cost.

### 4.3 Streaming: withholding the tail

The tail must not flash into the live transcript and then vanish. `stream_attachment`'s generator gains a small state machine over the delta stream:

- Deltas pass through normally, except the generator always retains the longest trailing suffix that could be a prefix of the fence marker (`` ```curio.v1 ``, ≤ ~16 chars held back at any moment — imperceptible).
- Once the marker is confirmed, subsequent deltas are withheld (accumulated silently). If non-whitespace content arrives *after* a closing fence, the suspicion was wrong (mid-reply block): the withheld text is flushed as ordinary deltas and passthrough resumes.
- At stream end the withheld block is parsed: valid → `event: content` (the parts) is emitted before `done`, whose `reply` excludes the block; invalid → the withheld text is flushed as a final `delta` first (fail-open parity with §4.2).

SSE envelope after this memo (additive over T1; old clients skip unknown events — already regression-tested in both directions):

```text
event: execution  {executionId}
event: delta      {text} …
event: content    {parts: [...]}          (only when parts exist)
event: done       {reply, executionId, usage, content}
```

The blocking `run` response likewise gains `content` (list, possibly empty). Persistence stays completion-time and identical across both paths.

### 4.4 Tool contracts (substrate, no execution)

- **Manifest**: parse the canonical schema's optional `tools` section — `[{id, required?}]`, ids validated against the capability-id grammar (dotted lowercase), duplicates rejected. Declarations are untrusted requirements, never grants (`DEC-017`, `REQ-PERM-001`; blueprint :247 — "allowlisted tool ID … never executable source").
- **Registry** (`app/agents/tools.py`): `ToolContract {id, contract_version, effect: "read"|"mutate", description}` — server-owned, typed, versioned. Per `ADR-AG-007`, contracts *name domain operations* — the implementations stay in their domains; the registry only wraps them as authorized typed references. **v1 ships empty** — deliberately: no current agent executes tools, and inventing one without a consumer would be dead code with a security surface (`RISK-SEC-001`). The registry, grammar, and grant pipe are what T2b/P5 need to exist first.
- **Grant resolution** (in `_prepare_run`): `granted = requested ∩ registry ∩ policy`, where v1 policy grants `read`-effect tools only — a `mutate` tool can never be granted until the `REQ-REVIEW-001`/`DEC-006` review-before-apply flow exists, fail-closed by construction. Granted ids are pinned on the execution record: `pins.tools: []` (additive key; T1 records simply lack it — this is the tools half of `REQ-CAP-002`'s execution pins).
- **Fail-closed requirement**: a manifest tool with `required: true` that resolves no grant → the run is refused with a 422 naming the tool (same posture as a missing instruction prompt). Optional tools resolve to "not granted" silently.
- Settings/Resource screens: no change yet (the Resources screen already says tools/network arrive with provider profiles; an empty grant list adds nothing to show).
- **Relation to the normalized event vocabulary** (`ADR-AG-006`, dev/03:344 — `tool_requested`/`tool_started`/`tool_result`/`review_required`/`mutation_applied`…): those events describe an *executing* tool loop and stay with T2b/leases. This tranche's `content` event extends the dev/22 SSE envelope the same additive way `execution` did in T1; nothing here conflicts with adopting the full vocabulary later.

### 4.5 Frontend

- **Types**: `AgentContentPart` union (`suggestedPrompts` | `card` | forward-tolerant unknown), `content?: AgentContentPart[]` on `AgentSessionTurn`; `runAttachmentStream` resolves `{reply, executionId, usage, content}`; the provider stores parts on the finalized turn (hydration gets them from the persisted session automatically).
- **Safe renderer** — the blueprint's planned modules, by their planned names (`dev/05`:499/:994): `sanitizeAgentContent.ts` (the policy: allowlisted URL schemes `http(s)`/`mailto`, everything else neutralized) + `SafeAgentContent` (the **only** renderer for agent rich content, `REQ-SEC-002`), built over the existing `react-markdown` dependency — raw HTML disabled (react-markdown's default: HTML is escaped, never parsed; no `rehype-raw`), `urlTransform` = the sanitizer policy, code blocks rendered as plain `<pre>`. Agent turn text switches from the raw string to this renderer; user bubbles stay plain text. Card fields intentionally do *not* pass through markdown (cards are plain text by contract).
- **Cards**: a `ChatCard` component implementing the `docs/03` visual contract (single `#f7f7f8` surface, `#ececee` hairline, 12px radius, leading accent dot in the agent's category tint, white raised inner panel for `lines`). `kind: "result"` gets its labeled treatment; unknown kinds render the same generic shell (title + lines) so future P5 kinds degrade gracefully on old clients.
- **SUGGESTED PROMPTS**: rendered from the *latest* agent turn's part only (stale follow-ups from earlier turns are noise): a labeled chip row above the input (soft-token treatment per `docs/03`), and the **primary prompt prefilled into the input** — editable, send button active — per `docs/08`. Clicking a chip replaces the input draft. Typing, sending, cycling to another attachment, or a new turn arriving clears/replaces the prefill. Prefill never overwrites a non-empty draft the user has already typed (explicit rule: user text wins).

## 5. Data and State Handling

- Source of truth: unchanged — the session file owns turns; parts ride the agent turn (same lifecycle, GC, share-exclusion via sidecar placement + `strip_agent_state`; the rule-9 share suite already guards the spec surface).
- `turn.text` stays the visible reply and the only thing `context_messages` reads — provider context is byte-identical for turns without parts, and excludes the tail for turns with them (no compounding cost, no contamination).
- No migrations: turns/manifests without the new keys read as "no parts"/"no tools"; T1 execution records without `pins.tools` read as "none granted".
- The chip row derives from the last agent turn at render time — no separate suggestion state to drift; clearing the conversation clears it by construction.
- Grants are resolved per-run at dispatch (no stored grant state); the execution pin is the only record, consistent with DEC-031's "pin what actually ran".

## 6. Edge Cases

- Model emits no tail block (the common case): no `content` event, `content: []`/absent, chip row absent — exactly today's behavior.
- Malformed tail (bad JSON, over bounds, unknown type): block stays visible in the reply; no parts (fail-open, §4.2); streaming flushes the withheld text.
- Fenced `curio.v1` block mid-reply (model explains the syntax): body text — only a terminal block parses; the stream state machine flushes on post-fence content.
- Legacy JSON-contract agents (planners/suggesters whose whole reply is machine JSON): reply contains no tail fence → passes through untouched; their legacy consumers parse as before.
- Marker split across delta boundaries: the retained-suffix buffer spans deltas by construction; a stream that *ends* mid-marker flushes the suffix.
- Stream disconnect mid-withhold: completion-time persistence means no turn is written (T1 rule) — nothing partial persists.
- Empty `alternatives` with a valid `primary`: legal (prefill only, no chip row). Duplicate alternatives are de-duplicated at validation.
- A turn with parts but empty visible text (model answered only in the block): the reply falls back to rendering the parts alone; `text` may be `""` and the transcript shows the card/chips without an empty bubble.
- Old server + new client / new server + old client: additive fields and skipped unknown SSE events on both sides (tested both directions, extending the T1 suites).
- Manifest with `tools: [{id: "x.y", required: true}]` uploaded today: import/install succeed (declarations are legal); the run is a 422 naming the ungranted tool — fail-closed, visible, honest.
- Intent-edited attachments: the tail instruction is runtime-owned and composes *after* the preamble+intent, so an edited intent cannot strip or spoof it; a user typing a fake fence in their message affects nothing (only the agent reply is parsed).

## 7. Testing Strategy

Backend — `test_content.py` (new): tail extraction (terminal-only, whitespace tolerance, mid-reply ignored), validation bounds (lengths, counts, unknown types dropped, de-dup), fail-open verbatim retention. Runtime (`test_routes.py`): run + stream persist `content` on the agent turn; blocking response and `done` carry it; `event: content` ordering (after deltas, before `done`); stream-withhold — marker split across deltas, false-positive flush, invalid-tail flush; legacy-JSON reply passthrough; context regression (tail never re-enters provider context; part-less turns byte-identical). Tools (`test_manifest.py`, `test_tools.py`, `test_routes.py`): `tools` parsing (grammar, duplicates, required flag), grant resolution (empty registry ⇒ no grants; mutate never grantable), `pins.tools` on the execution record, required-tool 422 before admission (no quota consumed). Share regression: the rule-9 suite re-run (parts live in the sidecar, not the spec).
Frontend: safe-renderer **hostile-content fixtures** (`RISK-RENDER-001`'s mitigation is explicitly "hostile-content component tests"): raw `<script>`/`<img onerror>`/HTML escaped inert, `javascript:`/`data:` links neutralized, event-handler attributes never reach the DOM, ordinary markdown/code fences render; card shell + result kind + unknown-kind fallback; chip row renders from the latest agent turn only; primary prefills, chip click replaces draft, user draft wins, send/cycle clears; stream `content` event tolerance and finalized-turn storage; all existing suites green.

## 8. Acceptance Criteria

- [x] An agent reply ending in a valid `curio.v1` tail persists typed parts on its turn, streams as `event: content` + enriched `done`, and never shows the raw block in the transcript; an invalid tail stays visible verbatim and attaches nothing.
- [x] SUGGESTED PROMPTS render per the approved concept: chip row above the input from the latest agent turn, primary prompt prefilled and editable with send active, user-typed drafts never overwritten; no agent-rendered action buttons anywhere.
- [x] Agent text renders only through `SafeAgentContent` (`REQ-SEC-002`): markdown works, hostile HTML/scripts/unsafe URL schemes are inert under component tests; cards render the `docs/03` visual contract with unknown kinds degrading to the generic shell.
- [x] Manifest `tools` declarations parse per the canonical schema and `DEC-017`; grants resolve server-side (empty registry ⇒ none; `mutate` ungrantable, `DEC-006`); granted tools are pinned on the execution record; a required-but-ungranted tool refuses the run with a 422 that consumes no quota.
- [x] Old sessions/clients/servers interoperate unchanged (additive keys, skipped events — tested both directions); provider context for part-less turns is byte-identical to before.
- [x] LangChain remains uninstalled; no new dependencies (react-markdown/dompurify already present).

## 9. Recommended Commit Breakdown

1. `feat(agents): typed content-part contracts + structured-tail parser (app/agents/content.py), with tests`.
2. `feat(agents): runtime structured content — tail instruction, strip/persist on both run paths, SSE content event + enriched done, stream withholding, with tests`.
3. `feat(agents): tool contracts — manifest tools parsing, registry + grant resolution, pins.tools, required-tool fail-closed, with tests`.
4. `feat(agents): frontend — safe renderer, chat cards, SUGGESTED PROMPTS chips + prefill, stream/type additions, with tests`.
5. Docs + ledgers: build-log entry `BL-P2-2026…-07`; register **`DEC-043`** in the canonical dev/03 decision table and the 2.1 traceability ledger (the DEC-040/041/042 pattern); update the build-log P2 phase row and the "Chat structured-content cards + SUGGESTED PROMPTS" deferred item (3.1:65 → closed); `docs/AGENTS.md`; memo status flip.

## 10. Engineering Quality Checklist

- Additive everywhere: turn `content`, SSE `content` event, response fields, manifest `tools`, `pins.tools` — zero migrations, old data and old clients read clean.
- Fail-open for model content (a bad block is visible, never silently dropped); fail-closed for capability (required tools, mutate effects) — each failure mode matches what it protects.
- One parser/validator (`content.py`), one renderer (`AgentMarkdown`), one card shell — no per-agent forks of any of them; the tail instruction lives in one runtime constant.
- The transcript remains the single history (memo 12): parts ride turns; no parallel content store; chips derive from the transcript.
- Cards carry no actions and no interpreted markup; the concept's "suggested prompts, not buttons" invariant is structural, not stylistic.
- Bounds enforced server-side at validation, not trusted from the model; all limits named in one place with the contract.
