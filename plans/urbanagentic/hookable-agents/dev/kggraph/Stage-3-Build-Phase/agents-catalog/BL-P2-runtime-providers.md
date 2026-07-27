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
