# Hookable Agents

Hookable agents are Curio's reusable AI building blocks. Like a node package, an agent is a small, self-contained folder with a `manifest.json` describing what it does — but instead of a canvas node, it defines an assistant you can attach to a node, a connection, or the whole canvas, and refine in chat.

> **Status: in active development.** This document grows as the feature lands. Today it covers the **agent manifest contract** — the schema and validator every agent package is built on. The catalog drawer, install/attach lifecycle, and chat surfaces are documented here as each ships.

This guide is in parts, plus a developer appendix:

- [1. What is a hookable agent?](#1-what-is-a-hookable-agent) — the model and how it relates to node packages.
- [2. The agent manifest](#2-the-agent-manifest) — the `manifest.json` contract, field by field.
- [3. Capabilities](#3-capabilities) — semantic behavior contracts, and why they are never prompt filenames.
- [4. The default LLM provider](#4-the-default-llm-provider) — the single default every agent (and the LLM chat) falls back to.
- [5. Where lifecycle state lives](#5-where-lifecycle-state-lives) — the filesystem layers, mirroring the Node Catalog.
- [6. Catalog & lifecycle API](#6-catalog--lifecycle-api) — the `/api/agents` endpoints.
- [Appendix: validating a manifest (developer-only)](#appendix-validating-a-manifest-developer-only).

---

## 1. What is a hookable agent?

Every agent Curio knows about ships as an **agent package**, identified by an id and a version:

```
<agentId>@<version>     e.g.   agent.node-explainer@1.0.0
                             agent.dataflow-builder@1.0.0
```

Agent package ids always begin with **`agent.`**, which keeps them distinct from node package ids (`curio.builtin`, `ai.urbanlab.uhvi`) and other product namespaces. A package is a folder with a `manifest.json` (the contract) and a `prompts/` directory holding the system preamble and instruction assets the manifest references by digest.

Agents follow the same **catalog model** as node packages and datasets — you browse a shared catalog, import/install into your own scope, and (for definitions you own) publish back to the catalog hub. The manifest is the foundation that model is built on; this document starts there.

Open the drawer from the top menu: **Data → Agents Catalog**. It has the three scope tabs — **Global Catalog**, **My Imports**, **Installed in this project** — reusing the same drawer chrome as the Node and Data catalogs. The agents installed in the open project also appear in the **AGENTS** palette in the left tools panel (alongside DATA and PACKAGES), with a **Get more agents +** shortcut back to the drawer; palette rows are draggable and action-free.

| Concept | Node package | Hookable agent |
|---|---|---|
| Ships as | `<packageId>@<major>/` with `manifest.json` | `<agentId>@<version>/` with `manifest.json` + `prompts/` |
| Id namespace | `curio.builtin`, `ai.urbanlab.uhvi` | `agent.node-explainer`, `agent.dataflow-builder` |
| Provides | Draggable canvas node kinds | An assistant attachable to a node / connection / canvas |
| Canonical schema | [`docs/schemas/node-package.v4.json`](schemas/node-package.v4.json) | [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) |

---

## 2. The agent manifest

The manifest uses **camelCase** field names and is validated against [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) (JSON Schema Draft 2020-12). The schema is the source of truth for what fields a manifest can declare.

A minimal, complete manifest:

```json
{
  "$schema": "../../docs/schemas/agent-package.v1.json",
  "id": "agent.node-explainer",
  "name": "Node Explainer",
  "category": "node",
  "version": "1.0.0",
  "purpose": "Explain what a node or its output does.",
  "roles": ["explanation"],
  "capabilities": [
    { "id": "node.explain", "contractVersion": "1" },
    { "id": "node.output.interpret", "contractVersion": "1" }
  ],
  "delegatesTo": [],
  "prompts": {
    "system": { "path": "prompts/default_preamble.txt", "sha256": "<sha256>", "variables": [] },
    "instruction": { "path": "prompts/single_box_explanation.txt", "sha256": "<sha256>", "variables": ["nodeContext"] }
  },
  "compatibleTargets": [{ "kind": "node", "requires": ["code-or-output"] }],
  "inputs": { "reads": ["nodeContext"], "requiredConfig": [] },
  "outputs": ["explanation"],
  "runtime": { "execution": "foreground", "reviewPolicy": "report-only" },
  "providerRequirements": { "capabilities": ["structured-output"] },
  "tools": [{ "id": "catalog.search", "required": false }],
  "settingsDefaults": { "profileId": "interactive-report", "profileVersion": "1" },
  "provenance": { "publisher": "curio", "license": "MIT", "trust": "built-in" }
}
```

| Field | Required | What it declares |
|---|---|---|
| `id` | ✓ | `agent.`-prefixed, kebab-case package id. Pairs with `version` to form the on-disk directory `<id>@<version>`. |
| `version` | ✓ | Semver-style version string. |
| `name` | ✓ | Human-readable name shown in the catalog. |
| `category` | ✓ | One of `data`, `node`, `canvas`, `package`, `evaluate` — the catalog chip and hook-target family. |
| `capabilities` | ✓ | Non-empty list of `{ id, contractVersion }` — the semantic contracts this agent implements (see §3). |
| `provenance` | ✓ | `{ publisher, license?, trust? }`; `trust` is one of `built-in`, `global`, `imported`. |
| `purpose`, `roles` | | One-line description and display roles. |
| `delegatesTo` | | Other `agent.` ids this agent may call. Expresses a preferred implementation only — it grants nothing and never auto-imports or auto-installs. |
| `prompts` | | Prompt assets by **contained** package-relative `path` + `sha256` + declared `variables`. Absolute paths and `..` escapes are rejected. |
| `compatibleTargets` | | Where the agent can attach: `{ kind: node\|canvas\|connection, requires: [...] }`. |
| `inputs`, `outputs` | | Context the agent reads / config it requires / named outputs it produces. |
| `runtime` | | `execution` (`foreground`\|`background`) and `reviewPolicy` (`report-only`\|`review-before-apply`). |
| `providerRequirements` | | Provider *capability* requirements (e.g. `structured-output`). Provider **credentials** are selected through an authorized account-level provider profile outside the manifest. |
| `tools` | | Typed, allowlisted tool **requirements** — never executable code or permission grants. |
| `settingsDefaults` | | Immutable, non-secret seed suggestions plus a reviewed profile-family id/version. A manifest cannot create a new trusted profile family implicitly. |

The on-disk directory name is authoritative: the loader cross-checks it against the manifest's `id` and `version` and rejects a mismatch, exactly as the node-package loader does.

---

## 3. Capabilities

A **capability** is a semantic behavior contract — *what* an agent does — kept deliberately separate from the prompt file that implements it. A capability id is two or more dot-separated lowercase segments:

```
node.explain            dataflow.orchestrate       package.recommend
node.output.interpret   dataset.fetch.author       connection.propose
```

Capability ids are used for catalog discovery, orchestration resolution, compatibility, and substitution — **never for authorization**. Because they are contracts and not assets, a capability id **must not** contain a prompt filename, path separator, underscore, or `.txt`. So `node.explain` is valid; `single_box_explanation_prompt` or `prompts/explain.txt` are rejected. This keeps the "what" (capability) cleanly independent of the "how" (prompt asset), so a prompt can be edited or replaced without changing the capability contract.

`delegatesTo` lets one agent compose over another's capabilities (an orchestrator delegating to specialists, for example). Delegation names a preferred implementation; it never grants permission and never triggers an import or install on its own.

---

## 4. The default LLM provider

An agent's `providerRequirements` declare what it needs from a provider (e.g. `structured-output`); the *actual* provider, model, endpoint, and key come from configuration, not the manifest. Curio resolves this from a **single default** so there is no separate built-in default scattered through the code: when a user has not configured their own provider under **LLM Settings**, the app falls back to `config.DEFAULT_LLM_*`, seeded from the sage200 OpenAI-compatible endpoint.

| Setting | Env var | Default |
|---|---|---|
| Provider type | `CURIO_DEFAULT_LLM_API_TYPE` | `openai_compatible` |
| Base URL | `CURIO_DEFAULT_LLM_BASE_URL` | `https://sage200.evl.uic.edu/v1` |
| Model | `CURIO_DEFAULT_LLM_MODEL` | `llama4-nim` |
| API key | `CURIO_DEFAULT_LLM_API_KEY` / `AICONN_API_KEY` | *(unset)* |

Resolution rules (`_resolve_llm_config` in [`app/api/routes.py`](../utk_curio/backend/app/api/routes.py)):

- A user who has configured their own provider under **LLM Settings** keeps that exact config — the default never overrides or contaminates it (a configured Anthropic user never picks up the default base URL).
- An **unconfigured** user falls back to the default provider above rather than being turned away.
- **Guests** use `GUEST_LLM_*`, which inherits `DEFAULT_LLM_*` unless separately overridden, so guests default to the same provider.

Operators point the whole install at a different default by setting the env vars above; individual users still override per-account under LLM Settings. The API key is read from `AICONN_API_KEY` (the same name used by the connection harness) when a dedicated `CURIO_DEFAULT_LLM_API_KEY` is not set.

Provider *dispatch* lives in a provider-neutral port, [`app/agents/providers.py`](../utk_curio/backend/app/agents/providers.py) — `run_chat_completion(ProviderConfig, messages)`. It is the single place the `openai` / `anthropic` / `google-generativeai` SDKs are used, so LLM behavior stays out of the route/flow/node layers. A resolved provider config (from LLM Settings or the default above) is handed to the port; callers never import a provider SDK directly. A future LangChain adapter, if adopted, would sit behind this same port without changing callers.

---

## 5. Where lifecycle state lives

Agents follow the Node Catalog's storage model exactly: **state lives on the filesystem, not the database.** Curio's database holds only users and the project index; datasets, node packages, and now agents are all files under `.curio/` and inside each project's spec. There are no agent tables and no migrations.

| Layer | On disk | Holds |
|---|---|---|
| **Definition artifact** | `.curio/users/<user-key>/agents/<agentId>@<version>/` (`manifest.json` + `prompts/`) | The immutable agent definition — same shape and store as an installed node package. |
| **My Imports** (account) | `.curio/users/<user-key>/imported-agents.json` — `{ "version": 1, "agents": ["<id>@<version>", …] }` | Which definitions the account has imported. The analogue of `default-packages.json`. |
| **Installed in this project** | `spec["dataflow"]["agents"]` inside the project's `spec.trill.json` | The project's installed agent templates. The analogue of the `dataflow.packages` lockfile. |

The same tolerances apply as elsewhere in the catalog: a missing registry file is an empty list, a corrupt one is treated as empty (reads never raise), and one invalid definition directory is skipped — never fatal to listing the rest. Directory names and coordinates are validated against the agent-id + semver grammar, and every path resolves through the shared containment guard (`app/common/safe_paths.py`) so a coordinate can't escape the user's store.

The backend modules that own these layers are [`app/agents/storage.py`](../utk_curio/backend/app/agents/storage.py) (definitions), [`app/agents/imports.py`](../utk_curio/backend/app/agents/imports.py) (My Imports), and [`app/agents/project_agents.py`](../utk_curio/backend/app/agents/project_agents.py) (the project lockfile) — mirroring `app/packages/storage.py`, `defaults.py`, and `spec_packages.py` respectively.

---

## 6. Catalog & lifecycle API

The `/api/agents` endpoints ([`app/agents/routes.py`](../utk_curio/backend/app/agents/routes.py) over [`app/agents/services.py`](../utk_curio/backend/app/agents/services.py)) expose the scopes and lifecycle commands, mirroring `/api/packages`. **Import** (account) and **Install** (project) are separate explicit commands — neither triggers the other.

| Method + path | Scope | Effect |
|---|---|---|
| `GET /api/agents/catalog` `?projectId=` | Global Catalog | List the built-in agent definitions available to import/install (marks which are already imported/installed). |
| `GET /api/agents/imports` | My Imports | List the account's imported definitions (as cards). |
| `POST /api/agents/imports/upload` `{manifest, prompts}` | My Imports | Upload a **user-authored definition** (memo `dev/36`): manifest + prompt texts as JSON (no archives). Trust forced to `imported`, digests stamped from the bytes, exact file correspondence, size limits, 409 on an existing coordinate (immutable — bump the version), atomic write. Registers in My Imports; never installs or publishes. |
| `POST /api/agents/imports` `{coord}` | My Imports | Record `<id>@<version>` as imported. Never installs into a project. |
| `DELETE /api/agents/imports/<coord>` | My Imports | Drop it from My Imports. |
| `GET /api/agents/projects/<projectId>` | Installed | List the project's installed templates from its `dataflow.agents` lockfile. |
| `POST /api/agents/projects/<projectId>/install` `{coord}` | Installed | Add it to that project's lockfile. Explicit; never auto-imports. |
| `DELETE /api/agents/projects/<projectId>/<coord>` | Installed | Remove it from that project's lockfile (also drops its project-default record). |
| `GET /api/agents/projects/<projectId>/defaults/<coord>` | Installed | The **project-agent-default** scope for one installed template: the per-project `{revision, settings}` record plus the effective policy with per-field provenance (runs/day + usage, cost incl. estimated spend, max output tokens, no-secrets provider summary). Lazily materialized for older installs. |
| `PATCH /api/agents/projects/<projectId>/defaults/<coord>` `{revision, settings}` | Installed | Edit one template's project defaults — tighten-only against the account-effective policy, optimistic revision (409 on stale), `{"settings": {}}` = *Reset to agent default*; non-policy seed keys preserved. |
| `GET /api/agents/settings` | Account | The **Account-policy** scope: record + effective policy + deployment ceilings + runs used today. |
| `PATCH /api/agents/settings` `{revision, settings}` | Account | Edit the account agent policy — tighten-only against the deployment ceilings, optimistic revision (409 on stale). |
| `POST /api/agents/publications` `{coord}` | Publish | Publish an **owned, imported, store-backed** definition to the Global Catalog (imported-only — rejects built-in/global/absent). |
| `DELETE /api/agents/publications/<coord>` | Publish | Unpublish it (owner only). |
| `GET /api/agents/projects/<projectId>/attachments` | Attach | List the project's private attachments. |
| `POST /api/agents/projects/<projectId>/attachments` `{coord, target}` | Attach | Attach an installed template to a `{kind: node\|canvas\|connection, targetId?}`. Requires the template installed (no auto-install). |
| `DELETE /api/agents/projects/<projectId>/attachments/<attachmentId>` | Attach | Detach the private instance (also deletes its session transcript). |
| `PATCH /api/agents/projects/<projectId>/attachments/<attachmentId>` `{intent}` | Attach | Set/clear the attachment's editable **initial intent**; `null`/empty falls back to the definition's prompt source. Bumps `revision`. |
| `GET /api/agents/projects/<projectId>/attachments/<attachmentId>/settings` | Attach | The **Attached-instance** policy scope (memo `dev/42`): the record's tighten-only overrides + the three-layer effective view with binding-scope `usedToday` metering and the Cost passthroughs. |
| `PATCH /api/agents/projects/<projectId>/attachments/<attachmentId>/settings` `{revision, settings}` | Attach | Edit the attachment's overrides — tighten-only against the project-effective policy, optimistic on the record's shared revision, `{"settings": {}}` = *Clear overrides*. |
| `GET /api/agents/projects/<projectId>/attachments/<attachmentId>/session` | Run | The attachment's persisted chat transcript (`{sessionId, turns}`; empty when none). |
| `DELETE /api/agents/projects/<projectId>/attachments/<attachmentId>/session` | Run | Clear the transcript; the attachment and its session id are kept. |
| `POST /api/agents/projects/<projectId>/attachments/<attachmentId>/run` `{message, context?}` | Run | Run one turn of the attached agent (system turn = **preamble + intent/instruction + the structured-tail instruction**, per the legacy composition + bounded prior session context + the optional **grounded context** (memo `dev/44`) + your message) via the provider port; returns `{reply, executionId, usage, content}` and persists both turns to the session. |
| `POST /api/agents/projects/<projectId>/attachments/<attachmentId>/run/stream` `{message}` | Run | Same turn, streamed as Server-Sent Events: `event: execution` `{executionId}` → `event: delta` chunks → tool rounds as `event: tool_requested`/`tool_started`/`tool_result` (memo `dev/41`) → `event: review_required` `{proposalId, tool, summary}` when a mutation was proposed → `event: content` `{parts}` → `event: done` `{reply, executionId, usage, content}` (or `event: error`). Additive envelope — old clients skip unknown event names. Validation errors return plain JSON statuses before streaming; persistence matches the blocking run. |
| `POST /api/agents/projects/<projectId>/attachments/<attachmentId>/proposals/<proposalId>/apply` | Run | Apply a pending review proposal (memo `dev/41`) — **the only mutation path**: re-checks the pinned content digest (drift → 409 and the proposal marks `stale`), writes the one node's content, logs a result-card turn, consumes no quota. |
| `DELETE /api/agents/projects/<projectId>/attachments/<attachmentId>/proposals/<proposalId>` | Run | Dismiss a pending review proposal without applying it (the card keeps its outcome). |

Each endpoint requires auth; project endpoints check ownership (404 if the project isn't the caller's). A card carries `id`, `version`, `dirName`, `name`, `category`, `purpose`, `capabilities`, `hooks`, `provenance`, and the `imported` / `installedInProject` flags the drawer uses to pick the right action controls.

An **attachment** is a private agent instance bound to a target. It lives in the project's `spec["dataflow"]["agentAttachments"]` (alongside nodes/edges) and carries an `attachmentId` + a `sessionId` + an optimistic `revision` — no version/publish identity (`DEC-031`). Attaching requires the template to be installed in the project (never auto-installs), and a node/connection target must reference an existing node/edge.

Its card also carries an **`intent`**: the user's edit when present (stored on the record, `intentEdited: true`), otherwise the definition's instruction prompt resolved at read time from the actual prompt bytes — nothing duplicates prompt text into stored state, so an unedited intent always tracks the prompt source. Runs use the same value as the system turn, so the pinned intent is exactly what runs.

**Each install materializes a per-project defaults record** (`spec.dataflow.agentDefaults`, memo `dev/23`): one independent `{revision, settings}` profile per project (seeded from the definition's `settingsDefaults` profile id/version; built-ins empty), preserved across canvas saves like the lockfile, dropped on uninstall, never reset by a reinstall. In the drawer, every *Installed in this project* card carries a labeled **`Project agent settings`** cog opening the settings shell at the project scope, which edits this record (memo `dev/24`).

**Provider config is resolved inside the `agents/` boundary** (`app/agents/provider_config.py`, the v1 step of `ADR-AG-012`): guest env config → per-user `llm_*` fields → the aiconn sage200 default (`DEC-039`). The legacy `/llm/*` handlers read through a thin shim over this resolver; `app/agents` never imports `app/api` (boundary-tested). The `ProviderProfile` model and encrypted secret store remain v2.

**Runs are policy-gated through an atomic usage ledger** (`app/agents/{policy.py,ledger.py}`, memos `dev/24`/`dev/40`, `DEC-044`): one effective-policy resolver (`project ?? account ?? deployment`, clamped downward at read) feeds both the settings screens and admission. Admission is one flock-guarded critical section over an **append-only per-day ledger** (`.curio/users/<key>/agents/ledger/<date>.jsonl`): every run is a reserve→settle pair keyed by its execution id, so concurrent last-slot attempts serialize to exactly one admit (race-tested cross-thread and cross-process). Checks in order: the account runs/day limit, a project-template runs/day limit, a per-**attachment** runs/day limit when an attachment-scope override binds (memo `dev/42` — reserve entries carry an `attachmentKey`, so sibling attachments of the same template keep running), then the **budget spend ladder** — settled actual USD + settled estimates + in-flight holds + this run's hold — with the `REQ-COST-001` **fail-closed rule**: a configured `dailyBudgetUsd` with neither a cost estimate nor a table price denies the run (a hard cap that enforces nothing is forbidden; leave the budget unset for no gate). Denial is the same stable `429` `{error, quota, reason: "quota"|"budget", resetAt}` as always, consuming and persisting nothing. Old `quota.json` counters are retired; their same-day counts seed the ledger exactly once so a deploy cannot re-open an exhausted quota. Legacy `/llm/chat` is not gated.

**Pricing is deployment-owned and never fabricated** (`app/agents/pricing.py`): an operator table at `.curio/agents-pricing.json` (`CURIO_AGENT_PRICE_TABLE` overrides the path) maps `"<provider>/<model>"` to per-Mtok USD rates. The built-in table is **empty** — the default self-hosted provider has no per-token price, and Actual USD exists exactly where the operator states one (memo 11). Snapshots resolve at reservation time and pin into the reserve entry: a mid-day table edit never rewrites what an earlier run was charged. Settlement computes `costUsd` from the pinned snapshot × Actual tokens — or null when either half is missing.

**Every run leaves an execution record** (memo `dev/37`, the first v2-maturation tranche): the agent turn persisted to the session carries `{executionId, pins, usage, durationMs, status}` — the transcript **is** the run history (memo `12`); there is no parallel execution store. The `pins` are the `DEC-031` reproducibility inputs resolved from what actually dispatched: coord, the manifest's instruction-prompt sha256 (null tolerated for unstamped built-ins), whether the intent was edited, provider type + model (never secrets), and the flat effective-policy snapshot admitted for the run. `usage` is the provider-reported **Actual** token count, or `null` when the provider reports none — never an estimate (memo `11`); the port's `usage_out` sink captures it per backend (openai `include_usage`, anthropic response/stream usage, gemini `usage_metadata`). Error turns carry `status: "error"`, and since T3 the record also carries `costUsd` — the ledger settlement's Actual USD, null unless a deployment price existed for the run (memo `dev/40`). The run's tokens settle into the ledger at completion (summed across tool-loop rounds), and the recordless dev/25 title call is counted as a priced housekeeping entry — so the daily counters may exceed the transcript's sum, by design. `GET /api/agents/settings` and the project-defaults GET expose `usageToday`, `actualSpendTodayUsd` (null until anything real exists — never a fabricated $0.00), and a no-secrets `pricing` summary; the Quotas screen shows `N runs · X in / Y out tokens today (actual)`. Old turns/windows without the new keys read clean — no migrations, and provider context ignores the extra keys.

**The settings screens** (`AgentSettingsModal`): the shared shell with the three v1 policy screens — Cost (estimated spend labeled as such; the Actual line shows **true Actual USD · provider-reported tokens · the pricing effective date** where a deployment price exists, and names the missing price for `<provider> · <model>` otherwise; the gate-status line covers estimate-gated, actual-gated, the fail-closed blocked state, and off), Quotas (runs + actual tokens today), Resource policies — at the **Account policy** scope (the labeled `Agent settings` cog in the roster header), the **Project agent default** scope (the installed-card cog), and the **Attached instance** scope (memo `dev/42`: the labeled `Attachment settings` control at the top of the opened chat view's content area — beneath the `DEC-042` header, never in it). Every field shows its effective value + source across all four layers (`attachment ?? project ?? account ?? deployment`, tighten-only at every step); edits are revisioned (409 on stale — the attachment scope shares the record's revision with intent/title edits); the project scope offers *Reset to agent default* and the attachment scope *Clear overrides*. The attachment scope's `usedToday` meters the **binding** limit (an attachment-source limit shows that attachment's own count). The account-only cost estimate is read-only below account scope. No Publish/Release/Share exists in any settings scope.

**Chat replies stream**: the frontend consumes the SSE endpoint via `agentsApi.runAttachmentStream`, growing a live agent turn per delta; a pre-delta stream failure falls back to the blocking run once, and quota denials render as a soft error turn with the reset time.

**Runs are grounded in the live canvas** (memo `dev/44`): on every send the client composes the attachment's declared inputs (`inputs.reads`, dev/38 — the Trill, node id, subtask, workflow goal, node context, …) from the **live** ReactFlow state — unsaved nodes included — and the runtime frames them as one **ephemeral** provider message between the session history and the user's turn: recomputed each send (never stale), never persisted (the transcript stays what the user saw), bounded server-side. Node Content Builder reproduces its legacy Get Code framing byte-for-byte (the Trill with the target node's content blanked + Node ID + Subtask + Task); reads with no chat-time source (`connectionSide`, the legacy panel's `keywords`/`currentTask`) are carried by the user's message instead. This push mechanism complements the dev/41 read *tools* (the model's pull-based refresh against the saved spec). `_materialize_builtin` also heals stale built-in store copies to the current roster asset set on install/import.

**Structured agent content** (memo `dev/39`, `DEC-043`): the runtime appends one instruction letting the model optionally end its reply with a fenced ` ```curio.v1 ` JSON block. A **terminal** block is stripped server-side, validated against bounded typed contracts — `suggestedPrompts` (a primary + up to 3 alternatives) and `card` (kind/title/lines; informational plain data, **no actions** — actions are suggested prompts, never buttons) — and persisted as `content` parts on the agent turn; the visible text stays `turn.text`, so provider context never replays the tail. A malformed block fails **open**: it stays visible verbatim and attaches nothing. Streaming withholds a candidate tail so it never flashes into the live transcript (false positives and invalid tails are flushed as ordinary deltas). In the chat, the newest agent turn's suggested prompts prefill the input (editable — a user-typed draft always wins) with alternatives as a chip row above it, and cards render the docs/03 visual shell. All agent rich content renders only through the centralized safe renderer (`SafeAgentContent` over `sanitizeAgentContent` — markdown yes, raw HTML never, `http(s)`/`mailto` links only), hostile-content tested (`REQ-SEC-002`).

**Tool contracts** (`app/agents/tools.py`, `DEC-017`/`DEC-043`/`DEC-045`): manifest `tools` entries — `[{id, required?}]`, capability-id grammar, no duplicates — are untrusted *declarations*, never grants. The server resolves `granted = requested ∩ registry ∩ policy` per run; granted ids are pinned on the execution record (`pins.tools`); a `required` tool that resolves no grant refuses the run with a 422 before admission (no quota consumed). The registry holds three contracts, each with a named built-in consumer: `dataflow.read` and `node.read` (read) and `node.content.write` (mutate).

**Tools execute in a bounded server-side loop** (memo `dev/41`, `DEC-045`): a reply may end with one `toolRequest` tail; a **granted read** contract executes its domain-owned implementation (`ADR-AG-007` — `dataflow.read` returns the saved spec through `strip_agent_state`, so agent-private sections never enter model context; `node.read` defaults to the attached node; results are bounded at 32 KB and fed back as framed untrusted data), then the model is re-prompted — at most **2 tool executions per run**. The execution record gains `toolCalls` and usage summed across rounds; the live client shows transient system lines. Ungranted/unknown requests refuse loudly to the model, invisibly to the user; grant-less runs are byte-identical to before.

**Mutations are review-before-apply** (`DEC-006`/`REQ-REVIEW-001`, structural): a granted `mutate` request never executes — the runtime mints a **proposal** (validated params, the target's current content sha256 pinned as the revision basis) persisted as a `proposal` part on the turn plus the attachment's `activeProposal` mirror, streamed as `review_required`, and rendered as the review card (inert plain-text preview; Apply/Dismiss are *system review controls*, the same sanctioned family as the `DEC-035` install dialog — agent workflow actions remain suggested prompts, never buttons). Only the authenticated apply endpoint executes the write; no model reply, tool result, or user message text can trigger it (injection resistance, tested by name). A newer proposal supersedes a pending one; applying a drifted target 409s and marks it `stale`. **LangChain remains uninstalled by decision** (`DEC-045`): the loop is direct provider-port code; `DEC-007`'s adapter adoption is deferred to P5 multi-agent delegation.

**Shared links carry no agent-private data** (`project_agents.strip_agent_state`, memo `dev/35`): the unauthenticated shared-project route serves a sanitized copy of the spec without the backend-owned agent sections — the install lockfile and the attachment records (including edited intents, conversation titles, and session ids) never reach shared viewers, while the non-agent graph stays intact. The per-project agent endpoints (attachments, sessions, defaults) are owner-only. Regression-enforced by `tests/test_agents/test_share_regression.py` (tracking rule 9, `DEC-032`).

**Chat sessions are persistent** (`app/agents/sessions.py`): each attachment's transcript lives in a private sidecar at `.curio/users/<key>/projects/<pid>/agent-sessions/<sessionId>.json` — deliberately **outside** the project spec, so canvas saves and the share pipeline never carry conversation content. `run` includes the last 20 non-error turns as provider context and persists the exchange; a provider failure persists the user turn plus a display-only error marker (excluded from future context) and returns 502. A transcript lives exactly as long as its attachment: detach deletes the file, and the orphan-prune on canvas save GCs the files of pruned attachments (final retention durations remain `OQ-008`).

Installing (or importing) an agent **materializes its prompt bytes into the user store** (`.curio/users/<key>/agents/<id>@<version>/manifest.json` + `prompts/`) — a built-in seeds **both** its instruction and its system preamble (`default_preamble.txt`, or the syntax agent's own) from `utk_curio/llm-prompts/`. So an installed agent is self-contained on disk and doesn't depend on the legacy prompt dir at runtime.

**Running** an attachment resolves its source definition's instruction prompt — the materialized store copy first, then the published-catalog copy, falling back to the built-in source — sends it as the system turn plus the caller's `message`, and dispatches through the provider port (§4). Any installed agent that carries an instruction prompt runs; a definition with no prompt asset returns 422.

In the UI: **drag an installed agent from the AGENTS palette onto a node** to attach it to that node, or **onto empty canvas** to attach it to the whole canvas (the drop target is resolved from the node under the cursor); node agents render as avatar badges on their node, canvas agents in the top dock bar. **Click a badge/tile** to open the **chat panel** (styled to the approved concept, `DEC-042`: one dark top header with ‹ › agent-cycling arrows that walk all attachments, the tinted bot + name + `idx / total`, the attached target + session chip, Clear conversation, and Close — no Pin; the intent renders as the conversation's first editable message, followed by dark user bubbles / avatar-prefixed agent rows and a pill input with a circular ↑ send). The **Agents Catalog drawer** header carries the Pin only (`DEC-042`) — pinning blocks the backdrop/Escape dismissals. Each send runs one turn through the run endpoint; the transcript is hydrated from the persisted session, so closing the panel (✕ / Escape — the agent stays attached), reopening, or reloading the page restores the conversation. The header also offers *Clear conversation* (confirm-first) and the ✕ on a badge detaches. A node target is validated against the *saved* project spec, so attach to a node after the project has been saved.

The **Global Catalog** is the 14 built-in agents ∪ any **published** definitions. Thirteen built-ins are the migrated prompt behaviors (Chat, Debug, Node Explainer, Dataflow Explainer, Connection Builder, the planners/validators, etc.), defined as a data-driven roster in [`app/agents/builtin.py`](../utk_curio/backend/app/agents/builtin.py), generated from the canonical prompt→agent map over `utk_curio/llm-prompts/*.txt` and validated through the manifest contract; the fourteenth is **Node Builder** (`agent.node-builder`), the first composite (memo dev/48) with a net-new instruction in the same directory. A built-in resolves for Import/Install straight from the roster (no prior store copy needed). The generated-content evaluator is intentionally absent (no prompt asset yet).

**Node Builder (the first composite).** Attached to the canvas, it turns one described step into ONE reviewable new node. Reuse-first is structural: its `node.create` proposals may only instantiate node templates the project can already use (the seeded `curio.builtin` package plus the project's package lockfile — enumerated per run by the packages domain, never a hardcoded list, re-validated at apply). Only when no available template fits may it propose a **new custom node type** (`node.template.create`) — a reviewed proposal carrying its written justification, applied through the existing package factory as a namespaced `curio.agent.<slug>@1` package plus the first node, transactionally. It can **delegate** content generation to Node Content Builder (`delegateRequest` → a depth-1 child run with its own execution record, `parentExecutionId` link, and its own quota/budget admission); a delegate that isn't installed in the project yields a reviewed `Install in project` proposal, never a silent install. Applied mutations reach the saved spec **and** the live canvas in the same action (the apply→canvas bridge — which also fixes the older `node.content.write` live-sync gap).

Each built-in declares its system preamble asset and the context it reads (`inputs.reads`), grounded in what its legacy call site passed:

| Built-in | Capabilities | `inputs.reads` | Preamble |
|---|---|---|---|
| Chat | `conversation.respond`, `attachment.refine` | `userMessage` | default |
| Debug | `code.debug.diagnose`, `code.fix.propose` | `dataflowContext` | default |
| Dataflow Explainer | `dataflow.explain` | `dataflowContext` | default |
| Node Explainer | `node.explain`, `node.output.interpret` | `nodeContext` | default |
| Node Content Builder | `node.content.generate` | `dataflowContext`, `nodeId`, `subtask`, `workflowGoal` | default |
| Execution Subtask Planner | `execution.followup.plan` | `nodeContent`, `nodeType`, `currentTask` | default |
| Dataflow Task Planner | `workflow.plan.create` | `currentTask`, `dataflowContext` | default |
| Connection Builder | `connection.propose` | `workflowGoal`, `nodeId`, `subtask`, `connectionSide`, `dataflowContext` | default |
| Workflow Suggester | `workflow.suggest` | `dataflowContext`, `workflowGoal` | default |
| Plan Coherence Validator | `workflow.coherence.validate` | `workflowGoal`, `dataflowContext` | default |
| Syntax Analysis | `code.syntax.analyze` | `codeContext` | `syntax_analysis_preamble.txt` |
| Task Refresh | `workflow.plan.refresh` | `currentTask`, `keywords`, `dataflowContext` | default |
| Keyword Binding | `workflow.keyword.bind` | `keywords`, `dataflowContext` | default |

("default" = `default_preamble.txt`. At run time the system turn composes the preamble + the instruction — or the attachment's edited intent in place of the instruction.)

**Publish is imported-only** (`DEC-030`): only an owned, imported, store-backed definition can be published — a built-in (or any global/absent) coordinate is rejected. Publishing copies the definition into a deployment-shared catalog at `.curio/agents-catalog/<id>@<version>/` ([`app/agents/publications.py`](../utk_curio/backend/app/agents/publications.py)), where every user's Global Catalog then lists it. A My Imports card carries `publishable` (owned + store-backed) and `published` flags, so the drawer's Publish pill only appears for eligible definitions. **Publish is user-reachable**: upload-import (memo `dev/36`, the drawer's `Import package` button) creates owned `imported`-trust definitions, which are exactly what Publish accepts.

---

## Appendix: validating a manifest (developer-only)

The canonical spec is [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json). The backend validator that implements the supported subset lives in [`utk_curio/backend/app/agents/manifest.py`](../utk_curio/backend/app/agents/manifest.py) and mirrors the node-package validator ([`app/packages/manifest.py`](../utk_curio/backend/app/packages/manifest.py)):

```python
from pathlib import Path
from utk_curio.backend.app.agents.manifest import load_agent_manifest, parse_agent_manifest

manifest = load_agent_manifest(Path("agents/agent.node-explainer@1.0.0"))
# or validate an already-parsed dict:
manifest = parse_agent_manifest(raw_dict)
```

Both raise `AgentManifestError` (a `ValueError`) with a `{where}.field` message pointing at the offending field. The validator enforces the id/version grammar, the capability-id rules above, prompt-path containment, and the directory/manifest agreement.

---

## See also

- [`docs/schemas/agent-package.v1.json`](schemas/agent-package.v1.json) — the manifest JSON Schema.
- [`docs/CATALOG.md`](CATALOG.md) — the Node Catalog, whose package/catalog model hookable agents mirror.
- [`utk_curio/backend/app/agents/manifest.py`](../utk_curio/backend/app/agents/manifest.py) — the manifest validator.
