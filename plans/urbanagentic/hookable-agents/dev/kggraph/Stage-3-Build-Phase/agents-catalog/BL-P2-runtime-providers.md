# Build Log — P2: Runtime & Providers

Child log for Phase 2 (see `../3.1-Agents-Catalog-Build-Log.md`). Entries follow the
Build Entry Template and are append-only.

> **Backfill note.** `BL-P2-20260719-01` was written retroactively right after its
> commit, when the per-change build-log discipline was restored. Only the aiconn
> default landed so far; the provider adapter / LangChain runtime slice is still to come.

---

## BL-P2-20260719-01: Default LLM provider = aiconn sage200

- Date / author: 2026-07-19 / Karla
- Status: verified
- Requirements: `REQ-PROVIDER-002` (default provider/model/API/runtime seeded from `aiconn/`)
- Design decisions/artifacts: **`DEC-039`** (aiconn as the single default source), `ADR-AG-012` (provider-credential migration — encrypted store deferred to 2b); `SRC-AICONN`
- Tasks: `TASK-P2-default-provider`
- Risks/questions: `RISK-SECRET-001` (plaintext `user.llm_api_key` column retained for now; hardening deferred to 2b), `RISK-EGRESS-001` (remote default endpoint)
- Design-to-code decision or deviation: implemented **only** the aiconn default — **no DB migration** (scope split from `ADR-AG-012`'s encrypted store). Reused the existing `_resolve_llm_config` + `GUEST_LLM_*` env pattern rather than a parallel default. A configured user keeps their exact config (no default base-url contamination). Behavior change: an unconfigured authenticated user now defaults to sage200 instead of the old "No LLM configured" abort.
- Files/modules changed:
  - `utk_curio/backend/config.py` (`DEFAULT_LLM_{API_TYPE,BASE_URL,MODEL,API_KEY}`; `GUEST_LLM_*` inherit them)
  - `utk_curio/backend/app/api/routes.py` (`_resolve_llm_config` default fallback)
  - `docs/AGENTS.md` (§4 default provider + operator env-var table)
- Tests added/updated: `TEST-P2-default-provider` = `utk_curio/backend/tests/test_llm_default_provider.py` (7 tests)
- Verification evidence: `pytest test_llm_default_provider.py` → 7 passed. Config defaults (aiconn) asserted; guest inheritance; every resolver branch (unconfigured→default, configured-kept, guest, guest-no-key→400).
- Commit/PR: `COMMIT-64a680d`
- Issues/regressions discovered: an unconfigured user with no `AICONN_API_KEY` set will now 401 at the provider rather than see the friendly "configure your LLM" message — intended default-source behavior.
- Resolution: documented in `docs/AGENTS.md` §4 and the commit body; operators/users can override via env or LLM Settings.
- Follow-up work: **2b** encrypted secret store (deferred; can be an encrypted FS file per `DEC-040`); the LangChain runtime adapter (Feature 4) will consume this same default profile.
- Remaining risks/questions: `RISK-SECRET-001` — plaintext key column remains until 2b.

---

## BL-P2-20260719-02: Extract provider adapter into `app/agents/providers.py`

- Date / author: 2026-07-19 / Karla
- Status: verified
- Requirements: `REQ-MODULE` (LLM/provider behavior owned by `agents/`, not routes/flow/node — `dev/04`), `REQ-RUNTIME` (provider-neutral execution boundary)
- Design decisions/artifacts: `SRC-MEMO-MODULE` (`dev/04`); `SRC-BLUEPRINT-005` (provider port / `LangChainModelBridge` seam)
- Tasks: `TASK-P2-provider-adapter`
- Risks/questions: `RISK-ARCH-001` / `RISK-ARCH-002` (LangChain/provider details leaking into UI/routes); `RISK-SECRET-001` (key handling unchanged)
- Design-to-code decision or deviation: **behavior-preserving refactor.** Move the `_call_llm` provider dispatch (openai_compatible / anthropic / gemini) out of `app/api/routes.py` into a provider-neutral port `run_chat_completion(ProviderConfig, messages)` in `app/agents/providers.py`. `_resolve_llm_config` keeps its request-layer role (reads `g.user`) and now builds a `ProviderConfig`. **LangChain is deliberately NOT added** — it is not currently a dependency and is not required for the port; adding it is a heavy dependency decision surfaced to the user, and a LangChain adapter can later sit behind this same port.
- Files/modules changed:
  - `utk_curio/backend/app/agents/providers.py` (new — `ProviderConfig` + `run_chat_completion` port; the 3 backends moved verbatim)
  - `utk_curio/backend/app/api/routes.py` (`_call_llm` now a thin wrapper over the port; no raw provider SDK usage remains)
  - `docs/AGENTS.md` (§4 note on the provider-neutral port)
- Tests added/updated: `TEST-P2-providers` = `utk_curio/backend/tests/test_agents/test_providers.py` (6 tests)
- Verification evidence: `pytest test_agents/ test_llm_default_provider.py` → 59 passed. `import utk_curio.backend.app.api.routes` OK; grep confirms no `openai`/`anthropic`/`google.generativeai` usage left in `routes.py` (dev/04 boundary satisfied for this path).
- Commit/PR: `COMMIT-6cc42f0`
- Issues/regressions discovered: none (behavior-preserving; existing `_resolve_llm_config` tuple contract and its 7 tests unchanged).
- Resolution: n/a
- Follow-up work: optional LangChain adapter behind the port (dependency decision — surfaced to the user, not taken); tool/event/lease/admission + SSE-runtime slices remain for later P2 entries.
- Remaining risks/questions: whether to adopt LangChain at all vs keep direct provider SDKs behind the port.

---

## BL-P2-20260722-03: Provider-config resolution moved into `agents/` (`ADR-AG-012` v1 step)

- Date / author: 2026-07-22 / Karla
- Status: verified
- Requirements: `REQ-MODULE` (agents/ ownership boundary), `REQ-PROVIDER-002` (aiconn default seed, `DEC-039`)
- Design decisions/artifacts: `ADR-AG-012` (memo `17` §3.3), `SRC-AICONN`, memo `dev/22` slice 1
- Tasks: `TASK-P2-provider-config`
- Risks/questions: `RISK-SECRET-001` context — storage unchanged (`user.llm_*`/guest env); the `ProviderProfile` + encrypted secret store remain the flagged v2 remainder
- Design-to-code decision or deviation: behavior-preserving move of `app/api/routes.py::_resolve_llm_config` → `app/agents/provider_config.py::resolve_provider_config(user) -> ProviderConfig` (guest key handling, aiconn default via `config.DEFAULT_LLM_*`, configured passthrough). The agents run route resolves directly; the legacy `/llm/*` handlers keep their exact contract through a thin tuple shim over the moved resolver — the bridge direction `ADR-AG-012` prescribes. `app/agents` no longer imports `app/api` (boundary-tested).
- Files/modules changed: `app/agents/provider_config.py` (new), `app/agents/routes.py`, `app/api/routes.py`
- Tests added/updated: `test_provider_config.py` (5 incl. the import-boundary guard); `test_llm_default_provider.py` repointed at the moved module while still exercising the legacy shim (proves the bridge)
- Verification evidence: `pytest tests --ignore=tests/test_frontend` → 669 passed
- Commit/PR: `COMMIT-1cd6359`, `COMMIT-9dd5718` (legacy-test repoint)

---

## BL-P2-20260722-04: SSE streaming runtime (provider port + run/stream route + chat client)

- Date / author: 2026-07-22 / Karla
- Status: verified
- Requirements: `REQ-RUNTIME`, `REQ-CHAT` (streaming behavior per memo `12`/`docs/08`)
- Design decisions/artifacts: memo `dev/22` slices 2/3/5; reuse of the dev/19 intent + dev/20 session semantics via shared `_prepare_run`/`_persist_exchange`
- Tasks: `TASK-P2-sse`
- Risks/questions: `RISK-STATE-001` (persistence parity) — mitigated: one shared message-builder and persist helper for run + stream
- Design-to-code decision or deviation: `providers.stream_chat_completion` yields reply deltas per backend (openai-compatible `stream=True`, anthropic `messages.stream`, gemini `stream=True`); `services.stream_attachment` validates eagerly (404/422 are plain JSON before streaming) and yields `delta…`/`done` or `error`, persisting the full exchange once at completion — a failure persists the user turn + display-only marker, never the partial. Route emits `text/event-stream`. Frontend: `agentsApi.runAttachmentStream` (raw `fetch` + SSE frame parser — POST rules out `EventSource`); the provider grows a live agent turn per delta, finalizes on `done`, and falls back to the blocking `run` once on a pre-delta non-HTTP failure. The blocking `run` contract is unchanged.
- Files/modules changed: `app/agents/{providers.py,services.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/attach/AgentAttachmentsProvider.tsx`
- Tests added/updated: `test_providers.py` (+3 streaming), `TestStreamRun` in `test_routes.py` (4: deltas→done+persist-once, mid-stream error marker, plain-JSON validation, prior-session context); frontend parser tests (3) + provider streaming tests (4)
- Verification evidence: backend 669 passed; `npx jest` full → 514 passed (50 suites); `tsc --noEmit` clean.
- Commit/PR: `COMMIT-828e3d2` (port), `COMMIT-73f828a` (route/service), `COMMIT-7a06e20` (chat client)
- Follow-up work: chat structured-content cards + SUGGESTED PROMPTS chips are now unblocked (separate slice).

---

## BL-P2-20260722-05: Basic quota admission (simple FS counters)

- Date / author: 2026-07-22 / Karla
- Status: verified
- Requirements: `REQ-QUOTA-001` (v1 subset per `DEC-038`: simple counters, stable denial — not reservation ledgers)
- Design decisions/artifacts: `DEC-038` (v1 cut), `DEC-040` (FS-backed); memo `dev/22` slice 4
- Tasks: `TASK-P2-quota`
- Risks/questions: advisory counters may over-admit by one under races — explicitly accepted at v1 and documented in-module; ledgers are v2. Final limits are settings-screen/product tuning.
- Design-to-code decision or deviation: `app/agents/quotas.py` — per-account daily counters in `.curio/users/<key>/agents/quota.json`; `check_and_count` runs after request validation (invalid requests never consume quota) and before provider dispatch (a denied run never reaches a provider), on both run paths. Exhaustion raises `QuotaExceeded` → stable `429` `{error, quota, resetAt}`; nothing persists on denial. Limit via `CURIO_AGENT_RUNS_PER_DAY` (fail-closed default 200/day); corrupt/stale windows read as fresh. **Legacy `/llm/chat` stays un-gated** (explicit product call in this slice's approval).
- Files/modules changed: `app/agents/{quotas.py (new),services.py,routes.py}`
- Tests added/updated: `test_quotas.py` (6 pure) + `TestQuotaAdmission` in `test_routes.py` (3: 429 after limit + nothing persisted, plain-429 on the stream path, invalid request consumes no quota)
- Verification evidence: backend 669 passed. Frontend renders the denial as a soft error turn with the reset time (provider test).
- Commit/PR: `COMMIT-da9b43f`
- Follow-up work: per-scope quota editing arrives with the Cost/Quotas/Resource settings screens.

---

## BL-P2-20260727-06: Runtime maturation T1 — execution records, usage capture, typed event envelope

- Date / author: 2026-07-27 / Karla
- Status: verified
- Requirements: `DEC-031` (per-execution reproducibility pins — the previously unimplemented half), `DEC-038` (v2 maturation program, tranche 1), memo `11` (Estimated vs **Actual** labeling), memo `12`/`docs/08` (the transcript IS the run history)
- Design decisions/artifacts: memo `dev/37` (approved tranche-1 spec; tranches 2–4 = tool contracts/cards, ledgers+pricing, provider expansion)
- Tasks: `TASK-P2-execution-records`
- Risks/questions: `RISK-COST-001` context — counters remain advisory (racing writers may briefly under-count usage); T3's atomic reservations/ledgers replace, not patch, them. Title-call usage is counted but recordless, so counters and transcript may deliberately disagree by that small amount.
- Design-to-code decision or deviation: **(1) Usage capture in the port** — `run_chat_completion`/`stream_chat_completion` gain an optional `usage_out: dict` sink (mutated in place; a streaming generator can't return a value mid-protocol): openai `stream_options={"include_usage": true}` / `completion.usage`, anthropic response/`get_final_message()` usage, gemini `usage_metadata`; populated only when the provider reports both counts — Actual or absent, never estimated. **(2) Execution records on the agent turn** — `sessions.make_turn` gains an additive `execution` key; `_prepare_run` (now taking the resolved `ProviderConfig`) builds the DEC-031 pins in one place: coord, manifest prompt digest (null tolerated — built-in roster manifests are unstamped), `intentEdited`, provider/model (no secrets), and the flat effective-policy snapshot from `_run_policy`. Both run paths persist `{executionId, pins, usage, durationMs, status}` on the agent turn — error turns carry `status: "error"`; the blocking response gains `executionId`+`usage`; the dev/25 title call writes no record. **(3) Counters + envelope** — the quota window gains `usage` counters (`record_usage`/`usage_today`, folded in post-run incl. the title call); `GET /settings` and the project-defaults GET expose `usageToday`; the SSE stream opens with `event: execution` `{executionId}` before the first delta and `done` is enriched to `{reply, executionId, usage}` (old clients skip unknown events — verified in both directions). **(4) Frontend** — the stream client parses the new events and resolves `{reply, executionId, usage}`; the attachments provider stores the execution on the finalized turn; the Quotas screen shows `N runs · X in / Y out tokens today (actual)`; the Cost screen's Actual line names tokens as available and USD as pending the T3 price table. LangChain remains uninstalled; zero new dependencies; zero migrations (old turns/windows read clean; provider context byte-identical — regression-tested).
- Files/modules changed: `app/agents/{providers.py,sessions.py,services.py,quotas.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/attach/AgentAttachmentsProvider.tsx`, `components/agents/settings/AgentSettingsModal.tsx`; `docs/AGENTS.md`
- Tests added/updated: `test_providers.py` (usage_out per backend incl. the include_usage chunk), `test_sessions.py` (execution kwarg + context-ignores-execution regression), `TestExecutionRecords` in `test_routes.py` (10: pins/usage persisted, usage-null, error status, intent pin, stream record + envelope correlation, stream error, recordless title call, counters incl. title call, settings exposure, uploaded-digest pin), `TestUsageCounters` in `test_quotas.py` (5), stream-envelope updates in `TestStreamRun`; frontend: parser (execution/enriched-done/unknown-event tolerance), provider finalized-turn execution (2), settings screens actual-usage rendering (2 + legacy-payload zeros)
- Verification evidence: backend `pytest tests --ignore=tests/test_frontend` → 768 passed; frontend `npx jest` full → 555 passed (53 suites)
- Commit/PR: `COMMIT-f6b2696b` (port usage capture), `COMMIT-d2fe8457` (execution records), `COMMIT-8d62932a` (counters + SSE), `COMMIT-ab1cf29f` (frontend)
- Follow-up work: T2 tool contracts + structured content (cards/SUGGESTED PROMPTS ride the typed envelope); T3 ledgers + price table (true Actual USD from these token counts); T4 provider profiles + secret store. LangChain decision stays deferred until T2 shows a concrete need.

---

## BL-P2-20260728-07: Runtime maturation T2 — tool contracts + structured content (DEC-043)

- Date / author: 2026-07-28 / Karla
- Status: verified
- Requirements: `REQ-SEC-002` (centralized allowlist renderer — first implementation), `REQ-PERM-001` (declarations grant nothing), `REQ-REVIEW-001` (no ungated mutation — mutate-effect ungrantable), `REQ-CAP-002` (tools among execution pins)
- Design decisions/artifacts: **`DEC-043`** (registered with this entry in the dev/03 table + 2.1 ledger), `DEC-017` (allowlisted typed tool ids), `DEC-006` (review-before-apply), `ADR-AG-007` (domain-owned tools), memo `dev/39` (approved tranche-2 spec over the dev/37 T1 envelope)
- Tasks: `TASK-P2-structured-content`, `TASK-P2-tool-contracts`
- Risks/questions: `RISK-RENDER-001` — mitigated (one renderer, hostile-content component tests); `RISK-SEC-001` — the tool registry deliberately ships **empty** (a contract without a consumer is a security surface with no benefit; the first entry lands with T2b/P5). LangChain remains uninstalled — the tail protocol is prompt-and-parse over the provider port; the adoption decision moves to the first *executing* tool.
- Design-to-code decision or deviation: **(1) Content contracts** (`app/agents/content.py`) — the terminal `curio.v1` fenced-tail protocol: `split_tail` (terminal-only detection; mid-reply blocks are body text), bounded v1 parts (`suggestedPrompts` ≤200-char prompts/≤3 deduped alternatives; `card` kind/title/lines bounds, ≤4 cards, ≤8 parts, ≤4 KB block), `extract_content` fail-open (a malformed block stays visible verbatim), and the runtime-owned `TAIL_INSTRUCTION` (invites suggestedPrompts only — no card producer exists, so nothing prompts fabrication). **(2) Runtime** — the instruction composes after preamble+intent (an edited intent can't strip or spoof it); both run paths persist `turn.content` (additive) with the visible text as `turn.text`, so provider context never replays the tail; the blocking response and `done` gain `content`; `event: content` precedes `done`; the stream generator withholds a candidate tail (fence marker split across deltas handled via a longest-prefix hold-back), flushes false positives (closed block + subsequent prose) and invalid terminal tails as ordinary deltas; legacy machine-JSON planner replies pass through byte-identical. **(3) Tool contracts** — manifest `tools` now enforce the capability-id grammar + duplicate rejection; `app/agents/tools.py` owns the typed registry (empty) and `resolve_grants` (requested ∩ registry ∩ policy; read-effect only); grants pinned as `pins.tools`; a required-but-ungranted tool → 422 at validation, before admission (no quota, nothing persisted). **(4) Frontend** — `sanitizeAgentContent.ts` + `SafeAgentContent` (react-markdown, no rehype-raw, http(s)/mailto-only URL policy, noopener links) are the blueprint's planned modules by name; agent text renders only through them; `AgentChatCard` implements the docs/03 visual contract (plain data, no actions, unknown kinds → generic shell); SUGGESTED PROMPTS per docs/08 — primary prefilled/editable (user drafts always win), alternatives as chips, stale once the user replies; jest transforms the ESM markdown chain via inline babel presets (the package-scoped `.babelrc` never reaches `node_modules`).
- Files/modules changed: `app/agents/{content.py (new),tools.py (new),manifest.py,services.py,sessions.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/content/{sanitizeAgentContent.ts,SafeAgentContent.tsx,AgentChatCard.tsx,AgentChatCard.module.css}` (new), `components/agents/attach/{AgentChatPanel.tsx,AgentChatPanel.module.css,AgentAttachmentsProvider.tsx}`, `package.json` (jest config); `docs/AGENTS.md`
- Tests added/updated: `test_content.py` (26: terminal-only splitting, bounds, dedup, fail-open), `TestStructuredContent` in `test_routes.py` (7: strip/persist both paths, context regression, withhold/false-positive/invalid-flush/partial-marker, legacy passthrough), `test_tools.py` (9) + `TestToolRequirements` in `test_manifest.py` (4) + `TestToolGrants` in `test_routes.py` (3: 422-before-admission consuming no quota, optional-ungranted, granted-and-pinned); frontend `SafeAgentContent.test.tsx` (13 incl. hostile fixtures), panel structured-content suite (7: markdown, cards, prefill/chips/stale/user-draft-wins), stream-parser content events (2), provider finalized-turn parts (1)
- Verification evidence: backend `pytest tests --ignore=tests/test_frontend` → 818 passed; frontend `npx jest` full → 578 passed (54 suites)
- Commit/PR: `COMMIT-65fec1c1` (contracts), `COMMIT-b087535e` (runtime), `COMMIT-896b09e7` (tools), `COMMIT-204fa397` (frontend)
- Issues/regressions discovered: pre-existing system-turn parity tests updated for the appended tail instruction (expected; asserted exactly).
- Follow-up work: **T2b** — the first executing tool + the review-before-apply application flow + the `tool_requested`/`tool_result`/`review_required` event vocabulary (with the P5 composite that needs them); card *producers* (suggestions/behavior/preview) with the Dataset Finder (P5); T3 ledgers + pricing; T4 provider profiles + secret store; `inputs.reads` grounding for attachment chat (own memo).
- Remaining risks/questions: prompt-token cost of the tail instruction (~150 tokens/run) accepted; whether smaller models reliably emit valid tails is observational — fail-open means the cost of failure is cosmetic only.

---

## BL-P2-20260728-08: Runtime maturation T2b — executing tools + review-before-apply (DEC-045)

- Date / author: 2026-07-28 / Karla
- Status: verified
- Requirements: `REQ-REVIEW-001` (no mutation without an explicit revision-safe review action — first implementation), `REQ-PERM-001` (declarations grant nothing), `REQ-SEC-002` (tool output/proposed content rendered inert), `REQ-CAP-002` (execution pins now cover executed tools)
- Design decisions/artifacts: **`DEC-045`** (registered with this entry: the bounded tool loop + digest-pinned proposal/apply flow + **the LangChain disposition** — `DEC-007`'s adapter adoption is explicitly deferred to P5 multi-agent delegation; the runtime stays the direct provider-port implementation, recorded per tracking rule 10), `DEC-006`, `DEC-017`, `ADR-AG-006`/dev/03:344 (event names adopted verbatim: `tool_requested`/`tool_started`/`tool_result`/`review_required`; `mutation_applied` is the apply response + result-card turn), `ADR-AG-007` (domain-owned implementations), memo `dev/41`
- Tasks: `TASK-P2-tool-loop`, `TASK-P2-review-apply`
- Risks/questions: `RISK-SEC-001` — mitigated structurally: read tools execute only inside the bounded loop (≤2 rounds, 32 KB result bound, results are framed untrusted data that cannot request tools), mutations only inside the authenticated apply endpoint; no flag exists whose flip would let the model mutate. Prompt-injection amplification bounded by the round cap; the injection-resistance property (no model/tool/user TEXT can trigger an apply) is tested by name.
- Design-to-code decision or deviation: **(1) Tail contract** — model-emitted `toolRequest` part (capability grammar, ≤1 KB params, exclusive per reply); model-authored `proposal` keys invalidate the block (the review flow cannot be spoofed from the tail); `tail_instruction(grants)` enumerates server-resolved grants, byte-identical to T2 for grant-less runs (regression-pinned). **(2) Loop** — both run paths become parse → execute → re-prompt (`MAX_TOOL_ROUNDS = 2`); granted reads execute via `tools.execute_read_tool`; results feed back as framed user-role context; execution records gain `toolCalls` + usage **summed** across rounds; round text folds into one persisted turn (the transcript stays the run history; tool detail lives on the execution record). **(3) Contracts with named consumers** — `dataflow.read` (saved spec through `strip_agent_state` — rule-9 posture extends to tool output), `node.read` (defaults to the attached node), `node.content.write` (mutate): declared in the roster by Debug, Dataflow Explainer, Workflow Suggester, Node Explainer, and Node Content Builder, grounded in their dev/38 reads. **(4) Review-before-apply** — a granted mutate request mints a proposal (validated params, target's current content sha256 pinned as the revision basis, `proposal` part on the turn + `activeProposal` mirror, `review_required` before `done`); `POST …/proposals/<id>/apply` is the ONLY mutation path (digest drift → 409 + `stale`; success writes the one node's content, logs a result-card turn, consumes no quota); `DELETE` dismisses; newest supersedes. **(5) Frontend** — `AgentReviewCard` (docs/03 shell, inert preview, Apply/Dismiss as system review controls — the DEC-035 exception family; outcome labels once resolved); transient tool-activity system lines from the stream events (durable record = `toolCalls`); apply/dismiss refresh transcript + listing together.
- Files/modules changed: `app/agents/{content.py,tools.py,builtin.py,services.py,sessions.py,attachments.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/content/{AgentReviewCard.tsx,AgentReviewCard.module.css}` (new), `components/agents/attach/{AgentChatPanel.tsx,AgentAttachmentsProvider.tsx,AgentDockOverlay.tsx}`; `docs/AGENTS.md`
- Tests added/updated: `test_content.py` (+10: toolRequest grammar/bounds/exclusivity, proposal-spoof rejection, grant-aware instruction incl. the byte-identity pin), `test_tools.py` (rewritten: registry contents, both-effects grant policy, read executors incl. strip-agent-state + truncation), `TestToolLoop` (5: events ordering + record + summed usage, ungranted refusal, round cap, loop-never-mutates, grant-less byte-identity) and `TestReviewProposals` (8: mint, review_required ordering, apply + result turn + no-quota + idempotence, digest-drift stale, dismiss, supersede, **injection resistance**, validation refusals) in `test_routes.py`; frontend `AgentReviewCard.test.tsx` (8 incl. inert hostile preview), panel review/tool-line tests (2), provider apply/409 wiring (2), stream onEvent routing + endpoint tests (2)
- Verification evidence: backend `pytest tests --ignore=tests/test_frontend` → 848 passed; frontend `npx jest` full → 592 passed (55 suites)
- Commit/PR: `COMMIT-ffef3b9a` (tail contract), `COMMIT-c580aeaa` (loop), `COMMIT-f812b4f4` (review flow), `COMMIT-fc815f3e` (frontend)
- Issues/regressions discovered: dev/39's mutate-ungrantable policy tests superseded by the dev/41 grantable-for-proposal policy (updated; the never-executes property moved to route-level tests).
- Follow-up work: P5 composites consume this substrate (suggestion/preview card producers, graph-shape mutation tools with their own apply semantics, `delegatesTo` orchestration — the LangChain revisit point); T3 ledgers meter multi-round runs; tool-call policy fields (`REQ-QUOTA-001`) when someone needs to tune the round cap.
- Remaining risks/questions: model reliability at emitting valid toolRequest tails is observational (fail-open: a malformed request degrades to text); `inputs.reads` prompt-time injection remains unimplemented by design — the pull-based read tools are the chosen alternative; revisit only with usage evidence.

---

## BL-P2-20260728-09: Runtime maturation T3 — ledgers + pricing (DEC-044)

- Date / author: 2026-07-28 / Karla
- Status: verified
- Requirements: `REQ-COST-001` (immutable price snapshot + atomic idempotent reservation before provider work; estimates advisory; actual usage append-only; **unknown pricing fails closed under a hard monetary cap**), `REQ-QUOTA-001` (atomic windowed reservations — concurrent attempts cannot oversubscribe), memo `11` (Estimated vs Actual labeling, honored end-to-end)
- Design decisions/artifacts: **`DEC-044`** (registered with this entry: the FS ledger realization + the deployment-owned empty-by-default price table), `DEC-040` (FS-backed — the ledger is per-day JSONL under the user dir), `dev/05`:1242-1244 (price-snapshot / reservation / usage-ledger-entry shapes), memo `dev/40`
- Tasks: `TASK-P2-ledger`, `TASK-P2-pricing`
- Risks/questions: `RISK-COST-001` — **closed for the synchronous runtime**: admission is one flock-guarded critical section (thread + fork race tests prove exactly-one-admit at the last slot/dollar); a crashed run's hold self-expires at the day boundary (conservative); lease-based reconciliation remains with background execution. Windows degrades to in-process locking exactly as `projects/storage.py` already does.
- Design-to-code decision or deviation: **(1) Ledger** (`app/agents/ledger.py`) — append-only per-day JSONL with entry kinds `reserve`/`settle`/`usage`/`seed`; every aggregate derived, none stored; reservationId **is** the T1 executionId; settles are first-write-wins idempotent, land in the reservation's own day, and compute `costUsd` from the reservation's **pinned** snapshot (a mid-day table edit never rewrites what an earlier run was charged — pinning test). Budget = the spend ladder (settled actuals + settled estimates + in-flight holds + this run's hold) with the `REQ-COST-001` fail-closed rule — **the tranche's one deliberate behavior change** (previously a budget without an estimate silently disabled the gate; now it denies, 429 `reason: "budget"`, named message, tested by name). A one-time same-day `seed` carries the legacy `quota.json` counts forward (an exhausted quota stays exhausted across the deploy). **(2) Pricing** (`app/agents/pricing.py`) — `.curio/agents-pricing.json` (env-overridable), **empty by default**: the default aiconn deployment has no per-token USD price and memo 11 forbids fabricating one. **(3) Runtime** — both paths reserve atomically before dispatch and settle once at completion (ok and error alike; a T2b multi-round run settles its summed usage as one reservation); the title call is a priced `usage` entry (counted, never run-counted); execution records gain `costUsd` (Actual-or-null). `quotas.py` reduces to the deployment limit + ledger-backed reads, re-exporting `QuotaExceeded` — **the 429 contract is byte-compatible** (every pre-existing quota/budget route test passed unchanged before any test edits). **(4) Surfaces** — settings payloads gain `actualSpendTodayUsd` (null until anything real exists — never a fake $0.00) + a no-secrets `pricing` summary; the Cost screen shows Actual USD · tokens · effective date when priced, names the missing price otherwise, and states all four gate states incl. fail-closed.
- Files/modules changed: `app/agents/{ledger.py (new),pricing.py (new),quotas.py (rewritten as facade),services.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/settings/AgentSettingsModal.tsx`; `docs/AGENTS.md`
- Tests added/updated: `test_ledger.py` (24: roundtrip/aggregates, idempotent double-settle, settle-without-reserve, append-only bytes, corrupt-line tolerance, midnight windowing, legacy seed ×4, budget ladder ×6 incl. fail-closed + actuals-replace-holds, **thread and fork race tests**), `test_pricing.py` (8 incl. the mid-day pinning test), `test_quotas.py` (rewritten: facade reads + re-export identity), `TestLedgerAndPricing` in `test_routes.py` (5: priced settlement → `costUsd` + `actualSpendTodayUsd`, honest nulls, fail-closed by name consuming nothing, budget+estimate parity, error-run settlement); frontend Cost-screen state tests (4: priced/unpriced/fail-closed/actual-gated)
- Verification evidence: backend `pytest tests --ignore=tests/test_frontend` → 877 passed; frontend `npx jest` full → 596 passed (55 suites)
- Commit/PR: `COMMIT-a69ab1ca` (ledger), `COMMIT-0224bf42` (pricing), `COMMIT-1bb6f1a0` (runtime wiring), `COMMIT-157889f6` (frontend)
- Issues/regressions discovered: none — the pre-ledger admission tests passed over the ledger unchanged; only retired-function unit tests were rewritten.
- Follow-up work: T4 provider profiles + secret store (`ADR-AG-012` remainder); P5 composites — the Dataflow Builder's parent/child **aggregate reservations** now have their substrate (`dev/11`); leases/reconciliation with background execution; evaluation sub-budgets (`DEC-037`, v2 governance).
- Remaining risks/questions: operator price tables can misstate reality (garbage-in — the table is deployment-owned and pinned per run, so at least auditable); `OQ-009` (multi-instance topology) unchanged — flock covers multi-process on one host, not NFS-mounted multi-host.

---

## BL-P2-20260729-10: Grounded run inputs — preamble/input propagation for attached built-ins (memo dev/44)

- Date / author: 2026-07-29 / Karla
- Status: verified (fix for post-implementation testing feedback; not a regression — the gap existed since the migration)
- Requirements: `dev/06` migration parity (the legacy call sites' pushed context), the dev/38 `inputs.reads` contract (declared but previously unsupplied at run time)
- Design decisions/artifacts: memo `dev/44`; amends memo `dev/38` (§5 added) and the `BL-P5-20260719-01` migration parity claim; closes the "prompt-time inputs.reads grounding" item dev/39/dev/41 deferred pending usage evidence — this testing feedback was that evidence. The dev/41 read tools remain the pull-based complement.
- Tasks: `TASK-P2-grounded-inputs`
- Risks/questions: none new — context is user-owned project data composed by our own client, bounded server-side (120k chars, visible truncation), never persisted, never on the share surface.
- Design-to-code decision or deviation: **(1) Verified first**: preamble composition was CORRECT (incl. stale pre-dev/38 store copies via the roster fallback — empirically 18.5 KB composed); the defect was inputs. **(2) Ephemeral context pipeline** — run/stream accept an optional bounded `context` string framed as ONE provider message between session history and the user's turn: recomputed per send (stale impossible), never persisted (the transcript stays what the user saw), never replayed; absent → byte-identical (regression-pinned). The attachment card exposes the manifest's `reads`. **(3) Live-canvas composer** (`agentRunContext.ts`) — Node Content Builder reproduces `clickGenerateContentNode` byte-for-byte (Trill from live nodes/edges with the target's content blanked + Node ID + Subtask (node goal) + Task (workflow goal)), proven in tests against an independently generated legacy composition; other built-ins assemble canonical per-read fragments in manifest order (dev/44 §3.3 audit table: every chat-time-sourceable read covered; `connectionSide`/panel `keywords`/`currentTask` documented as chat-time omissions). Unsaved/new nodes covered by construction (live ReactFlow state). **(4) Materialization heal** — stale built-in store copies gain the current roster asset set on install/import; complete copies byte-untouched; owned imported shadows never rewritten.
- Files/modules changed: `app/agents/{services.py,routes.py}`; frontend `api/agentsApi.ts`, `components/agents/attach/{agentRunContext.ts (new),AgentDockOverlay.tsx,AgentAttachmentsProvider.tsx,useAgentAttachments.ts}`; memo `dev/38` (§5); `docs/AGENTS.md`
- Tests added/updated: `TestRunContext` (7: placement, ephemerality, recompose-not-replay, byte-identity pin, truncation, 400, stream parity, card reads) + `TestMaterializationHeal` (3: stale-copy heal, complete-copy untouched, imported-shadow never rewritten) in `test_routes.py`; frontend `agentRunContext.test.ts` (5 incl. the byte-for-byte legacy-parity fixture with target-content blanking and unsaved-node inclusion) + provider/hook forwarding tests (2)
- Verification evidence: backend `pytest tests --ignore=tests/test_frontend` → 905 passed; frontend `npx jest` full → 611 passed (56 suites)
- Commit/PR: `COMMIT-230364e6` (backend pipeline), `COMMIT-fc6a4e6d` (frontend composer)
- Issues/regressions discovered: the perceived "wrong preamble" was a downstream symptom of the missing inputs; documented in dev/38 §5.
- Follow-up work: `nodeContext.current_input/current_output` currently send empty (legacy passed live execution values from the node widget) — wire execution outputs into the composer when the exec store exposes them to the overlay; P5 composites inherit the pipeline via their declared reads.
- Remaining risks/questions: none new.
