# dev/114 — A data-loading node's source is never the model's word: Node Builder invents local filenames (`pd.read_csv("bras_ibge_data.csv")`) because nothing between "load this data" and the review card resolves, verifies, or checks the source — ground it at runtime

**Status: IMPLEMENTED (2026-09-08) on `imp/agentcatalog` — commits `634ee9a3` (1, source_grounding.py + catalog.search path/loader + node_context thin-ref fix, 75 unit tests), `eaaa079f` (2, the gate at node.create / node.content.write (dev/73 mint inherits) / node.template.create / Solve; ONE per-run egress budget + probe cache; `loop_ctx["message"]`; DEC-063 applications six (`dataset.discover` catalog + #269 schema) and seven (`sourceGrounding`); `_mint_candidates_from_delegate`; roster tools += catalog.search, delegatesTo += agent.dataset-finder; 23 route cases), `b219af6a` (3, review-card Source block, shared `verificationChip.tsx`, candidates card `builder` variant, panel wiring, hand-off kind label; jest +12), `fa4aa140` (4, contract copy: Node Builder source ladder, preamble exemplars without bare filenames, Dataset Finder `handoff` card with verdicts; roster pins), `4039f346` (5, docs — `docs/AGENT-CATALOG.md` §3). `DEC-072` minted; backlog `BL-P5-20260908-48` (numbers checked on disk). Backend `test_agents` 1045 green; jest 199 suites / 2296 tests green; `tsc` unchanged (pre-existing notices only). PORT NOTE: implemented against `main`'s agents code on the owner-created `imp/agentcatalog` (from `main` @ `f3bc4f24`), NOT on `feat/agentscatalog` — see Amendment A1 for what that changed (no `node.insert` on this branch; plan-carried content already refused by dev/67-5; the catalog loader is the portable `curio_dataset_path("<id>")`, grounded by id; `docs/AGENTS.md` is `docs/AGENT-CATALOG.md` here; the memo's six commits landed as five). Owner live re-test pending.**

Date: 2026-09-08
Branch / tree: written against `feat/agentscatalog` @ `6b277a87` (line numbers in §1–§3 pin to that commit); **implemented on `imp/agentcatalog`** (owner-created from `main` @ `f3bc4f24`, 2026-09-08) in the shared tree after the owner asked for the temporary worktree to be removed. `main` absorbed feat/agentscatalog through dev/106 (merge-base `6f3c07a8`) and then refactored it; the dev/107–113 mechanisms are NOT on this branch (Amendment A1). `plans/` is untracked on `main`-derived branches — this memo and its ledger rows live on disk only.
Origin: GitHub issue #298 (2026-09-03, reporter on `main`): *"the agent generates Python code that assumes specific local data files already exist (e.g., `pd.read_csv('bras_ibge_data.csv')`) … execution immediately throws a `FileNotFoundError`. The agent should validate file availability, use absolute/verified paths, or write the necessary download logic instead of guessing filenames."* Also `bras_geosampa_boundary.shp`. The reporter ran `main`'s legacy chat; this memo closes the gap on the hookable-agents path (every agent-authored code boundary), and records the legacy caller as the out-of-scope remainder it already is (dev/113 owner instruction: `llmRequest` callers untouched).
Evidence: `utk_curio/llm-prompts/default_preamble.txt:332-352` — the ONLY data-loading exemplar every built-in agent sees reads bare filenames (`pd.read_csv('Milan_22.07.2022_Weather_File_UMEP_CSV.csv', …)`, `gpd.read_file('R03_21-11_…_Selected.shp')`, `rasterio.open(f'Milan_Tmrt_2022_203_{timestamp:02d}00D.tif')`). `node_build_instruction.txt` (19 lines) never mentions files, paths, the Data Catalog, or Dataset Finder; its one data clause (§4, line 11) says a fetch request "is a data-loading template whose content is the fetch code" and nothing about where the source comes from. `_mint_node_create` (`services.py:5927-6002`) validates template, size, title, appearance — never the content's sources. `catalog.search` rows (`tools.py:396-403`) carry `{id, name, format, origin, installed, description}` — no path, no loader snippet — so even a model that searched the catalog could not write a grounded path. `node_context.compose_node_context` (`node_context.py:89-97`) reads `entry.get("id")`/`name` off refs whose real keys are `datasetId`/`dirName` (`datasets/application/mutations.py:830-837`) — every delegated generation today receives `datasetRefs: [{"id": null, "name": ""}]`.
Family: dev/48 (Node Builder composite, `node.create`, reuse-first registry gate) → dev/50 (Dataset Finder, two-lane `datasetCandidates`, DEC-047 user-mediated handoff) → dev/52/63 (Dataflow Builder plan + Solve → `node.content.generate`) → dev/57 (`extract_node_content` at every model-output→node-content boundary) → dev/67-4 (DEC-053: `verify.py` generic endpoint gate, `_verify_candidate_parts` on finder rows) → dev/67-6 (`node_context`, the ONE composer) → dev/72/73 (delegation trace, runtime-minted content review) → dev/94/95 (DEC-063: tool-less children get evidence as INPUTS — five applications) → dev/105 (DEC-067: refusals self-correcting, `ParamRefusal` free rounds) → dev/112/113 (refuse BEFORE mutating; `node.insert`) → **dev/114**.
Design decisions consumed: DEC-006 (review before apply gates graph/dataset mutations), DEC-009 (Dataset Finder selects sources; Node Builder builds the fetch node), DEC-046 (depth-1, tool-less children), DEC-047 (external handoff user-mediated; a child never mints proposals), DEC-053 (the runtime, never the model, verifies external sources — the generic gate covers ANY dataset API), DEC-063 (an instruction must be executable on every path its agent runs on — evidence arrives as inputs), DEC-067 (a refusal must be self-correcting on the path that produced it), DEC-070 (refuse before any spec write). **New decision proposed: DEC-072** — *every agent-authored node content passes ONE runtime source-grounding gate before it can become a proposal or be written by Solve: a local path is grounded only when the user typed it or the Data Catalog resolved it; a URL is grounded only when the runtime probed it this run or an already-verified candidate row carries it; a data-loading node with no source is grounded only when synthetic data was explicitly requested and is labeled as such; anything else is refused with the correction named — never proposed, never written, never described as existing.*
Backlog: `BL-P5-20260908-48` at closure; closes the "unclosed half" dev/67-4 §1 named (`67-4:24-30`: *"the Node Builder writes fetch code around an unverified URL; first contact with reality is the user executing the node"*); the `BL-P5-20260804-03` follow-up line ("capability-first resolution at Dataflow Builder") is touched, not closed.

---

## 1. Problem Statement

**What is broken.** When a user asks an agent for a node that loads data from the web or a public source, the generated content references a local file that does not exist (`pd.read_csv("bras_ibge_data.csv")`, `gpd.read_file("bras_geosampa_boundary.shp")`). The node is proposed, the review card shows plausible code, the user applies it, the sandbox runs it against `CURIO_LAUNCH_CWD` (`sandbox/app/worker.py:44/189`) and throws `FileNotFoundError`. The reporter's expectation is the product's own specification: docs/06 says the Dataset Finder discovers and selects, Node Builder "owns fetch code" for a *verified* external pick, and "missing, malformed, unavailable … sources remain explainable failures".

**Why it happens — four gaps, one per layer.**

1. **Prompt layer.** The shared preamble's worked dataflow (`default_preamble.txt:332-352`) is the only data-loading exemplar any built-in sees, and all three of its DATA_LOADING nodes read bare filenames. Node Builder's own instruction never says where a source may come from. A model reproducing the pattern it was shown is not malfunctioning.
2. **Tool layer.** Node Builder holds `dataflow.read, node.create, node.template.create, node.runtime.read, node.content.write, node.insert` (`builtin.py:184-186`) — no `catalog.search`, no delegate to Dataset Finder (`delegates_to`, `builtin.py:187-202`, points the other way: Dataset Finder → Node Builder). Even a model that wanted to ground a catalog path could not: `catalog.search` rows omit `path`/`loaderSnippet` (`tools.py:396-403`), and the installed-dataset refs `dataflow.read` projects verbatim (`tools.py:489`) are the thin `{datasetId, dirName, origin, …}` shape without path, title, or format.
3. **Runtime layer.** DEC-053 verifies Dataset Finder's external *rows* (`_verify_candidate_parts`, `services.py:6243-6269`) and the evidence rides the card. But the DEC-047 handoff is prose in a suggested prompt (`discovery_instruction.txt:16`), `externalSelection` composes nothing client-side (`agentRunContext.ts:216-221`), and no mint — `_mint_node_create` (`:5927`), `_mint_node_insert` (`:6040`), `_mint_node_content_write` (`:5847`), Solve's `_record_outcome` (`:3966-3989`), plan-carried `content` (`content.py:446-455`) — inspects what the generated code actually opens. The only empirical guard, `validation.validate_candidate` (dev/67-7), is wired to `validate-node` and Simulation Mode, never to a mint.
4. **Context layer.** `compose_node_context` mis-reads the thin ref (`node_context.py:89-97`), so the one grounding input Solve children DO receive about datasets is empty. dev/94's degradation doctrine ("honest absence beats a fabricated neighborhood") is satisfied by accident — the neighborhood is absent because of a key mismatch, not honesty.

**Affected surfaces.** Node Builder attachment runs (canvas, node, connection targets): `node.create`, `node.insert`, `node.content.write` (direct and via the dev/73 runtime mint after `node.content.generate`). Dataflow Builder: plan-carried content at mint, Solve (`write` and `propose` modes), Simulation Mode's solve step. Dataset Finder: the external handoff and the two-lane card. The chat transcript (`AgentChatPanel`), the review card (`AgentReviewCard`), and the candidates card (`AgentDatasetCandidatesCard`).

**Expected behavior.** Every data-loading node resolves its source in order: (1) a path the user supplied; (2) a Data Catalog dataset the runtime resolved (real id → real installed path); (3) an external URL the runtime verified through the DEC-053 gate; (4) synthetic/inline data only when explicitly requested, labeled as synthetic. Discovery (catalog first, then verified external candidates) is presented for review through the existing two-lane surface; the node is created only after confirmation; a source that cannot be grounded is reported as a limitation or a request for a path — never fabricated.

**Why it matters.** Correctness: applied nodes crash on first run. Trust: the review card presents fabricated evidence as reviewable code, which defeats review-before-apply (DEC-006). Weak-model robustness: the owner's gemma4 test (2026-09-08) shows the deployment's models cannot vouch for links (4/5 broken) or request shapes (HTTP 400) — so a fix that lives in prompt wording is no fix (dev/54 doctrine; DEC-067). Consistency: DEC-053 already made "the runtime verifies, never the model" the rule for the finder half; this memo extends the same rule to the builder half, closing the asymmetry dev/67-4 named.

## 2. Scope

**Included**

- New backend module `utk_curio/backend/app/agents/source_grounding.py` — the ONE source-grounding gate (pure scan + verdict; one catalog read behind a seam).
- `services.py`: the gate applied at every agent-authored code boundary — `_mint_node_create`, `_mint_node_insert`, `_mint_node_content_write` (hence the dev/73 runtime content-review mint), Solve `_record_outcome` (write + propose), `_mint_dataflow_plan` (plan-carried `content`), `_mint_node_template_create` (first-node content); the proposal `source` payload on the part; `loop_ctx["message"]` (the current user text — turns persist AFTER the run, `services.py:5637`, so the mint cannot read it from the session); the sixth runtime-supplied-inputs application in `_enriched_delegate_inputs` (`dataset.discover`: catalog rows + reply contract) and a seventh (`node.content.generate` on a data-loading node: `sourceGrounding`); `_mint_candidates_from_delegate` (schema-recognized `datasetCandidates` from a tool-less Dataset Finder child → tool-grounded catalog rows → DEC-053 verification → the part on the PARENT turn); `_candidates_pending_review` (a same-run `node.create/insert` after minting candidates is refused: the user reviews first).
- `builtin.py`: Node Builder `tools += catalog.search`, `delegates_to += agent.dataset-finder` (declaration order keeps Node Content Builder first).
- `tools.py`: `catalog.search` rows gain `path` and `loader` (the datasets domain's `loaderSnippet.code`) for rows whose path the listing already resolved and contained — additive; the description says catalog-lane paths come from these rows only.
- `node_context.py`: `datasetRefs` reads the thin ref shape (`datasetId`, `dirName`, `origin`) and the legacy fat shape.
- Prompts (sha-pinned edits, one deliberate commit): `node_build_instruction.txt` (new §: the source-resolution ladder, synthetic declaration, never invent a filename, the delegate step), `default_preamble.txt:332-352` (the three DATA_LOADING exemplars read a Data-Catalog-shaped `dataset_path` with a comment naming where it comes from — no bare filename remains in any exemplar), `discovery_instruction.txt` §5 (the handoff card is `kind: "handoff"` and carries each row's verification verdict; unverified rows are named as such).
- Frontend: `agentsApi.ts` (`AgentProposalPart.source`, `AgentSourceRef` types); `AgentReviewCard.tsx` (a "Source" block for `node.create`/`node.insert`/`node.content.write` with the verification chip); `content/verificationChip.tsx` (the chip + label extracted from `AgentDatasetCandidatesCard` and reused — no second label table); `AgentDatasetCandidatesCard.tsx` (`variant: "finder" | "builder"` — the confirmation prompt reads "build the data-loading node from …" in a Node Builder chat instead of "hand off to Node Builder"); `AgentChatPanel.tsx` (passes the variant from `attachment.coord`); `AgentChatCard.tsx` (the `handoff` kind gets its label — same shell).
- Tests: backend `test_source_grounding.py` (new, pure), `test_routes.py` (new classes: the #298 regression, catalog path grounding, verified external URL, unavailable source, synthetic, candidates-from-delegate, Solve refusal, plan content), `test_builtin.py`/`test_tools.py` pins, `test_node_context.py` (thin ref), `test_content.py` (source payload), `test_delegation.py` (candidates mint); jest `AgentReviewCard.test.tsx`, `AgentDatasetCandidatesCard.test.tsx`, `AgentChatPanel.test.tsx`, `AgentChatCard.test.tsx`.
- Docs on close (the dev/93 convention): `docs/AGENTS.md` (Node Builder + Dataset Finder paragraphs, the DEC-063 applications list → seven), dev/03 DEC-072 row, dev/00 index row, BL-P5 closing entry, `3.1` status lines, this memo's Status line.

**Must be checked but not changed**

- `verify.py` / `egress.py` (DEC-053 gate and budget — reused as-is; `MAX_CALLS_PER_RUN = 4` bounds every probe this memo adds).
- `delegation.py` (depth-1, tool-less children, `_frame_inputs` — untouched; the sixth/seventh enrichments ride the existing seam).
- `validation.py` (dev/67-7 execute-through — NOT wired to mints here; see §3.7 and follow-ups).
- `datasets/application/listing.py:190-245` (path containment is the datasets domain's; the tool only forwards what the listing already deemed safe), `datasets/domain/catalog_item.py:56-140` (`loader_snippet` is the ONE loader recipe — forwarded, never re-implemented).
- `AgentAttachmentsProvider.tsx` apply bridge, `useAgentCanvasMutations.ts` — unchanged; the apply response shape does not change.
- `_store_proposal`, `_apply_node_create/_apply_node_insert/_apply_node_content_write` — unchanged; the `source` payload is display + provenance, never a pin the apply re-checks (a verified URL going dark between mint and apply is the node's runtime error to report, not a stale proposal — recorded posture).

**Out of scope (explicitly)**

- Background execution / resident services (DEC-064), general prompt validation and governance (DEC-058 Prompt Quality/Audit), optimization/evaluation sub-budgets (DEC-037/DEC-056) — the fix depends on none of them; recorded as untouched.
- Execute-through validation at mint time (dev/67-7 stays on `validate-node` / Simulation Mode) — a probe of the URL's constant prefix is the narrow runtime guard this memo needs; a full request-parameter check (the owner's HTTP 400) is a follow-up (§ follow-ups, F1).
- The legacy `llmRequest` chat callers on `main` (the reporter's actual path) — dev/113 owner instruction; F2.
- Provenance metadata written INTO the spec node (`docs/06:71-72` "carries source/provenance metadata"): `dataflow.nodes` is frontend-owned on save and unknown node fields are not guaranteed to survive; provenance lives on the proposal part, the transcript, and the applied card. F3.
- New card TYPES for the handoff or the install result: the DEC-047 `card` (now `kind: "handoff"`), the dev/72 `delegation` entry, and the `dataset.install` review card in its `applied` state already are those surfaces (§5 reconciles the concepts).
- Package-authored python template sources (`package.draft.apply`) — a different review contract (dev/89/96); F4.
- `dataflow.datasets` ref shape changes, `catalog.search` semantics beyond the two additive fields.

## 3. Recommended Implementation Approach

### 3.1 One gate, one module — `source_grounding.py`

Pure functions, no Flask, no model:

- `scan_sources(code: str, engine: str) -> list[SourceRef]` — for `python`: `ast.parse`; every `Constant` string and the constant prefix of every `JoinedStr` (f-string) is classified `url` (`http://`/`https://`) or `path` (ends with a data-file extension — csv, tsv, json, geojson, shp, gpkg, parquet, feather, tif/tiff, xlsx/xls, nc, zip, gz, pbf, kml, kmz, topojson — or contains a path separator AND a dot-extension); each ref carries `literal` and `line`. `SyntaxError` → a regex fallback over string literals (the same classifier); non-python engines → the regex path. Bounded output (`_MAX_REFS = 32`). Nothing else in a string is a source (column names, URLs inside comments are not literals).
- `GroundingContext` — `catalog_paths: dict[str, CatalogRef]` (resolved path → `{datasetId, title, format}`), `user_paths: set[str]`, `verified_urls: dict[str, dict]` (URL → verification evidence), `synthetic_requested: bool`, `is_data_loading: bool`, `probe: Callable[[str], dict] | None` (the run-budgeted DEC-053 prober), `hints: list[str]` (grant-aware corrective sources to name in a refusal).
- `check_grounding(code, engine, ctx) -> GroundingVerdict` — every `path` ref must be in `catalog_paths` (exact, or the same file under a catalog directory) or `user_paths`; every `url` ref must be in `verified_urls`, or be probed now: `verified` → grounded (evidence recorded), `httpStatus ∈ {401, 403}` → grounded with `requirement: "credential-gated"` (the endpoint exists; docs/06 row contract has the field), anything else (400/404/405/5xx, transport, refused, budget spent) → violation naming the status. A data-loading node with **no** refs: `synthetic_requested` → grounded as `synthetic`; else violation *"no grounded source"*. Returns `ok`, `violations: [str]` (one line each, model-correctable), and `source` (§3.4 payload).
- `synthetic_requested(texts, params)` — `params.get("synthetic") is True`, or any of a fixed word list (synthetic, fake, mock, dummy, sample data, made-up, fabricated, simulated, random data, generate data) in the USER texts only (never in model text — the model may not self-authorize).
- `user_paths(texts)` — the same path classifier over the user's own messages. A **URL in user text is NOT auto-grounded**: the DEC-047 handoff prompt is model-suggested text the user forwards; URLs are grounded by verification only (the runtime probes them — one probe, cached in `loop_ctx` for the run).
- `refusal_text(verdict, ctx)` — the correction the model can act on: each violating literal, why, and the allowed sources — *"use the path the user gave, a `path` from `catalog.search` (granted), a URL the runtime has verified (delegate `dataset.discover` to find and verify candidates), or declare `\"synthetic\": true` if the user asked for made-up data"* — each clause only when that route exists on the refusing run (DEC-067's grant-aware hint rule).

### 3.2 The gate at every boundary (`services.py`)

- `_grounding_context(user_key, project_id, loop_ctx, *, node_type_entry, params, extra_texts=())` builds the context ONCE per mint: catalog paths from `DatasetCatalogService(g.user).list_catalog(dataflow_id=project_id)` items whose `path` the listing resolved (the same truth `catalog.search` serves; a failing catalog read degrades to an empty map + a logged warning — the check still refuses ungrounded paths, honestly); user texts = `loop_ctx["message"]` + the session's prior `user` turns (`sessions.read_turns`); verified URLs = every `datasetCandidates` external row with `verification.status == "verified"` across the session's turns and `loop_ctx["_minted_candidates"]` (this run) plus `loop_ctx["_probe_cache"]`; `is_data_loading` = template id ends with `/data-loading` (canonical id from `resolve_template`); `probe` = a closure over `verify.verify_external_source` that counts against `loop_ctx["_egress_probes"]` and `egress.MAX_CALLS_PER_RUN` (shared with `_verify_candidate_parts`'s counter — one budget name, one run).
- `_mint_node_create` / `_mint_node_insert`: after `extract_node_content` and size checks, `verdict = check_grounding(...)`; `not ok` → `_refuse_params(refusal_text)` (a free correction round, dev/105 D2 — the store was never touched); `loop_ctx.get("_candidates_pending_review")` → `_refuse_params("dataset candidates await the user's selection — end your turn and let the user confirm")`. `ok` → `part["source"] = verdict.source`, `proposal["source"] = verdict.source`, summary suffix ` · source: <label>`.
- `_mint_node_content_write`: same gate keyed on the EXISTING node's type (spec `nodes[].type` → `canonical_template_id`). The dev/73 `_mint_content_review_from_delegate` inherits it: a refusal returns the honest *"could not become a reviewed proposal (<violation>)"* text, which the parent reports — nothing minted.
- Solve `_record_outcome` (`services.py:3966-3989`): `solved` → `check_grounding` with the batch's pre-computed context (built ONCE in the request thread before the pool — workers hold no `g`); violation → `results[node_id] = {"status": "failed", "error": "ungrounded source: … — resolve it with Dataset Finder (attach it to this node) or give the path"}` and NOTHING enters `applied_contents`; the `node_result` event carries the same error (dev/106 D3 made `error` durable). Propose mode routes through the content-write mint and refuses there.
- `_mint_dataflow_plan`: plan nodes carrying `content` (`content.py:446-455`) are checked with the plan's `nodeType`; a violation is one more entry in the dev/54 correction errors (`_plan_correction_message`) — the plan is never minted with a fabricated path, and the model gets the literal named.
- `_mint_node_template_create`: `template.content` checked with `is_data_loading = template.category == "data"`; refusal via `_refuse_params`.
- `_verify_candidate_parts` records verified rows into `loop_ctx["_minted_candidates"]` when called from the loop (signature gains an optional `loop_ctx`), so a same-session confirmation can ground a URL without re-spending egress.

### 3.3 Node Builder → Dataset Finder (the attachment path)

- Roster: `tools += catalog.search`; `delegates_to += agent.dataset-finder` (last — reuse/content specialists stay ahead in `delegation.resolve` order). `_ROSTER_GRANTS` unchanged.
- The delegation paragraph now offers `dataset.discover — handled by Dataset Finder` on every Node Builder run where the finder is installed. When it is not, `_resolve_delegate_request` already yields the reviewed `project.install` proposal (REQ-ORCH-001).
- `_enriched_delegate_inputs`, sixth application (DEC-063): `capability == "dataset.discover"` → `catalog` (the `_catalog_search_rows` shape over the child's `intent`/`q`, bounded 40 rows, path included) + `discoveryReplyContract` (the schema: `{"datasetCandidates": {"lanes": {"external": [...], "catalog": [...]}}}` with the row fields of `content._parse_candidate_row`, and the rule "catalog rows ONLY from the `catalog` input; external rows are suggestions the runtime will probe"). Model keys always win.
- `_mint_candidates_from_delegate(loop_ctx, child_text, catalog_rows)`: schema-only recognition (a JSON object — bare or in one fence — whose `datasetCandidates.lanes` is a dict, the `_extract_notes_reply` shape) → `content._parse_dataset_candidates` → catalog rows whose `datasetId` is not in `catalog_rows` are DROPPED (count reported: *"N catalog rows dropped — not in the Data Catalog"*) → `_verify_candidate_parts([part], loop_ctx)` → the part is appended to the PARENT's `minted` (the two-lane card renders in the Node Builder chat; the dev/72 trace lands at the finder's home as today); `loop_ctx["_candidates_pending_review"] = True`; the delegate result text tells the model: *"candidates are shown to the user for review — do not propose a node in this turn; ask the user to select and confirm"*. Zero surviving rows → `status = "no-candidates"` with the honest text.
- Confirmation turn: the user's edited prompt (composed by the card's `variant: "builder"`) names the selection; Node Builder proposes `node.create`; the gate grounds the URL from the session's verified rows or a catalog path from `catalog.search`; the card shows the source.
- Dataset Finder's own attachment path (DEC-047) is unchanged in mechanism: external confirmation → `kind: "handoff"` card (verdict per row) + the suggested prompt to the Node Builder attachment; Node Builder's gate probes the URL at mint. Catalog confirmation → reviewed `dataset.install` (existing).

### 3.4 The `source` payload (proposal part + stored proposal)

```json
"source": {
  "kind": "catalog" | "external" | "user-path" | "synthetic" | "mixed",
  "label": "Data Catalog · Census ACS 5-year (parquet)",
  "refs": [
    {"kind": "catalog", "value": "/…/census-acs.parquet", "datasetId": "…", "title": "…", "format": "parquet"},
    {"kind": "external", "value": "https://api.census.gov/data", "verification": {"status": "verified", "httpStatus": 200, "checkedAt": "…"}},
    {"kind": "user-path", "value": "/data/tracts.geojson"},
    {"kind": "synthetic"}
  ]
}
```

Bounded (`_MAX_REFS`, value ≤ 300 chars — the candidate URL bound), plain data, rendered inert. Not a pin: apply does not re-check it (§2 posture).

### 3.5 Dataflow Builder path — reconciliation with the required sequence

The task's step 1–2 ("Dataflow Builder delegates node work to Node Builder; Node Builder … delegates source resolution to Dataset Finder") meets two standing constraints: Solve delegates `node.content.generate` to Node Content Builder directly (dev/63, `requiresAgents`, DEC-068), and DEC-046 forbids a child delegating further (no grandchildren). The reconciliation — a deliberate deviation, recorded here and in the BL entry:

- The **runtime** performs Dataset Finder's catalog step for Solve: the seventh `_enriched_delegate_inputs` application injects `sourceGrounding` into `node.content.generate` inputs for data-loading nodes — `{catalogDatasets: [{datasetId, title, format, path}], userPaths, verifiedUrls, rule}` — catalog datasets = installed items with resolved paths; user paths/URLs mined from the plan node's `intent`, the plan `goal`, and the mission (URLs probed, budgeted).
- The gate refuses ungrounded output (§3.2) — the node stays pending with the reason and the remedy: the plan node's **auto-attached Node Builder** (`_attach_node_builder`, `services.py:1939-1969`) is where the user resolves the source, and THAT Node Builder delegates to Dataset Finder (§3.3). So the sequence holds end-to-end at the user's gesture, with the runtime carrying the finder's catalog half where a grandchild cannot.
- The DFB instruction §6 line ("direct them to their Dataset Finder attachment") is unchanged.

### 3.6 Prompt edits (one commit, sha-pinned)

- `node_build_instruction.txt` — new §4a (renumber-free: inserted as a paragraph under §4): the ladder (user path → `catalog.search` `path` → runtime-verified URL via `dataset.discover` delegate or a verified candidates card → `"synthetic": true` only when asked), *"never invent a filename, never assume a file exists, never write a URL from memory — the runtime probes every URL and refuses unreachable ones; if no source can be grounded, ask the user for a path or URL instead of proposing"*, and the two-turn rule (candidates → user confirms → propose).
- `default_preamble.txt:332-352` — the three DATA_LOADING contents become `dataset_path = "<absolute path from the Data Catalog>"`-shaped with the comment `# the path comes from the Data Catalog or the user — never a guessed filename`. The example's shape teaches; the gate enforces.
- `discovery_instruction.txt` §5 — handoff card `kind: "handoff"`, one line per row with its verdict (`verified ✓ / unreachable ✗ / unverified`), and the suggested prompt keeps the URL exactly as verified.

### 3.7 What this memo deliberately does NOT do

No second validator: `validate_candidate` (execute-through) is not wired to mints — it needs upstream data and a sandbox round-trip per mint; the grounding gate is a static, millisecond check that closes the fabrication class. No new part type: the two-lane `datasetCandidates`, `card`, `delegation`, and `proposal` parts carry everything. No apply-time re-verification of URLs (posture in §2). No auto-selection: a single verified candidate still awaits the user's confirmation (DEC-006).

## 4. Data and State Handling

- **Source of truth.** Catalog paths: the datasets domain listing (`list_catalog`), read at mint/Solve time — never cached across runs. Verification: `verify.verify_external_source` results stored on candidate rows in the transcript (already) and in the proposal's `source.refs[].verification`. User paths: the user's own turns (persisted) + the current message (`loop_ctx["message"]`).
- **Derived values.** `source` is derived from the verdict at mint; the card renders it. The confirmation prompt is derived client-side from the selection (`composeConfirmationPrompt`), per variant.
- **Budget.** One egress counter per run (`loop_ctx["_egress_probes"]`), shared by candidate verification and mint probes; probes are cached per URL in `loop_ctx["_probe_cache"]` so a corrected retry never re-spends. Solve: one counter per batch.
- **Loading / empty / error.** Catalog read failure → empty catalog map + warning; the refusal hint then omits the catalog clause (grant-aware honesty). Delegate reply with no recognizable candidates → `status: "no-candidates"` on the delegation entry, text says so. Egress budget spent → the URL is a violation with *"budget spent — not checked"*; the model is told to ask the user.
- **State after actions.** A refused mint stores nothing (DEC-070 posture). A minted proposal with `source` persists in the attachment mirror + transcript as today. Solve failure over grounding writes nothing to the node; `nodeRuns[node] = "failed"` with the reason (dev/106 D3).
- **Race/stale.** `_candidates_pending_review` is run-scoped (loop_ctx) — a later turn is a new run. A dataset uninstalled between search and mint → its path is no longer in the catalog map → refusal names it (honest). Concurrent Solve workers share a read-only pre-computed context; the gate is pure.

## 5. UI and UX Requirements

Reference: concepts `03` and `07` (non-canonical where they differ from docs/06/08 — `png-concepts/README.md`). Reconciliation, recorded:

| Concept detail | Current contract | Decision |
|---|---|---|
| `03`/`07` card titled "Suggested datasets", header links "→ Node Builder" / "→ install" per lane | `AgentDatasetCandidatesCard`: "Dataset candidates · select & confirm in chat"; lanes have labels only, no bespoke actions (docs/06:35-39) | **Keep the current card.** Lane header links are stale (they are actions). |
| `03` fit as "94%" | `Fit 94/100 — <rationale>` | Keep; the rationale is the docs/06 row contract. |
| `03` Data Loading node code `gpd.read_file("data/tracts.geojson")` | A relative path in a proposed node is exactly the #298 shape | Stale as an exemplar; grounded only if the user typed it. |
| `07` "Handing off to Node Builder · running" card | DEC-047 `card` (now `kind: "handoff"`) on the finder's turn + the dev/72 `delegation` entry on a Node Builder turn + dev/80 run status | Keep both existing surfaces; no new card type. The `handoff` kind label renders in the generic shell. |
| `07` "Installed from the Data Catalog" result card | The `dataset.install` review card in its `applied` state IS the result record (docs/08:115) | Keep. No separate result card. |
| `07` Census ACS shown "installed" yet installed by the prompt | Idempotent duplicate rule (docs/06:84-85) | Stale detail; already-installed picks say so instead of proposing. |
| `03`/`07` composer prefilled with an editable prompt; chip row below | `suggestedPrompts` prefill rule + chips (`AgentChatPanel.tsx:290-311, 827-838`) | Matches; unchanged. |

Requirements:

- **Two-lane surface everywhere it appears** (finder chat, Node Builder chat): rows show name, source type badge, provider · format · coverage, URL, fit, requirement, installed chip (catalog), verification chip (external). Unchanged component; the `variant` only changes the composed prompt text.
- **Review card "Source" block** (node.create / node.insert / node.content.write): one line per ref — `Data Catalog · <title> (<format>)`, `External · <url>` + verification chip (Verified ✓ / Unreachable ✗ / Refused ✗ / Unverified), `User-provided path · <path>` (label: "not checked by Curio"), `Synthetic · generated in the node, no external source`. Plain text, inert, `role="group"` with `aria-label="Data source"`. Rendered above the preview so it is impossible to miss; the effect line stays.
- **Never imply application**: the review card's pending/applied/dismissed/stale states are unchanged; a refused mint yields the agent's plain-text explanation (and at the round cap the existing cutoff card).
- **Editable prompts only**: the candidates card composes into the input through the existing prefill rule; no row-level buttons (docs/06:35-39). Apply/Dismiss remain review-card system controls.
- **Accessibility**: checkboxes keep `aria-label="Select <name>"`; the verification chip carries `title` text (already) and the status word in text (never color alone); the Source block is a labeled group; the `handoff` card keeps the `${kind} card: ${title}` group label.
- No layout shift: the Source block is part of the card's initial render (it rides the part), no async fetch.

## 6. Edge Cases

- **F-strings and concatenation**: `f"https://api.census.gov/data/{year}/acs/acs5?get={vars}"` → the constant prefix `https://api.census.gov/data/` is probed; `base + "/resource/x.json"` → each literal is classified alone (`"/resource/x.json"` is a path-shaped literal → must be grounded) — recorded limitation: concatenated URLs are refused with the hint "write the full URL as one literal". Corrective, not silent.
- **Catalog path spelled differently**: exact match first, then same real path (`os.path.realpath`) — case/`./` drift tolerated; a different file in the same directory is NOT grounded.
- **User typed a relative path** (`data/tracts.geojson`): grounded as `user-path` (the user knows their launch dir); the card says "not checked by Curio".
- **URL verified in an earlier session turn, dataset gone now**: session evidence grounds the URL (no re-probe) — a runtime error at Run is the node's honest report; recorded posture.
- **401/403**: grounded, `requirement: credential-gated`; the card shows it; the instruction tells the model to name the credential need in the goal.
- **400 from a base URL**: violation *"answered 400 — check the request parameters"* (the owner's Census case surfaces as a named refusal instead of a broken node; F1 follows up parameter validation).
- **Egress budget spent** (4 probes/run): the URL is a violation with the budget named; the hint says "ask the user to confirm the URL" — never silently accepted.
- **Synthetic word in the MODEL's text only**: not authorization — the user's texts or `params.synthetic` only.
- **Data-loading node with no refs and no synthetic request**: refused (*"no grounded source"*), even though the code would run — an inline `pd.DataFrame({...})` of invented values is the same fabrication class.
- **Non-data-loading node that opens a file** (`computation-analysis` reading `x.csv`): path refs are checked for EVERY node type; only the "no source" rule is data-loading-specific.
- **Delegate reply malformed / chat JSON**: schema recognition fails → `no-candidates`, honest text; no fabricated rows. Catalog rows with ids not in the runtime's list → dropped and counted.
- **Repeated confirmations / duplicate candidates**: the card's selection is client-local; re-confirming re-mints a superseding proposal (existing dev/41 supersession).
- **Solve batch with N data-loading nodes**: one shared context, one budget; nodes beyond the budget refuse with the budget named; other nodes solve normally (failure isolation, dev/63).
- **Streaming vs. non-streaming**: both loops call the same mints; `stream_with_context` keeps `g.user` available (`routes.py:907`).
- **Legacy fat dataset refs** (`path`/`format` present): `node_context` reads both shapes.

## 7. Testing Strategy

Deterministic providers (the `_fake_run` closure pattern, `test_routes.py:3374-3404`), `verify_external_source` monkeypatched (the `TestVerifiedDiscovery` shape), a `data-loading` template added to `TestNodeCreate._write_builtin_package` — no network.

- **Unit — `test_source_grounding.py`** (new): scanner (constants, f-string prefix, syntax error fallback, extension table, bound); verdicts per rule (catalog path ok / foreign path refused / user path ok / URL verified ok / URL 404 refused / 401 credential-gated / budget spent / synthetic declared / synthetic by user text / model-text synthetic ignored / no-source data-loading refused / no-source computation ok); `source` payload shape and bounds; refusal text grant-awareness.
- **Unit — `test_node_context.py`**: thin ref → `{id: datasetId, name: dirName/title, origin}`; fat ref unchanged.
- **Unit — `test_tools.py`**: `catalog.search` rows carry `path`/`loader` only when the listing resolved a contained path; registry description pin.
- **Unit — `test_builtin.py`**: Node Builder tools/delegates pins; instruction carries the ladder words; preamble exemplars contain no bare `read_csv('…csv'` literal.
- **Integration — `test_routes.py`**:
  1. **Regression #298** (`TestSourceGroundingRegression298`): a Node Builder run whose scripted reply is `node.create` with `pd.read_csv("bras_ibge_data.csv")` → NO proposal; the tool-result message names the literal; `refusedRounds == 1`; second scripted reply with the corrected content (a catalog path) → proposal with `source.kind == "catalog"`.
  2. **Catalog data**: an installed dataset with a real path; `catalog.search` returns it with `path`; `node.create` using that path → proposal, `source.refs[0].datasetId` is the real id; apply creates the node; the finder-side `dataset.install` flow untouched (existing tests stay green).
  3. **External API**: no catalog match; `dataset.discover` delegate reply carries external rows; runtime verifies (fake: one verified, one 404); the part lands on the Node Builder turn with verdicts; a same-run `node.create` is refused (`_candidates_pending_review`); next run: `node.create` with the verified URL → proposal `source.kind == "external"` with the verification; with the 404 URL → refused naming 404; with a guessed filename → refused (never a local file).
  4. **Unavailable source**: all probes unreachable and no catalog → refusal text asks for a path/URL; at the refusal cap the run ends with plain text and no proposal; nothing in the spec changed.
  5. **Synthetic**: user message "generate synthetic sample data for 5 tracts" + inline `pd.DataFrame` → proposal `source.kind == "synthetic"`, summary says synthetic; the same content WITHOUT the request → refused.
  6. **Solve** (`TestSolveSourceGrounding`): a plan with a data-loading node; child returns `pd.read_csv("x.csv")` → `node_result.status == "failed"` with "ungrounded source"; spec content stays empty; a sibling computation node solves; child inputs carried `sourceGrounding` with the installed dataset's path; a child returning that path → solved.
  7. **Plan content**: a plan carrying `content: "pd.read_csv('a.csv')"` on a data-loading node → correction round naming it; corrected plan mints.
  8. **Content write via delegate** (dev/73 path): generated content with a fabricated path → no review proposal; the parent's delegate result text carries the refusal.
- **Integration — `test_delegation.py`**: `_mint_candidates_from_delegate` schema recognition (bare / fenced / chat JSON ignored), catalog-row dropping, verification applied, `no-candidates` outcome.
- **Component — jest**: `AgentReviewCard` renders the Source block for each kind with the chip text and the group label; absent `source` → no block (existing cards unchanged). `AgentDatasetCandidatesCard` `variant: "builder"` composes "build the data-loading node from …"; default unchanged (existing test stays). `AgentChatCard` `handoff` kind label. `AgentChatPanel` passes the variant for a Node Builder coord (one assertion on the composed prefill).
- **Required before complete**: 1–8, the unit suites, the two roster pins, jest for the review card and the candidates variant; full `pytest utk_curio/backend/tests/test_agents` and full jest green; `tsc --noEmit` unchanged (pre-existing notices only).

## 8. Acceptance Criteria

1. Asking Node Builder for "a node that loads Brazilian IBGE demographic data" with no catalog match and no path yields either a two-lane candidates card (after a Dataset Finder delegation) or a plain request for a path/URL — never a proposal containing `bras_ibge_data.csv` or any path the user did not type.
2. A proposal whose code opens a local file is created only when that path is an installed Data Catalog path (the card shows "Data Catalog · <title>") or appears verbatim in the user's own message (the card shows "User-provided path · not checked by Curio").
3. A proposal whose code fetches a URL is created only after the runtime probed it (2xx, or 401/403 labeled credential-gated) or a verified candidates row carried it; the card shows the URL and "Verified ✓"; a 404/400/transport failure is refused with the status named.
4. A data-loading node with inline data is proposed only when the user asked for synthetic data (or the model declared `synthetic: true` for such a request) and the card says "Synthetic · generated in the node, no external source".
5. In a Node Builder chat, selecting rows on the candidates card prefills an editable prompt reading "build the data-loading node from …"; in the Dataset Finder chat the existing "Confirm my selection — …" prompt is unchanged; no row has an action button.
6. Solve never writes fabricated-path content: the node shows `failed` with "ungrounded source: <literal>" and the remedy; other nodes in the batch are unaffected.
7. The Dataset Finder's external confirmation card is `kind: handoff`, lists each row's verdict, and the suggested prompt is addressed to the Node Builder attachment (DEC-047 unchanged); the catalog confirmation still mints the reviewed `dataset.install`, whose applied card is the installation record.
8. No surface says a dataset or node was installed/created/changed before Apply succeeded: refused mints produce plain text; pending cards say "review"; Solve failures say "failed".
9. `catalog.search` rows for installed datasets carry `path` and `loader`; rows without a resolved contained path carry neither.
10. `compose_node_context` returns real `datasetRefs` ids/names for thin refs.
11. All new/updated tests pass; `test_agents` and jest fully green; roster/prompt pins updated deliberately in the contract-copy commit.

## 9. Recommended Commit Breakdown

- **Commit 1 — the gate.** `source_grounding.py` (scanner, context, verdict, payload, refusal text) + `test_source_grounding.py`; `node_context.py` thin-ref fix + test; `tools.py` `catalog.search` `path`/`loader` + test/registry pin.
- **Commit 2 — mints and Solve.** `services.py`: `_grounding_context`, `loop_ctx["message"]`, gate in `_mint_node_create/_mint_node_insert/_mint_node_content_write/_mint_node_template_create/_mint_dataflow_plan`, Solve `_record_outcome` + pre-computed batch context, `_verify_candidate_parts(loop_ctx)` cache, `source` on parts; `test_routes.py` cases 1, 2, 4, 5, 6, 7, 8.
- **Commit 3 — Node Builder ↔ Dataset Finder.** `builtin.py` roster (tools + delegate), `_enriched_delegate_inputs` sixth/seventh applications, `_mint_candidates_from_delegate`, `_candidates_pending_review`; `test_routes.py` case 3, `test_delegation.py`, `test_builtin.py` pins.
- **Commit 4 — frontend.** `agentsApi.ts` types, `verificationChip.tsx`, `AgentReviewCard` Source block, `AgentDatasetCandidatesCard` variant, `AgentChatPanel` wiring, `AgentChatCard` handoff label; jest.
- **Commit 5 — contract copy.** `node_build_instruction.txt`, `default_preamble.txt`, `discovery_instruction.txt` (sha pins updated deliberately; `test_builtin` assertions on the ladder words).
- **Commit 6 — docs.** `docs/AGENTS.md`, dev/03 `DEC-072`, dev/00 index, BL-P5 closing entry (`BL-P5-20260908-48`), `3.1` status lines, memo status + hashes.

Multi-session protocol applies (pathspec commits; `git status` before every add; `git diff --cached -- <file>` before touching a file another session staged; the worktree's `node_modules` symlink is never added).

## 10. Engineering Quality Checklist

- [ ] ONE grounding gate (`source_grounding.py`); no per-mint re-implementation; every code boundary calls the same function.
- [ ] The model never authorizes itself: synthetic from USER text or an explicit param the user's request justifies; URLs grounded by runtime evidence only.
- [ ] Refusals are `ParamRefusal` (free rounds) with grant-aware hints; broken-store failures stay unmarked (dev/105 D2).
- [ ] Refuse BEFORE any store write (DEC-070 posture); Solve writes nothing for a refused node.
- [ ] Egress budget shared and cached per run; no unbounded probing.
- [ ] DEC-046 intact: children stay tool-less; evidence arrives as inputs (applications six and seven); the candidates mint is runtime-owned and schema-recognized.
- [ ] Two-lane card, delegation entry, review card reused — no new part type, no row-level buttons.
- [ ] a11y: labeled groups, status words in text, chip `title`; no color-only state.
- [ ] Types explicit (`AgentSourceRef`, `AgentProposalPart.source?`); forward-tolerant (absent `source` renders as before).
- [ ] Prompt pins updated in their own commit with the edit they guard (dev/48 D4 rule).
- [ ] Tests cover the #298 regression, all six required cases, and every edge in §6 that has a deterministic shape.

## Open questions for the owner (non-blocking — defaults stated)

- Should a URL that verified in an EARLIER session turn be re-probed at mint? Default **no** (evidence in the transcript is the record; the run budget is small; a Run failure reports honestly).
- Should the "no grounded source" rule refuse inline-data nodes for non-data-loading templates too? Default **no** (only path/URL refs are checked there; a computation node legitimately builds data).
- Provenance INTO the spec node (F3)? Default **defer** until the frontend save contract preserves unknown node fields.

## Follow-ups (recorded, not delivered)

- **F1** Request-parameter validation for verified endpoints (the owner's HTTP 400): probe the exact composed request in a `research.verify` delegation or wire dev/67-7 `validate_candidate` behind an opt-in at mint — its own memo.
- **F2** The legacy `llmRequest` chat callers (the reporter's path on `main`): unchanged by owner instruction (dev/113); the gate is reusable as a pure function when that cutover happens (`3.1` remainder line).
- **F3** Source/provenance metadata persisted on the spec node (docs/06:71-72) — needs the frontend save contract to preserve it.
- **F4** Package-authored python templates through the same gate (`package.draft.apply`).
- **F5** `catalog.search` `q` relevance for the delegate path (today's `list_catalog(q=…)` filter is the drawer's; a ranking pass may follow demand).


## Amendment A1 (2026-09-08) — ported onto `imp/agentcatalog` (main's agents code)

The owner chose (2026-09-08, over a full merge of the 41 dev/107–113 commits, which conflicted in 17 code files and would have re-added what `main` deliberately retired) to **port dev/114 only** onto the branch created from `main`. What the port changed against §2–§3 as written:

1. **No `node.insert` here** (dev/113 is feat-only; `main` has its own connection attach, `b801f0fb`). The gate covers `node.create`, `node.content.write`, `node.template.create`, and Solve — §3.2's `node.insert` bullet is void on this branch.
2. **Plan-carried content is already refused** by `_mint_dataflow_plan` (dev/67-5: "plans describe intent") — §3.2's plan-content check was unnecessary and was not added.
3. **The catalog loader is portable**: `main`'s `loader_snippet` emits `dataset_path = curio_dataset_path("<id>")`, resolved by the sandbox at run time (`/processPythonCode` → `resolve_execution_paths`). The gate therefore grounds a `catalog-id` ref by dataset id (`GroundingContext.catalog_ids`, scanner support in AST and regex, the same id grammar as `_DATASET_PATH_CALL_RE`), in addition to the literal-path form; `catalog.search` rows carry both `path` and the `loader` line; `sourceGrounding.catalogDatasets[].use` hands the child the exact line.
4. **One schema, not two**: `main`'s #269 `content.CANDIDATES_INSTRUCTION` is the `datasetCandidates` reply schema; the `dataset.discover` delegate input `discoveryReplyContract` = `_DISCOVERY_RULE` + that text. Because #269 keys the schema on the `catalog.search` grant, Node Builder's own tail now also carries it (a Node Builder may propose candidates directly; the gate still governs what it builds) — recorded, not fought.
5. **Docs target**: `docs/AGENTS.md` was deleted on `main` (`97ff17eb`); the closing docs went to `docs/AGENT-CATALOG.md` §3 ("Where a data-loading node's source comes from").
6. **Commit plan**: §9's six commits landed as five — the backend mints/Solve and the Node Builder ↔ Dataset Finder seam share one `services.py` change set and were committed together (`eaaa079f`).
7. **Solve's failure text** is built from the refusal's violation clause (bounded to 300 chars per dev/106 D3) plus the remedy "resolve the source with Dataset Finder (attach it to this node) or give the path"; propose-mode Solve runs the gate BEFORE the content-review mint so the node's failure names the source rather than "could not become a proposal".
8. **Test fixture lesson**: the run loop mutates ONE `messages_work` list, so every recorded provider call aliases the same object — route tests read tool results by prefix (`_tool_results`), never by call index.

Field evidence folded in (owner, 2026-09-08): gemma4 on our server and on Hugging Face — four of five suggested dataset links broken, a Census fetch node answering HTTP 400. The gate's refusal for a 400 names the request shape ("the endpoint exists but this request shape is wrong; check the parameters") — F1 (parameter validation) stays the follow-up.
