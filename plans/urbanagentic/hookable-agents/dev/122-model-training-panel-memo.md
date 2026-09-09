# dev/122 — Model Training in AI Settings: fine-tune on the approved fixtures, or say plainly why you cannot

**Status: PROPOSED (2026-09-09) on `imp/agentcatalog` — memo complete, no code yet. Proposes `DEC-078`; backlog entry `BL-P5-20260909-56` at the first implementation change. Delivers dev/121 F1 (the Model Training panel and its nine preconditions) and consumes dev/121's export, whose held-out split has had no consumer until now. The panel is functional or absent: where the configured endpoint has no fine-tuning surface it reports **Unavailable** with the endpoint's own reason, and it never simulates a job.**

Date: 2026-09-09
Branch / tree: `imp/agentcatalog` @ `0d53d203` (dev/121 closed). Line numbers pinned to that commit. `plans/` is tracked on this branch; `plans/urbanagentic/hookable-agents/knowledge-graph/` (354 MB site copy) stays untracked by intent.
Origin: the owner's instruction of 2026-09-09 — *"go ahead with the finetuning related follow ups, as always memo first"* — against dev/121's F1, whose preconditions this memo is written to settle: provider capability detection, dataset consent and licensing, redaction, cost disclosure, job status and cancellation, trained-model versioning, an evaluation gate, activation, and rollback.
Evidence (what exists): dev/121's fixtures and library — 31 reviewed prompt fixtures with `split ∈ {train, validation, heldout}` and a `review.status` gate (`docs/examples/prompts/`, `docs/schemas/example-prompt-fixture.v1.json`); `app/agents/evaluation/export.py` (`rows_for_split`, `TRAINABLE_SPLITS = ("train",)`, `ExportRefused`); `app/agents/evaluation/oracle.py` (`plan_for` → the exact plan bytes the runtime's parser accepts, and `Unrepresentable` for what the contract cannot express); `app/agents/evaluation/live.py` + `utk_curio/tools/agent_eval.py` (the opt-in evaluation runner and its report); `report.scrub` (the one write-side redactor, built on `utk_curio/common/redaction.py`). Provider seam: `app/agents/providers.py` exposes `run_chat_completion`, `stream_chat_completion`, `list_provider_models` and nothing else — confirmed again for this memo. Recording precedent: `app/agents/model_catalog.py` records what an endpoint said about itself, per account, and replays it labelled with the date it was true. Egress chokepoint: `app/agents/egress.py` (`check_url`, `fetch`, `CallBudget`, `EgressRefused`, and dev/90 A2's `trusted_host` exemption for a host the operator declared by configuring it). Settings surface: `AiSettingsModal.tsx` with `connectionKeys/ConnectionKeysSection.tsx` as the collapsible sub-panel precedent (dev/116 commit 4). Roster block: `services._available_templates_block(project_id, landscape, notes_agent=...)` composes the system turn's template listing from a `landscape` dict, so the same formatter can compose a training example's system turn.
Evidence (what is missing): no fine-tuning contract anywhere in the code — `grep -rn "fine.?tun|finetune|lora|adapter_weights|peft|distill"` over `utk_curio` returns nothing, and the only tuning-adjacent strings in the repository are three HuggingFace checkpoint names in example 10. Every other mention in `plans/` and `docs/` (seventeen of them) is dev/121 and its ledgers saying this does not exist yet and what would be required first. No training job record, no trained-model provenance, no consent record, and no consumer for the `heldout` split.
Evidence (the provider fact this memo turns on): **Anthropic's public API has no fine-tuning endpoint.** Its API overview lists Messages, Message Batches, Token Counting, Models, Files and Skills, plus beta Agents, Sessions and Environments — nothing for tuning or custom-model training (`https://platform.claude.com/docs/en/api/overview`, read 2026-09-09). OpenAI-compatible endpoints are the family that does publish one (`/v1/files` + `/v1/fine_tuning/jobs`), and an *OpenAI-compatible* endpoint is not the same thing as OpenAI: Ollama, LM Studio and vLLM answer the chat route and nothing else. Gemini has a tuning surface of a different shape (`tunedModels`). So capability is **detected per endpoint, never tabulated per provider name** — the `provider-models` doctrine (`routes.py:122-160`: *"Nothing here is authored by hand. The first cut of this route carried a literal table of model ids, which drifts silently the moment a provider ships or retires one"*).
Family: dev/11 (`DEC-058`, prompt governance deferred; *"a candidate cannot judge/approve itself"*) → dev/85 (`DEC-055`, the evaluator has **no authority**) → dev/116 (`DEC-074`, the AI Settings sub-panel precedent and the redaction boundary) → dev/121 (`DEC-077`, the fixtures, the export and the deterministic comparator) → **dev/122**.
Design decisions consumed: `DEC-077` (fixtures never leak, held-out is never training data, no agent grades an agent), `DEC-055` (report-only evaluator, no authority), `DEC-058` (Prompt Quality/Audit/release/governance-history stay reserved — this panel is none of them), `DEC-074` (a credential is a named connection key, never a literal; redaction at every write boundary), `DEC-062` (one roster, one vocabulary), `DEC-072` (the grounding gate's refusal texts are training-relevant, see §6), dev/90 A2 (the operator declares a host by configuring it), dev/10 (the egress chokepoint).
Design decision proposed: **`DEC-078` — Curio can fine-tune the configured model on its own approved example fixtures, and every step is either real or absent. Capability is probed on the endpoint the account configured and reported with the endpoint's own reason; the training set is built from APPROVED `train`-split fixtures only, targets are the exact plan bytes the runtime's parser accepts (so a fixture the agent contract cannot express is excluded by construction), and it is scrubbed and consented to by an explicit act that records what was sent and where; the provider owns the long-running job and Curio owns its record; the trained model becomes a first-class model entry labelled with its training digest and date; and it CANNOT be activated until an evaluation of that exact model id on the HELD-OUT split exists, computed by dev/121's deterministic comparator — Curio does not decide that a trained model is better, it refuses to let you activate one you have not evaluated. Activation writes the same account setting AI Settings already writes and records the previous value, so rollback is one click. No cost is invented, no job is simulated, no model judges itself, and nothing here is the deferred `DEC-058` governance surface.**
Backlog: `BL-P5-20260909-56` at the first implementation change.

### The nine preconditions, and where each is discharged

dev/121 §3.9 named them in order and ended *"Until that memo is approved and implemented, AI Settings gets no panel."* This memo is that memo, so the mapping is stated up front rather than left to be inferred:

| dev/121 §3.9 | Discharged in |
|---|---|
| (1) provider capability detection, `Unavailable` rather than a substitute | §3.1 — probed per endpoint, recorded and replayed like the model list; the dev/11:115 posture (*"shows Unavailable rather than substituting an evaluator"*) applied to a provider feature |
| (2) dataset consent and licensing, *a field on the export, not an assumption* | §3.3 — an optional `consent` block per fixture, `identifiers-only` required to be trainable, and a consent event written **before** anything is sent |
| (3) redaction through the same redactor | §3.2 — `report.scrub` over every row, then a re-check that refuses the build |
| (4) cost disclosure: provider-reported or unknown, never a Curio estimate | §3.5 |
| (5) job status and cancellation | §3.4 — the provider owns the job, Curio records what it said and when |
| (6) trained-model versioning as a `model_catalog` entry labelled with its training digest and date | §3.6 |
| (7) held-out evaluation gates using *this* comparator | §3.7 |
| (8) activation as an explicit AI Settings choice | §3.7 |
| (9) rollback | §3.7 |

### The two open questions this touches, and how it stays inside them

**`OQ-010` — which data classifications may be sent to which remote provider, and who approves a destination — is open**, and its recorded default posture is *"Treat unclassified/restricted context as ineligible for remote egress; require an approved destination and never fall back from local to remote implicitly."* A training upload is remote egress of content, so this memo must answer to it rather than walk past it. It stays inside the posture in four ways, and **it does not close `OQ-010`**:

1. The content is **classified before it moves**: only fixtures declaring `consent.dataContent: "identifiers-only"` are eligible, and what that means is written down and test-asserted (§3.3). Nothing unclassified is eligible, which is the posture's first clause.
2. The content is **repo-authored** — prompts, expected graphs and plan targets, under the repository's own MIT licence — and carries dataset **identifiers**, never dataset rows, columns, geometry or files. The third-party dataset licences (*Open Data*, *Project Sidewalk API terms*, *Copernicus licence*, *Research use*) are therefore not implicated by what is sent.
3. The destination is **approved by the only person who can approve it**: the account holder's own configured endpoint, named to them on screen before they consent. Curio ships no default endpoint precisely so that *"an unconfigured instance"* never *"silently send[s] user data to a third party nobody chose"*, and this lane inherits that.
4. There is **no implicit fallback**: nothing is uploaded without an explicit consent act, and no failure path substitutes a different destination.
The one thing `OQ-010` would still have to settle — whether a *user's own* dataflow content may be sent — is exactly what §2 refuses and F2 tracks.

**`OQ-009` — single-process topology, and which durable lease owner is authoritative — is open**, and dev/115 recorded that adopting a durable store before the topology is decided *"pre-empts OQ-009"*. This design does not pre-empt it: there is no queue, no scheduler, no lease and no worker. The long-running work belongs to the provider; Curio keeps a per-account file record and asks the endpoint when someone looks (§3.4). A multi-instance deployment changes nothing about it.

### Risks it touches, and the controls carried over

- **`RISK-EVAL-001`** (*"stale, self-referential, unapproved, or unbudgeted evaluation falsely certifies"*) — the gate is deterministic code over the held-out split, pinned to the trained model id and the fixture digests, **stale-refusing** by digest, and it activates nothing on its own (§3.7).
- **`RISK-MODAL-001`** (*"ambiguous cogs, nested dialogs, stale scope, or inaccessible dirty/conflict states cause the wrong policy to change"*) — one dialog shell, no nested dialog, a labelled disclosure, the section's own controls and its own save, status carrying the time it was read, and each consequence in text rather than a tooltip (§3.8, §5).
- **`RISK-COST-001`** (*"fail-closed unknown pricing"*) — there is no budget to fail closed on: Curio does not meter, cap or bill, so an unknown price means no figure is shown, not a refused job (§3.5).
- **`RISK-SECRET-001`** — the lane never reads, receives, stores or returns a credential; `UserOut` has no field for one, and the provider config is resolved server-side as every other provider call resolves it.
- **`RISK-SHARE-002`** — nothing here becomes a shared surface: the record is per-account and no share payload gains a field.

### What it is not, in `DEC-058`'s terms

The reserved governance surface is Prompt Editor, Prompt Quality, Prompt Audit, evaluation suites/fixtures/runs with their pinning scheme, immutable release, and an append-only integrity-linked **governance history** (dev/87 §4). This memo introduces none of them: no suite record, no second pinning scheme, no release verb, no reveal/export path over protected content, and the held-out gate is deliberately **not** called a release gate. The training record is an operational record in the usage ledger's tradition — *"a record, not a gate"* — and it makes no compliance claim.

One rule from that contract does apply and is adopted rather than argued away: dev/87's *"Protected-content reveal and **every export** append an audit record (who, what, when) before the content is served."* The consent event **is** that record, and §3.3 requires it to be written and flushed **before** the first byte leaves.

A boundary worth stating because the names collide: **AI Settings is not the `DEC-025` six-screen agent-settings shell.** dev/11's screens (Cost, Quotas, Resource policy, and the deferred Prompt trio) are a different surface, and dev/11 explicitly puts *"provider-credential editing in these screens"* out of its own scope. This panel goes where the provider and the model already live — `AiSettingsModal.tsx`, beside Connection keys — and adds nothing to that shell.

---

## 1. Problem Statement

**The measurement exists and nothing consumes it.** dev/121 built 31 reviewed prompt fixtures, a deterministic comparator, and an export that writes prompt → expected-dataflow pairs under train/validation/held-out splits. It also, deliberately, built no way to use them: *"There is no train verb anywhere"*. So the held-out split has no consumer, the export has no reader, and the one question a user with a weak local model actually asks — *can I make this model plan Curio dataflows properly?* — has no answer in the product.

**The evidence that it is worth asking.** The owner's field test of a small local model (2026-09-08) produced broken links, a 400 from generated fetch code, mid-reply stalls and truncated JSON. Curio's answer so far has been to make the runtime survive that: grounding refuses fabricated sources, Solve re-runs and corrects, the plan grammar refuses what it cannot parse. Those are the right defences and they stay. But a model that has never seen a `dataflowPlan` block is being asked to produce one from a prose instruction, and the cheapest fix for that specific failure is the one every other part of the industry uses: show it a few hundred correct examples.

**What is currently unclear or absent.**
- Whether the configured endpoint can fine-tune at all. Today nothing asks, and a hand-written table of "which providers support tuning" would drift exactly the way the model-id table drifted (`routes.py:122-160`).
- What may legitimately be sent. The fixtures' prompts are repo-authored; the datasets they *name* are third-party with heterogeneous licences (`datasets/*/manifest.json` carries `license` values including *Open Data*, *Project Sidewalk API terms*, *Copernicus licence*, *Research use*). Nobody has written down that a training row carries dataset **identifiers** and never dataset **content**, which is the whole licensing argument.
- What a trained model is, once it exists. It is a model id that only this account can use, produced from a specific corpus at a specific time — and Curio's model surface currently records only "what the endpoint reported", with a doctrine that *"presenting a recording as the present tense is how you save a model the endpoint no longer has"* (`docs/AGENT-CATALOG.md`).
- What stops someone activating a model nobody evaluated. Nothing, today, because nothing can be activated.

**Expected behaviour.** AI Settings gains a **Model Training** section. Opened against an endpoint with no tuning surface, it says so in one sentence and offers nothing. Opened against one that has it, it shows what the training set would be (which fixtures, how many rows, what will leave the install), takes an explicit consent, starts a job at the provider, reports its status and lets it be cancelled, records the trained model with its provenance, refuses activation until a held-out evaluation of that model exists, and — once activated — offers one-click rollback to the model that was configured before.

## 2. Scope

**Included.**
- A deep link, so a refusal elsewhere can point here: `ConnectionKeysFocus.section` widens from a single literal to `"connection-keys" | "model-training"` (the subscriber already filters on it), which is the smaller change than a second event bus.
- Provider capability probe: `app/agents/providers.py` gains `fine_tuning_capabilities(config) -> FineTuningCapabilities` and the four job primitives (`create_fine_tuning_job`, `get_fine_tuning_job`, `cancel_fine_tuning_job`, `upload_training_file`), implemented for the OpenAI-compatible family and reporting an honest `Unavailable` reason for the rest.
- Capability recording: `app/agents/model_catalog.py` gains the same replay treatment for the probe result it already gives model listings (per account, per provider identity, labelled with when it was true).
- `app/agents/training/` (new, small, pure where it can be): `dataset.py` (build chat-format rows from approved fixtures via the oracle), `consent.py` (what is being sent, the statement, the digest), `records.py` (the on-disk job record with its append-only event list), `gate.py` (the held-out evaluation gate), `service.py` (the one orchestration seam the routes call).
- `services.py`: one new public wrapper `roster_block(templates, *, notes_agent=False)` over the existing `_available_templates_block`, so a training example's system turn is composed by the SAME formatter the runtime uses (`DEC-062`).
- Routes under `app/agents/routes.py`: `GET /api/agents/training/capability`, `POST /api/agents/training/dataset/preview`, `POST /api/agents/training/jobs`, `GET /api/agents/training/jobs`, `GET /api/agents/training/jobs/<jobId>`, `POST /api/agents/training/jobs/<jobId>/cancel`, `POST /api/agents/training/jobs/<jobId>/activate`, `POST /api/agents/training/jobs/<jobId>/rollback`.
- `utk_curio/tools/agent_eval.py`: `--model <id>` (evaluate a model other than the account's configured one) and `--gate-for <jobId>` (write the gate record beside the training record). Both are additive.
- Frontend: `src/components/training/ModelTrainingSection.tsx` embedded in `AiSettingsModal.tsx` as a collapsed `<details>` whose body mounts only while open (the dev/116 deviation, followed deliberately: *"a closed section adds no fields, buttons or comboboxes to the modal's accessibility tree"*), plus `src/api/trainingApi.ts` — a light module beside `connectionKeysApi.ts` rather than a method on `agentsApi`, for the dev/91 reason that file records: *"nothing here drags the vega-heavy `agentsApi` into a settings screen."* The section owns its own state and its own controls and does not join the modal's `handleSave`, exactly as `ConnectionKeysSection` does. Refusals are read off `apiFetch`'s thrown error (`.status` / `.body`), the 409 pattern that section already uses.
- Fixture schema: an optional `consent` object (declared, so `additionalProperties: false` still holds) recording what a row carries and under which licence; the 31 shipped fixtures get `dataContent: "identifiers-only"` and the repo licence.
- Docs: `docs/AGENT-CATALOG.md` §7's fine-tuning paragraph is replaced by a real subsection; `docs/CONTRIBUTING.md` gains the deterministic training tests; ledgers at closure.
- Tests: capability probe and its refusals, dataset build (approval, split, oracle exclusion, scrub, digest), consent refusals, record lifecycle and event append, the gate's four refusals, activation/rollback, the routes, the CLI flags, and a jest test for the panel's three states.

**Out of scope (tracked, not silently dropped).**
- **Training a model locally.** No GPU story, no weights, no LoRA. If the endpoint cannot tune, Curio cannot tune for it.
- **Gemini's `tunedModels` and Anthropic.** Gemini's tuning surface has a different shape and would need its own probe and job mapping; Anthropic publishes no tuning endpoint at all (see the Evidence above). Both report Unavailable with their own reason; Gemini is follow-up F2 if demand appears.
- **Any judgement about quality.** Curio will not compute a pass mark for a trained model, rank it against the base model, or recommend activation. It reports the evaluation and refuses activation without one.
- **Training on a user's own dataflows.** The consent shape is defined so it *can* be extended, and the builder refuses any fixture whose `consent.dataContent` is not `identifiers-only`. Enabling user-authored training data is follow-up F3 and needs its own consent UI.
- **The deferred `DEC-058` governance surface.** No Prompt Editor, no Prompt Quality screen, no compliance audit, no immutable release, no append-only *governance* history. The training record is an operational record like the usage ledger; it makes no compliance claim and gates no publish.
- **Closing `OQ-010` or `OQ-009`.** Both stay open. This memo stays inside their recorded default postures (see above) and says so; it does not decide the data-classification policy for remote providers, and it introduces no durable queue owner.
- **A budget or quota for training.** `DEC-037`'s evaluation sub-budget is an account-scope Cost concept in the deferred governance surface; nothing here adds a budget, and nothing here is refused for spend.
- **Prompt-level training** (fine-tuning the *instruction* rather than the model) and **automatic re-training** on a schedule.
- **Metering or billing.** Unchanged: *"Curio does not meter, cap, or bill agent runs"*; a training job is billed by whoever owns the key.

## 3. Recommended Implementation Approach

### 3.1 Capability is probed, never tabulated (`providers.py`)

```python
@dataclass(frozen=True)
class FineTuningCapabilities:
    supported: bool
    reason: str                    # always populated; the endpoint's own words when it spoke
    base_models: tuple[str, ...]   # tunable base models, when the endpoint says
    surface: str                   # "openai_compatible_v1" | "" (unknown)
    probed_at: str
```

`fine_tuning_capabilities(config)` dispatches on `api_type` exactly as the existing functions do:

| `api_type` | How the answer is obtained |
|---|---|
| `openai_compatible` | List one job through the `openai` SDK the module already uses (`client.fine_tuning.jobs.list(limit=1)`). It answers → supported. A 404/405/501 → not supported, quoting the status. A 401/403 → *"this key cannot list fine-tuning jobs"* — a scope answer, not a capability answer, and said as such. A connection error → not supported *right now*, with the reason. |
| `anthropic` | Not supported. Reason names the fact rather than a guess: the Claude API publishes Messages, Batches, Token Counting, Models, Files, Skills and the beta Agents/Sessions/Environments, and no tuning endpoint. |
| `gemini` | Not supported by this build. Reason: Gemini tunes through `tunedModels`, a different contract Curio has not implemented (F1). Worth noting for whoever does: `list_provider_models` deliberately **filters tuning-only Gemini models out** (`providers.py:282-287` — offering one as a chat model fails at the first agent run), so a Gemini training lane needs that filter's inverse, not its reuse. |
| `testing` | Supported, answered from the scripted provider, so the whole lane is testable with no network. |

The result is recorded per account and provider identity by `model_catalog`, and replayed **labelled with the date it was true** when a fresh probe is impossible — the same rule the model list obeys, for the same reason.

**Where these calls go, stated rather than implied.** Every fine-tuning call is made by the provider SDK inside `providers.py`, exactly like `run_chat_completion` and `list_provider_models`, and therefore **does not pass through `app/agents/egress.py`**. That is the existing posture and it is the right one here: the agents' egress chokepoint exists to police URLs a *model* chose (`egress.py`'s own words — a trusted host may be minted by deployment configuration and *"never model output"*), whereas the provider endpoint is one the account holder typed into AI Settings. It is also the only posture available: `egress.fetch` has no request body and caps responses at 256 KiB, so it cannot express a training-file upload, and nothing else in the backend uploads a file to an external API today. The memo names this so a later reader does not mistake the bypass for an oversight; the compensating rule is §3.3 — the destination host is shown to the user before anything is sent, and nothing is ever sent to a host they did not configure.

The four job primitives are thin and typed: `upload_training_file(config, name, content_bytes) -> str`, `create_fine_tuning_job(config, *, training_file, base_model, suffix) -> FineTuningJob`, `get_fine_tuning_job(config, job_id) -> FineTuningJob`, `cancel_fine_tuning_job(config, job_id) -> FineTuningJob`, where `FineTuningJob` is `(id, status, base_model, trained_model, trained_tokens, error, raw_status)`. Statuses are normalized to `queued | running | succeeded | failed | cancelled` and `raw_status` keeps the endpoint's own word, because a status Curio has not seen before must not read as a status it has.

### 3.2 The training set is the oracle's answer, and only for approved fixtures (`training/dataset.py`)

One row per fixture, in the chat shape the fine-tuning surface takes:

```json
{"messages": [
  {"role": "system",    "content": "<preamble + instruction + TAIL_INSTRUCTION + roster block>"},
  {"role": "user",      "content": "<the fixture's prompt>"},
  {"role": "assistant", "content": "<oracle.plan_for(fixture).as_reply()>"}
]}
```

Four properties, each deliberate:

1. **The target is the runtime's own contract.** `oracle.plan_for` produces the exact `curio.v1` block `content.parse_dataflow_plan_verbose` accepts. There is no second idea of a correct answer, and a target that would not parse cannot be written — the builder re-parses every target through the production parser before the row is kept, and refuses the row otherwise.
2. **What the contract cannot express is excluded by construction.** `plan_for` raises `Unrepresentable` for an interaction edge, so the eight T2 fixtures are omitted with their reason recorded in the record — not trained on a weakened graph. Training a model to emit something the parser refuses would be actively harmful.
3. **The system turn is composed by the runtime's formatter.** `services.roster_block(...)` over a landscape built from the fixture's `required.packages` ∪ builtin, plus the coordinate's own prompt bytes. The system turn's digest is recorded, because a model trained against one instruction and served another is a different experiment (dev/95 already pins those bytes).
4. **Approval and split are gates, not filters.** The builder calls `export.rows_for_split(..., split="train", purpose="training")`, which already refuses the held-out and validation splits by name and refuses unapproved prompts. The builder adds no way around either.

Every row is passed through `report.scrub` and then re-checked: if `source_grounding.credential_literals` still finds anything, the build **refuses** rather than uploading a redacted-looking row. The result is a `TrainingSet(rows, jsonl_bytes, sha256, fixture_ids, excluded, instruction_sha256, roster_digest)`.

### 3.3 Consent is an act, and the record says what it covered (`training/consent.py`)

The preview endpoint returns exactly what will leave the install: the row count, the byte count, the fixture ids, the destination **host** (not the URL, not the key), the licence line for each fixture, and the fact that rows carry dataset **identifiers** and never dataset content. Starting a job requires that the client echo the preview's `rowsDigest` and a typed confirmation; a mismatch is a 409, so a set that changed under the user cannot be consented to by accident.

**Ordering, not just presence.** The consent event is appended to the record and flushed **before** the first byte is uploaded — dev/87's rule that *"every export append[s] an audit record (who, what, when) before the content is served"*, adopted here because an export is exactly what this is. A crash between the two therefore leaves a record that says what was consented to and no record of a submission, which is the honest failure: it can be read as "consented, never sent" rather than leaving a silent upload behind.

The licensing argument, recorded per fixture in the new optional `consent` block and asserted by a test:

- The prompt, the expected graph and the target plan are repo-authored (`LICENSE`: MIT, Urban Toolkit).
- `required.datasets` are catalog **ids**; no row carries a row, a column, a geometry or a file from any dataset. The datasets' own licences (*Open Data*, *Project Sidewalk API terms*, *Copernicus licence*, *Research use*) are therefore not implicated by the export, and the memo says so where someone will find it.
- `consent.dataContent` must be `identifiers-only` for a fixture to be trainable. A future user-authored fixture carrying their own node code would be `user-content`, which the builder refuses until F3 gives it a consent surface of its own.

### 3.4 The provider owns the job; Curio owns the record (`training/records.py`, `service.py`)

`.curio/users/<key>/agents/training/<jobId>.json`, one file per job, with an **append-only `events` list** and projections recomputed from it. `jobId` is minted by Curio and validated against a `^[A-Za-z0-9-]{8,64}$` pattern before it reaches the filesystem, the discipline `sessions.py`'s `SESSION_ID_RE` exists for: any value that becomes a path segment is checked first, never trusted. The provider's own job id is a field, never a filename.

```json
{"recordVersion": 1, "jobId": "train-20260909T161200Z-a1b2",
 "provider": {"apiType": "openai_compatible", "baseUrlHost": "api.example.com", "baseModel": "..."},
 "dataset": {"split": "train", "rows": 9, "bytes": 41234, "sha256": "...", "fixtureIds": ["..."],
             "excluded": [{"fixtureId": "07-...", "reason": "interaction-edge"}],
             "instructionSha256": "...", "rosterDigest": "..."},
 "consent": {"grantedAt": "...", "statement": "...", "rowsDigest": "...", "destinationHost": "api.example.com"},
 "providerJobId": "ftjob-...", "status": "running", "rawStatus": "running",
 "trainedModel": null, "usage": {"trainedTokens": null}, "cost": null,
 "evaluation": null,
 "activation": {"activatedAt": null, "previousModel": null, "rolledBackAt": null},
 "events": [{"at": "...", "kind": "consented"}, {"at": "...", "kind": "submitted", "providerJobId": "ftjob-..."}]}
```

No background thread. A fine-tune runs for minutes to hours at the provider, so the provider is the job owner: `GET .../jobs/<jobId>` asks the endpoint, folds the answer into the record as an event, and returns the projection. This survives a restart for free, needs none of `agent_jobs.py`'s liveness machinery (that module is attachment-scoped with a 15-minute finished-TTL and a 2-job cap, all of it wrong for this), and cannot leave a phantom "running" job behind — the record's status is always what the provider last said, with the time it said it.

Cancellation calls the endpoint's cancel and records the answer. A cancel the endpoint refuses (already succeeded, already failed) is reported as such rather than forced locally.

### 3.5 Cost is disclosed, never invented

Before: the row count, the byte count, and the sentence that the provider bills per trained token at a rate Curio does not know. After: `trained_tokens` **as the provider reported it**. A USD figure appears only if the operator passes a rate (`--price-per-mtoken` at the CLI, or a rate field in the start request), and it is then labelled `operatorSupplied`, exactly as dev/121's report does it. The reason is the standing one: *"no USD figure is computed, because Curio has no price table and would have to invent the numbers."*

### 3.6 The trained model is a model, labelled with where it came from

On success the trained model id is written by `model_catalog` into a sibling of its suggestions file — `.curio/users/<key>/trained-models.json`, keyed by the same `provider_key(api_type, base_url)` identity — carrying `origin: "trained-in-curio"`, the `jobId`, the dataset digest and the date. A sibling rather than a new section inside `model-suggestions.json`, because that file's whole contract is *"only ever a recording of what an endpoint said about itself"*; a model Curio caused to exist is a different kind of fact and mixing them would blur the doctrine that makes the replay trustworthy. The AI Settings dropdown reads both and labels each for what it is. So it appears in AI Settings' model dropdown like any other model the endpoint serves, and — per the standing doctrine — it is labelled with what it is and when that was true rather than presented as a bare id. If the endpoint later stops serving it, it reads *(not listed)* like any other saved model, which is the existing behaviour and the honest one.

### 3.7 Activation is gated by an evaluation the model did not perform (`training/gate.py`)

`POST .../activate` refuses unless a **gate record** exists for that exact trained model id, and the gate record is written by dev/121's live runner:

```
export CURIO_EVAL_LIVE=1
python -m utk_curio.tools.agent_eval run --model ft:...:curio-plans:abc --tier T0 \
    --only <the heldout fixtures> --gate-for train-20260909T161200Z-a1b2
```

The gate record pins the trained model id, the fixture digests of the **held-out** split, the run id, the score per fixture and the category histogram. Four refusals, each its own message:

| Refusal | Why |
|---|---|
| no gate record | *"activate what you have not evaluated"* is the one thing this panel exists to prevent |
| the gate names a different model id | a report about the base model says nothing about the trained one |
| the gate's split is not `heldout` | validating on what you trained on measures memorisation (`DEC-077`) |
| the gate's fixture digests do not match the corpus | the examples moved since the evaluation, so the evaluation is stale |

**What the gate is not.** It is not a threshold. Curio does not decide that a trained model is good enough — no pass mark exists that anyone has justified, and inventing one would be the platform judging model quality on the user's behalf. The gate says *"you have evaluated this exact model on data it did not train on, and here is what it scored"*; the decision is the person's. And the score is computed by the deterministic comparator, so **no model — least of all the candidate — grades the candidate**: `DEC-055`'s report-only boundary and `DEC-028`'s self-certification firewall are untouched, and dev/11's *"a candidate cannot judge/approve itself"* survives into training as written.

Activation itself writes the account's `llm_model` through the same path AI Settings already uses (`PATCH /api/auth/me` → `users/services.py:patch_me`, whose semantics matter here: an absent field keeps, an empty string clears, and a guest is refused), recording the previous value on the record. Rollback restores it and records the time. Neither touches the key — and the key cannot leak through this lane by construction, because `UserOut` has no field for it at all: `GET /api/auth/me` reports only `has_llm_api_key`.

### 3.8 The panel (three states, no fourth)

`ModelTrainingSection` is a collapsed `<details>` in AI Settings whose body mounts only while open (dev/116's recorded deviation, reused on purpose).

- **Unavailable.** One sentence naming the endpoint and its reason, and nothing else. No disabled buttons pretending a feature exists, no "coming soon".
- **Ready.** What the training set is (fixtures, rows, bytes, the excluded ones with reasons, the destination host, the licence line), the consent control, and Start. If no fixture is approved yet, it says that instead — the corpus ships `pending-owner-review`, so this is the state a fresh install is in, and it points at the review rather than offering an empty upload.
- **A job exists.** Status with the time it was read, Cancel while cancellable, the trained model id when there is one, the gate's verdict or the command that would produce one, then Activate and — after activation — Rollback.

### 3.9 Alternatives considered

- **A provider table instead of a probe.** Rejected by precedent and by fact: the model-id table drifted the moment a provider changed its lineup (`routes.py:122-160`), and "OpenAI-compatible" spans endpoints that do and do not implement tuning. A probe is one cheap read-only call and it cannot be wrong about the endpoint in front of it.
- **A background training job in `agent_jobs.py`.** Rejected on four counts: it is keyed by `(user_key, attachment_id)` and a training job has no attachment; its `JOB_KINDS` are the two Solve kinds; it holds a 15-minute finished-TTL and an in-memory event deque, both far shorter-lived than a fine-tune; and it has **no cancellation primitive at all** (Solve cancels through a flag on the persisted builder session), while cancellation is one of the nine preconditions. `build_jobs.py` does have phases and a real `cancel_job`, but it too is a local worker driving local steps. Neither fits, because the work is not ours: the provider is the job owner and we hold its id.
- **Train on all 31 fixtures.** Rejected twice over: the held-out and validation splits are how the result is judged (`DEC-077`), and the eight interaction-edge fixtures have no representable target, so training on them would teach the model to emit blocks the parser refuses.
- **A quality threshold as the activation gate.** Rejected: no threshold is justifiable today, and a platform-set pass mark would be Curio judging models for the user. Requiring *an evaluation* is enforceable and honest; requiring *a good score* is not.
- **Let the Generated Content Evaluator score the gate.** Rejected outright: `DEC-055` gives it no authority, and a model in the approval path is the exact thing dev/11 forbids.
- **Ship the panel with the job lane stubbed.** Rejected by the brief that created this follow-up: *"Do not add a cosmetic or nonfunctional panel."* Where the lane cannot be real, the panel is absent.

### 3.10 What this is NOT

Not local training. Not a quality verdict. Not the `DEC-058` governance surface. Not a metering or billing feature. Not a change to the plan contract, the roster, any prompt byte-pin, any fixture's expected graph, or the comparator. Not a way to train on user data — that path is refused until it has its own consent surface.

## 4. Data and State Handling

**Sources of truth.** The endpoint is the truth for capability, job status, trained model id and trained tokens; Curio records what it said and when. The fixtures on disk are the truth for the training set (approval, split, digest). `model_catalog` is the truth for what models this account can pick. The user row's `llm_model` is the truth for what is active. The gate record is the truth for whether a trained model has been evaluated.

**Derived values.** The training set and its digest are pure functions of (approved fixtures, oracle, instruction bytes, roster) — recomputable, so a record can be checked against the corpus later. The record's projections are folded from its events.

**States.** *Loading*: capability and status are read on open and on demand, never polled on a timer — a fine-tune does not need a spinner every second. *Empty*: no approved fixtures, no job, no capability — each has its own sentence. *Error*: a provider error is shown with the endpoint's own message and status; a refusal (consent mismatch, gate missing) is a 409 with the reason. *Success*: a trained model id, a gate verdict, an activation.

**Staleness.** A capability replay is labelled with its date. A status is labelled with when it was read. A gate whose fixture digests no longer match the corpus is refused as stale rather than honoured. A record whose dataset digest cannot be reproduced from today's fixtures is still readable — it says what it trained on — but cannot be used to justify a new activation.

**Concurrency.** One in-flight job per account (a second start is a 409 naming the first), because a fine-tune costs money and a double-click must not spend twice. Records are written with the same write-then-rename discipline the other per-user stores use.

## 5. UI and UX Requirements

The section is titled **Model training** and sits below **Connection keys** in AI Settings. Copy is plain and never speculative: "This endpoint does not offer fine-tuning" rather than "unsupported"; "9 of 31 examples are approved and can be used" rather than a bare count; "Sends 9 rows (41 KB) to api.example.com" above the consent control, naming the host the user themselves configured.

Accessibility: the `<details>` is a real disclosure with a labelled summary; status is a `role="status"` live region so a change is announced; the consent control is a labelled checkbox plus a Start button that stays disabled until it is checked; Cancel, Activate and Rollback are ordinary buttons with `aria-describedby` pointing at the sentence that explains what each does. Every destructive-ish action (Cancel, Activate, Rollback) states its consequence in that sentence rather than in a tooltip.

No spinner theatre: a job that is queued says *queued*, with the time it was last read and a Refresh control. Nothing animates for hours.

## 6. Edge Cases

- **No approved fixtures** (the shipping state) → Ready-state copy points at the review; Start is absent, not disabled-with-a-tooltip.
- **Every train-split fixture unrepresentable** → the build refuses with the list, rather than uploading an empty file.
- **A fixture edited after approval** → its digest no longer matches, so `export` refuses it and the record's `excluded` names it.
- **The endpoint's key lacks tuning scope** (401/403 on the probe) → reported as a *scope* answer, distinct from "no such feature", because the fix is different.
- **The endpoint offers tuning but refuses the base model** → the provider's own 400 message is shown; Curio does not guess a substitute base model.
- **A credential-shaped literal survives scrubbing** → build refuses (§3.2). A prompt is repo-authored text, so this should be impossible; if it happens, something is wrong that an upload must not paper over.
- **The job fails at the provider** → status `failed` with the provider's error; no trained model; Activate absent.
- **The job succeeds but the endpoint stops serving the trained model** → it reads *(not listed)* in the model dropdown, the existing behaviour for any saved-but-absent model.
- **A gate for the base model, or for another job's model** → refused by id (§3.7).
- **A gate run against the *train* split** → refused by split; measuring on what was trained on is not a measurement.
- **Activation while a job is running** → refused; there is nothing to activate yet.
- **Rollback after the previous model was itself removed** → restores the recorded id and says it may no longer be served, rather than silently leaving the account on the trained model.
- **Two browser tabs** → the second start is a 409 naming the in-flight job.
- **A restart mid-job** → nothing is lost; the next status read asks the provider.
- **The account switches provider while a job runs** → the record keeps its own provider identity; status reads use the record's identity, and the panel says the account has moved on.
- **`api_type: "testing"`** → the whole lane runs against the scripted provider, which is how the tests exercise it.
- **Grounding-refusal texts in training data** — deliberately absent. The targets are plan blocks only; teaching a model to reproduce refusal prose would train it to *narrate* a refusal rather than avoid the cause (`DEC-072` refusals are the runtime's job, not the model's).

## 7. Testing Strategy

**Unit (offline, no stack, no network).**
- `providers`: the capability probe per `api_type` against a faked transport — 200/404/401/connection-error each producing its documented answer and reason; the four job primitives' request shapes and their status normalization (including an unknown `raw_status` staying unknown rather than being coerced).
- `training/dataset`: only approved `train`-split fixtures are included; held-out and validation are refused by name; every target re-parses through `content.parse_dataflow_plan_verbose`; an unrepresentable fixture is excluded with its reason; the system turn contains the coordinate's instruction bytes and a roster block built by `services.roster_block`; the digest is stable across runs and changes when a prompt changes; a planted credential literal makes the build refuse.
- `training/consent`: the preview names host, rows, bytes, fixture ids and licences and no key; a `rowsDigest` mismatch is refused; a fixture whose `consent.dataContent` is not `identifiers-only` is refused.
- `training/records`: events append and never rewrite; projections fold from events; a record round-trips; an unknown `recordVersion` is read but not written to.
- `training/gate`: the four refusals, and the accepting case.
- Fixture schema: the new optional `consent` block validates, `additionalProperties: false` still holds, and all 31 shipped fixtures declare `identifiers-only`.
- Ordering: with the upload made to fail, the record still carries its consent event and carries no submission event — the dev/87 rule proven by its failure mode rather than by reading the code.
- Two greps as tests: no provider→capability table exists in `app/agents/`, and the training package imports no scheduler, queue or thread primitive.

**Integration (in-process Flask client + scripted provider).** The whole lane end to end: capability → preview → consent → start → status → cancel; and capability → preview → consent → start → succeeded → model recorded → activate refused (no gate) → gate written → activate → account model changed → rollback → account model restored. Plus: a second start is a 409; a gate for the wrong model is refused; nothing in any response body contains the API key.

**Browser (opt-in, `examples` marker).** One test: AI Settings opens, the Model training section shows the Unavailable sentence against a testing-provider account configured to report no capability, and shows the Ready state with its row count and host when capability is reported. This is a rendering claim, so it is a screenshot plus an assertion that the copy is present.

**Live (owner-run, never CI).** A real fine-tune costs money and takes hours. Recorded as a scenario the owner runs once against their own endpoint, mirrored by the deterministic tests above (the dev/115 A3 discipline: *"A live failure that the deterministic mirror did not predict is a new fixture, not a prompt tweak"*).

Required before the change is called complete: all unit and integration tests green in `scripts/test.sh --backend-only`; the jest panel test green; the browser test collecting; and the memo's status saying plainly that the live fine-tune is owner-gated and not yet run.

## 8. Acceptance Criteria

1. With an endpoint that has no tuning surface, the panel shows one sentence naming the endpoint's own reason and offers no controls; no request to start a job can be made.
2. Capability is obtained by probing the configured endpoint, recorded per account and provider identity, and replayed labelled with the date it was true. No provider→capability table exists in the code, and a test greps for one.
3. The training set contains only fixtures that are `split: "train"` **and** `review.status: "approved"`; held-out and validation exports are refused by name; the eight interaction-edge fixtures are excluded with `reason: "interaction-edge"`.
4. Every assistant target re-parses through the production plan parser; a target that would not parse cannot be written.
5. The preview names the destination host, the row and byte counts, the fixture ids and their licences, and states that rows carry dataset identifiers and never dataset content. Starting requires echoing the preview digest; a mismatch is a 409.
6. No API key appears in any training response, record, or log line; a credential-shaped literal surviving scrubbing refuses the build.
7. A job's status is always what the provider last said, with the time it said it; cancellation calls the provider and records its answer; a restart loses nothing.
8. `trained_tokens` is reported as the provider gave it, and no USD figure appears unless an operator supplied a rate, which is then labelled as theirs.
9. The trained model id is recorded in the model catalog with `origin: "trained-in-curio"`, its job id, the dataset digest and the date, and appears in the model dropdown like any other model.
10. Activation is refused without a gate record for that exact model id, on the held-out split, with matching fixture digests — four distinct refusal messages. The gate's scores come from dev/121's deterministic comparator; no agent or model participates in the approval path, and the build entry records that the `DEC-055` boundary was not bypassed.
11. Activation records the previous model; rollback restores it and says so if that model is no longer served.
12. The consent record is written and flushed before the first byte is uploaded, and a test proves the ordering by failing the upload and asserting the record exists without a submission event.
13. Nothing in the lane introduces a queue, scheduler, lease or worker (so `OQ-009` is not pre-empted), and no fixture without `consent.dataContent: "identifiers-only"` can be uploaded (so `OQ-010`'s default posture holds). Both are asserted, and the build entry records that neither open question was closed by this work.
14. The build entry records, per tracking rule 17, that the `DEC-055` report-only evaluator boundary was not bypassed: no agent and no model participates in the gate or the activation path.
15. Ledgers at closure: dev/03 `DEC-078`, dev/00 row, `BL-P5-20260909-56`, `3.1`, dev/121 F1 closed, docs/09 note, and the user docs updated.

## 9. Recommended Commit Breakdown

1. **The provider contract** — `FineTuningCapabilities`, `FineTuningJob`, the probe and the four primitives, the `model_catalog` recording, and their unit tests against a faked transport.
2. **The training set** — `training/dataset.py` + `consent.py`, the fixture schema's optional `consent` block, the 31 fixtures' `identifiers-only` declaration, `services.roster_block`, and their tests.
3. **Records and the service** — `training/records.py` + `service.py`, the routes, and the in-process integration test of capability → preview → consent → start → status → cancel.
4. **The gate, activation and rollback** — `training/gate.py`, the `agent_eval` `--model` / `--gate-for` flags, the four refusals, activation and rollback, and the second half of the integration test.
5. **The panel** — `trainingApi.ts`, `ModelTrainingSection.tsx`, its embedding in AI Settings, the jest test of the three states, and the browser test.
6. **Docs + ledgers** — `docs/AGENT-CATALOG.md`, `docs/CONTRIBUTING.md`; tracking commit for dev/03 `DEC-078`, dev/00, `BL-P5-20260909-56`, `3.1`, dev/121 F1, docs/09.

Each commit is a pathspec commit, no push; `plans/` changes ride separate `tracking dev/122 …` commits.

## 10. Engineering Quality Checklist

- No second vocabulary: the target is the oracle's plan bytes, the system turn is the runtime's roster block, the export gate is dev/121's, the redactor is `utk_curio/common/redaction.py` through `report.scrub`.
- No provider→capability table; the probe is the only source, and a test enforces it.
- `app/agents/training/` keeps `dataset`/`consent`/`gate`/`records` pure (values in, values out); only `service.py` touches the store and the provider, and nothing there imports `app/api`.
- Types explicit and frozen for every value (`FineTuningCapabilities`, `FineTuningJob`, `TrainingSet`, `ConsentStatement`, `GateRecord`).
- Every outbound call goes through `egress` with the configured host as `trusted_host`; nothing reaches a host the user did not configure.
- One in-flight job per account; records written write-then-rename; events append-only.
- No spinner-driven polling; every status carries the time it was read.
- Accessibility: a real disclosure, a live region for status, labelled controls, consequences in text.
- The `DEC-055` report-only boundary is not bypassed: no agent or model is in the approval path.
- Tests cover each refusal by name, the leak checks, the digest stability, the lifecycle, and the panel's three states.
- Docs say plainly what the gate does and does not claim, and that a live fine-tune is owner-gated.

## Open questions for the owner (non-blocking — defaults stated)

1. **Which base model.** Default: the panel offers the base models the endpoint's probe reported, and refuses to guess when it reported none (the user types one, as with the Model field).
2. **Where the gate record lives.** Default: beside the job record, `.curio/users/<key>/agents/training/<jobId>.gate.json`, written by the eval runner.
3. **Suffix naming.** Default: `curio-plans`, so a trained model is recognisable in the endpoint's own console.
4. **Whether one in-flight job per account is too strict.** Default: keep it; a fine-tune costs money and the failure mode of a double-click is worse than the inconvenience.
5. **Validation split.** Default: v1 sends only the train split and does not pass a `validation_file`; the validation split stays for offline comparison. Passing it to the provider is F5.

## Follow-ups (recorded, not delivered)

- **F1 — Gemini `tunedModels`** as a second job surface, if demand appears.
- **F2 — user-authored training data**: enable `consent.dataContent: "user-content"` with its own consent surface, licence capture, and a redaction pass over node code (this is the one that needs real care).
- **F3 — a second corpus**: fixtures generated from a user's own dataflows, which is where the fine-tuning story becomes genuinely valuable and where F2's consent work is the prerequisite.
- **F4 — evaluation before and after**: run the gate against the base model too, so the report shows both without Curio drawing a conclusion.
- **F5 — pass the validation split** to endpoints that accept a `validation_file`.
- **F6 — training the instruction, not the model**: the same fixtures could measure a prompt change; that is the `DEC-058` Prompt Quality surface's job, not this one's.
