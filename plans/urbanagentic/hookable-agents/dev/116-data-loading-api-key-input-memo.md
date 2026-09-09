# dev/116 — A key-gated API is a dead end today: the verified Solve loop names the missing API key (Census, dev/115 §A3.1) and nothing lets the user supply it without pasting a secret into node code — give data-loading nodes a per-user key store the sandbox injects by name

**Status: IMPLEMENTED (2026-09-08 → 2026-09-09) on `imp/agentcatalog` — commits `58115a82` (1, `users/connection_keys.py` store + refs + normalisation, `connection_keys_routes.py` `GET/PUT/DELETE /api/users/me/connection-keys[/<name>]` + `/suggest-name`, the redactor), `ecccb58a` (2, `secret_names`/`SECRET_CALL_RE`, `_resolve_exec_secrets` + the `secrets` payload key on `/processPythonCode` and `run_through_node`/`validate_candidate`, `sandbox/util/secrets.py` injected in the in-process worker and the isolated child, `protocol.build_exec_request(secrets=)`, stdout/stderr redaction at the sandbox boundary; redactor moved to `utk_curio/common/redaction.py`), `97d97ccf` (3, `GroundingContext.secrets`/`secret_values`, `availableSecrets` + rule, the `secret` ref kind, unknown-name and credential-literal refusals, credential-gated hint, `secrets_fn` per round, keyed composed probes over `egress.fetch(headers=, params=)`, `_decline_remedy` → `remedy` on evidence/attempt/result/card, both prompt clauses), `84169e4d` (4, `connectionKeysApi.ts`, `ConnectionKeysSection` in AI Settings, `AddKeyAction` on the strip / per-node row / review card, `ConnectionKeysModalHost` + window-event bus, the `secret` Source ref), + commit 5 (docs: `docs/USAGE.md`, `docs/AGENT-CATALOG.md`, `docs/NODE-CATALOG.md`; ledgers in the untracked `plans/` tree: dev/03 `DEC-074` + DEC-022 T4 note, dev/00 row, `BL-P5-20260908-50`, `3.1`, dev/115 F7 closure, docs/09 note). `DEC-074` minted. Suites: backend 1231 passed / 2 skipped (+ sandbox suites green apart from one pre-existing platform-bound fallback test), jest 201 suites / 2330 tests, `tsc` clean. Deviations from §3 and §9, all recorded in `BL-P5-20260908-50`: routes on their own blueprint; the sandbox's missing-key sentence does not list saved names (the gate does); the redactor lives in `utk_curio/common` (the sandbox must not import the backend); a second remedy kind `use-connection-key`; the settings section is a collapsed `<details>` whose body mounts only while open; cards reach the modal through a window event answered on the dock overlay. Live re-test with a real Census key run 2026-09-09 (key saved by the owner through the new UI section; the driver never saw the value): PASS on the fourth pass after three harness fixes in `ab87e8fb` — results in §Live re-test below.**

Date: 2026-09-08
Branch / tree: `imp/agentcatalog` @ `421c95c6` (dev/115 field fixes). Line numbers pinned to that commit. `plans/` is untracked on this branch — this memo lives on disk.
Origin: owner request 2026-09-08 — *"lets plan the F7 api key input for data loading nodes"* — dev/115 follow-up **F7**: *"The Census API now requires a key for data queries. The harness names it; nothing lets the user supply one to a data-loading node without pasting it into code. A secret input the sandbox injects (env or params) is a memo of its own — never a literal in node content."*
Evidence: dev/115 §A3.1 Task 3 (live, gemma4): the composed Census request 302-redirects to `api.census.gov/data/missing_key.html` (`X-DataWebAPI-KeyError: 1`); the correction round declined — *"The US Census Bureau API requires an API key to fetch data"* — and the loop ended `source-missing` with the remedy *"provide what it names (a key, a path or a URL) in the chat, then Solve again"*. That remedy cannot be followed: a key typed in the chat enters the transcript and the provider context, and a key pasted into the code enters the saved spec (`spec.trill.json`), the runtime journal (`execution/runtime_journal.py:54` records code + stdout + stderr per node), every proposal preview and every export. `api/routes.py:362-371` — the `/processPythonCode` sandbox payload carries `dataset_paths` and `user_key`, both minted server-side from `g.user`; the browser sends no secret material (`PythonInterpreter.ts:64-86`). `execution/runner.py:308-321` — the validation runner mirrors the same keys (dev/115 added them because the portable loader form failed under validation while working on Play). `sandbox/app/worker.py:380` — `ns['curio_dataset_path'] = _make_curio_dataset_path(dataset_paths)` is the one injection point into the exec namespace in-process; `sandbox/isolation/child.py:481-484` is its isolated twin; `sandbox/isolation/protocol.py:360-371` is the parent→child request. `worker.py:238` and `isolation/zygote.py:106` — `os` is in both namespace templates, so **`os.environ` is fully readable from node code**: an environment-variable design would hand every node `CURIO_SANDBOX_TOKEN`, `GUEST_LLM_API_KEY`, `CURIO_DEFAULT_HUGGINGFACE_TOKEN` and any key baked into `CURIO_SEARCH_URL`, and (all children share one execution uid — `isolation/hardening.py:25-31`) leak across concurrent users. `hardening.SENSITIVE_PATHS` (`hardening.py:40-46`) already makes `.curio/users` unreadable by isolated node code — a per-user file store is unreachable by the very code it serves. `users/models.py:20` — the LLM key is a plaintext column, exposed to clients only as `has_llm_api_key` (`users/schemas.py:57`); `AiSettingsModal.tsx:391/515` masked inputs, `:228` remove — the UI precedent for "enter once, never read back". `agents/source_grounding.py:565-570` — the gate already grounds a 401/403 endpoint as `requirement: credential-gated`; `services.py:7017` `_source_grounding_inputs` hands the content delegate `catalogDatasets[].use` lines (`curio_dataset_path("<id>")`) — the DEC-063 idiom a key can reuse. `llm-prompts/new_content_prompt.txt:7` tells the builder to decline on a key page — the decline dev/115 §A3.1 recorded. No `redact`/`mask` helper exists anywhere in `utk_curio`; `egress.EgressResult.audit` (`egress.py:296-302`) stores full URLs including query strings.
Family: dev/50 (Dataset Finder: *"T4 becomes load-bearing when fetch nodes need credential profiles at run time"* — deferred) → dev/67-4 (DEC-053 verification gate) → dev/90 A3 (keyed-GET providers: the key lives in the operator's `CURIO_SEARCH_URL` template, operator-only) → dev/91 (DEC-061: package handlers run in a scrubbed env — *"no secrets exist to steal"*; `package_build_instruction.txt:33-34` names *"the deferred secret mediation"*) → dev/114 (DEC-072 gate; `credential-gated`) → dev/115 (DEC-073 verified Solve; F7) → **dev/116**.
Design decisions consumed: DEC-006 (review before apply — a key is never applied through a proposal), DEC-022 / T4 (`ProviderProfile` + encrypted secret store remain the flagged v2 remainder; `RISK-SECRET-001`), DEC-053 (the runtime verifies external sources), DEC-061 (secrets never exist inside a worker unless mediated), DEC-063 (evidence as inputs — the delegate is told what exists, in an executable form), DEC-067 (self-correcting refusals: an unknown key name is a refusal naming the saved names), DEC-072 (the grounding gate covers every agent-authored code boundary), DEC-073 (Solve is the engineering loop; the user's Solve is the trigger). **New decision proposed: DEC-074** — *A data-loading node reaches a key-gated API through a named, per-user connection key: the user saves the key once (masked, never read back, bound to a host), node code refers to it only as `curio_secret("<name>")`, the backend resolves the names that appear in the code at execution time — for Play and for the verified Solve loop alike — and hands the values to the sandbox inside the execution request, where they exist only as an injected callable in the node's namespace (never an environment variable, never a file, never staged). Agents learn a key's existence as a `use` line in their grounded inputs and never see, request, or emit its value; an unknown name is refused with the saved names listed; a probe that carries a key and every captured stdout/stderr is redacted before it is stored or shown. Encryption at rest stays T4's remainder: the store is 0600 plaintext behind a `secretRef`-shaped interface so T4 replaces the backend, not the callers.*
Backlog: `BL-P5-20260908-50` at closure; closes dev/115 F7; touches dev/50's T4 line ("credential profiles at run time") — the runtime half is delivered, encryption stays T4.

---

## 1. Problem Statement

**What is missing.** A data-loading node whose endpoint requires an API key cannot be made to work without the key appearing as a literal somewhere it must not: in the node's code (saved into `spec.trill.json`, replayed into every proposal preview, exported with the dataflow, recorded by the runtime journal on every run), in the chat (the transcript is persisted and the text goes to the provider), or in a widget (`WidgetsEditor.tsx:182-208` substitutes widget values into the code string in the browser *before* posting — a "secret widget" would be a literal on the wire and in the journal).

**Where it shows.** (1) The verified Solve loop (dev/115): round 1 runs the Census code, the composed request lands on the "Missing Key" page, the content builder correctly declines, the card says *"provide what it names … then Solve again"* — and there is no way to provide a key that keeps the rest of the guarantee. (2) The Node Builder / Dataset Finder path: a `credential-gated` (401/403) endpoint is grounded with the requirement named, and the model is told to name the credential need in the goal — the user still has nowhere to put the credential. (3) Play: a user who pastes a key into the code to get past the wall has just published it to their saved dataflow.

**Expected behavior.** The user saves a key once under a name bound to a host (e.g. `census` → `api.census.gov`) through a masked field that never reads the value back. Node code says `api_key = curio_secret("census")`. Play and Solve execute that code with the real value injected into the sandbox namespace and nothing else changed: the saved spec, the journal, the proposals, the transcript and the exports carry the name only. The content builder is told *"a key named `census` for `api.census.gov` is available — `api_key = curio_secret("census")`"* and writes code that uses it instead of declining; when no key exists for the host, the decline stands and the remedy is a concrete action — *Add a connection key for `api.census.gov`* — that opens the key form with the host prefilled. Running code that names a key the user has not saved fails with one sentence naming the missing key and the saved names, never with a `KeyError` inside a helper.

**Why it matters.** Correctness: the Census API (and most government/commercial APIs) are key-gated; dev/115's loop is only as good as its ability to make a real request. Safety: the alternative the loop currently implies — put the key in the code — is a credential leak into five persisted surfaces. Consistency: `curio_dataset_path("<id>")` already proved the pattern (an opaque name in code, a server-minted mapping on the wire, a callable in the namespace); a key is the same shape with a smaller value and a stricter no-disk rule. Decision hygiene: T4's encrypted store has been "the remainder" since dev/17; this memo delivers the runtime half behind an interface that T4 can fill without touching callers, and says so plainly rather than waiting.

## 2. Scope

**Included**

- **Per-user connection-key store** (backend): `users/secrets.py` (or `common/secret_store.py`) — `list_keys(user_key) -> [{name, host, delivery, createdAt, lastUsedAt}]` (never values), `put_key(user_key, name, host, value, delivery)`, `delete_key(user_key, name)`, `resolve(user_key, names) -> {name: value}`; file `.curio/users/<key>/secrets.json`, mode `0600`, atomic write (temp + rename) under a per-user lock, `user_key_segment()` discipline (`common/user_storage.py:69-80`: numeric id or `guest`). Name charset `^[a-z0-9][a-z0-9_-]{0,39}$`; host = a bare hostname (lower-cased, no scheme/path); `delivery` ∈ `{"query:<param>", "header:<Header-Name>", "code"}` (how the API expects it; default `"code"` = the node's code decides — v1 UI offers `query` param name and `header` name as optional fields).
- **Routes**: `GET/PUT/DELETE /api/users/me/connection-keys[/<name>]` (auth like `users/routes.py:143-146`; guest mode → the shared `guest` store when `CURIO_NO_AUTH=1`, else 401). `PUT` body `{host, value, delivery?}`; responses never include `value`; `GET` returns the list; 409 when a `PUT` would rename an existing host binding without `replace: true` (edge case 6.8).
- **Execution-time resolution + wire** (both callers, byte-symmetric): `_resolve_exec_secrets(code, user_key)` beside `api/routes.py:284` — scan `curio_secret("<name>")` (regex `CURIO_SECRET_CALL_RE`, one source of truth exported from `source_grounding.py` like `DATASET_PATH_CALL_RE`, cap 8 names), resolve from the store, return `{name: value}` for the names found (unknown names are omitted so the sandbox error names them). `/processPythonCode` payload gains `"secrets": {...}` (`routes.py:362-371`); `run_through_node` gains `secrets: dict | None` and adds `payload["secrets"]` (`runner.py:308-321`); `_verified_content_rounds` gets a `secrets_fn(codes)` beside `dataset_paths_fn` (resolved in the request thread, per dev/115's rule that job threads have no request context — the *resolver* is prepared in the request thread; the *values* are resolved per round from the candidate code so a correction that starts using a key gets it).
- **Sandbox**: `/exec` reads `secrets` (`sandbox/app/api.py:361-373`, re-shape: dict of str→str, cap 8, values ≤ 4 KiB); `worker.execute_code(..., secrets=None)` injects `ns['curio_secret'] = _make_curio_secret(secrets)` at `worker.py:380`; `protocol.build_exec_request(..., secrets=...)` adds `"secrets"` to the request dict (`protocol.py:360-371`); `child.run_node` injects `namespace["curio_secret"]` at `child.py:484`. `_make_curio_secret` is a closure over a dict copy; a missing name raises `RuntimeError("no connection key named 'x' is saved for this account — save one under Settings → Connection keys (saved: a, b)")`; the closure exposes no enumeration of values; the `secrets` dict is deleted from the request object after injection so a traceback's locals cannot show it. **Never** an environment variable, **never** staged to scratch (`staging.stage_dataset_paths` is not extended), **never** logged (a guard test asserts no `log.*` call in the exec path formats the request).
- **Redaction** (new, small, shared): `common/redaction.py` — `redact(text, values) -> str` replacing every occurrence of each value (≥ 8 chars) with `«redacted:<name>»`; applied to (a) sandbox stdout/stderr before the `/exec` response is built (`worker.py` capture → response) so the journal, the runner's `stderrTail`/`stdoutTail`, the Solve card and the review card never carry a printed key; (b) any probe URL/`finalUrl`/`detail`/`bodySample` in `verify.py` outcomes when the probe was made with a key (§3.5); (c) `egress.EgressResult.audit` URLs for keyed probes. The values to redact are exactly the resolved `secrets` of that execution/probe — no global scan.
- **Agent side**: `GroundingContext` gains `secrets: dict[str, SecretRef(name, host, delivery)]` (names + hosts only — the context never holds values); `_source_grounding_inputs` adds `availableSecrets: [{name, host, delivery, use: 'api_key = curio_secret("census")'}]` and a `rule` clause (*"fetch a key-gated host ONLY through its `use` line; never write a key literal; if the host needs a key and none is listed, return the one-line explanation"*); `check_grounding` scans `curio_secret("<name>")` calls (kind `secret`): a known name is grounded (a `source.refs[]` entry `{kind: "secret", name, host}` for the Source block — *"Connection key · census · api.census.gov"*), an unknown name is a violation *"no connection key named 'x' is saved (saved: census)"* (DEC-067: the refusal names the correction), and a **key-shaped literal** (`_KEY_LITERAL_RE`: ≥ 24 chars of `[A-Za-z0-9_-]` assigned to a name matching `key|token|secret|api_key|apikey|password` or passed as a `key=`/`token=`/`Authorization` value) is a violation *"a credential literal in node code — save it as a connection key and use curio_secret(...)"* — the gate runs before every sandbox run (DEC-072), so a pasted key never executes, never reaches the journal, and never lands in a proposal. `new_content_prompt.txt:7` gains the companion clause (*"…unless `sourceGrounding.availableSecrets` lists one for that host — then use its `use` line and its `delivery`"*). The `source-missing` remedy names the host when the decline mentions a key and the host is known from the code's URLs: *"Add a connection key for api.census.gov, then Solve again"*, and the Solve/review card carries an **Add key** action (§5).
- **Probe with the key (bounded)**: `_correction_url_evidence` (dev/115) composes the request the code makes; when the candidate calls `curio_secret("<name>")` and that key's `delivery` is `query:<p>` or `header:<H>`, the composed probe carries the key (header, or the param appended) so the evidence says what the *keyed* request answers (200 JSON vs the key page); the outcome is redacted (§2 redaction b/c) and the composed keyed URL is **never** added to `verified_urls`. `delivery: code` → no keyed probe (the harness cannot know how the code sends it) — the run itself is the evidence. `verify_endpoint` gains optional `headers`/`params` threaded through `egress.fetch` → `_default_request`; the trusted-host SSRF exemption is unchanged (a user's key host goes through the default-deny public path, as it should).
- **Frontend**: `api/connectionKeysApi.ts` (list/put/delete; a light module — no vega drag, dev/91 lesson); a **Connection keys** section in the existing settings modal (`AiSettingsModal.tsx` pattern: masked `type="password"` + `autoComplete="new-password"`, "saved" marker, Remove; rows: name, host, delivery, last used; the value field is write-only and clears after save); an **Add key** action on the `source-missing` error card / Solve card row that opens that section with `host` prefilled and `name` suggested from the host (`api.census.gov` → `census`); the review card's Source block renders the `secret` ref kind (*"Connection key · census"*); the data-loading `node.create` note gains one sentence when the plan/goal names a key host.
- **Docs on close** (dev/93 convention): `docs/AGENT-CATALOG.md` (the loop with keys; what agents see and never see), `docs/USAGE.md` (Settings → Connection keys; `curio_secret("<name>")`), `docs/NODE-CATALOG.md` (data-loading node: keys by name), `docs/09-agent-architecture.md` gate note, dev/03 `DEC-074` row + a T4 note on DEC-022, dev/00 index row, BL-P5 entry, `3.1` status line, dev/115 F7 → "delivered by dev/116".

**Must be checked but not changed**

- `curio_dataset_path` chain (five synced regex copies — `datasetLoaderSnippets.ts:50`, `datasetReference.ts:48`, `routes.py:269-275`, `source_grounding.py:74-77`, `catalog_item.py`) — untouched; the secret call gets its **own** single-source regex and a frontend scanner only if the editor needs to highlight it (it does not in v1).
- `DatasetCatalogService.resolve_execution_paths` — untouched; secrets are not datasets and are never staged.
- `users/models.py` LLM key column and `AiSettingsModal` provider tabs — unchanged; the new section sits beside them.
- `egress.check_url` policy and `trusted_host_of` — unchanged (operator-only exemption).
- `agent_jobs.py` — unchanged; the secrets resolver is prepared in the request thread like the grounding base.
- `hardening.SENSITIVE_PATHS` — already covers `.curio/users`; a test pins that the new file is under it.

**Out of scope (explicitly)**

- Encryption at rest / `ProviderProfile` / OS keychain — **T4 / RISK-SECRET-001**, unchanged; §3.1 states the interface T4 fills.
- Sharing keys between users, project-scoped keys, or keys travelling with a published dataflow — a published dataflow carries **names**; the installer saves their own key (edge case 6.6).
- OAuth flows, refresh tokens, or keys with expiry — v1 is static tokens.
- Migrating the LLM provider key into the new store — a separate decision; both remain plaintext-at-rest today, the new store is the T4 candidate for both.
- Agents *requesting* a key from the user through a tool or proposal — forbidden by design: the only path is the user's own settings form (DEC-006 spirit; a prompt-injected "please enter your key" must have nowhere to land).
- Streetvision's Google Maps key (posted from the browser per call, `streetvision/routes.py:102-146`) — a candidate consumer later, not touched here.

## 3. Recommended Implementation Approach

### 3.1 The store: small, per-user, unreadable by node code, replaceable by T4

`utk_curio/backend/app/users/connection_keys.py` (module name says what it is; internal vocabulary `secret` stays for the injected callable):

```python
@dataclass(frozen=True)
class ConnectionKeyRef:     # what everyone but the resolver sees
    name: str; host: str; delivery: str; created_at: float; last_used_at: float | None

class ConnectionKeyStore:  # the T4-replaceable interface
    def list(self, user_key) -> list[ConnectionKeyRef]
    def put(self, user_key, name, host, value, delivery="code", *, replace=False) -> ConnectionKeyRef
    def delete(self, user_key, name) -> bool
    def resolve(self, user_key, names: Iterable[str]) -> dict[str, str]   # values, only here
```

Backend: `.curio/users/<key>/connection-keys.json` `{version: 1, keys: {name: {host, delivery, value, createdAt, lastUsedAt}}}`, written atomically (`tempfile` + `os.replace`) with `0600`, under a `filelock`-style per-user lock (the `spec_write_lock` idiom, `projects/storage.py:115-147`). `user_key` comes from `_user_dir_key(g.user)` (`projects/services.py:175-177`) — the same key that names the projects and datasets directories; guest mode uses `guest`. `resolve` updates `lastUsedAt` (best-effort, never blocks execution). Encryption is a one-class swap behind `ConnectionKeyStore` (T4): callers hold refs, only `resolve` touches values — the memo's honesty line: **plaintext at rest, 0600, same posture as the LLM key column today; unreachable from isolated node code by `hardening.SENSITIVE_PATHS`.**

### 3.2 Resolution and wire — the `dataset_paths` twin, minus the disk

`source_grounding.py` exports `SECRET_CALL_RE = re.compile(r'curio_secret\(\s*["\']([a-z0-9][a-z0-9_-]{0,39})["\']\s*\)')` and `secret_names(code) -> list[str]` (ast first — a `Constant` argument to a call named `curio_secret`, like `_is_dataset_path_call`; regex fallback). `api/routes.py` adds `_resolve_exec_secrets(code) -> dict` beside `_resolve_exec_dataset_paths` (fail-open like it: an empty mapping never blocks execution; the sandbox names the missing key). The payload (`routes.py:362-371`) and the runner payload (`runner.py:308-321`) each gain `"secrets"`, present only when non-empty — byte-compatible otherwise (dev/115's `test_payload_is_byte_compatible_without_them` pattern). `run_through_node(..., secrets=None)`; `validation.validate_candidate(..., secrets=...)` passthrough; `_verified_content_rounds(..., secrets_fn=None)` calls `secrets_fn([candidate])` per round beside `dataset_paths_fn`, where `secrets_fn` is a closure built in the request thread over `(store, user_key)` — the store reads a file, so it needs no request context, but the **user key** does, hence the closure (dev/115 lesson 1).

### 3.3 Sandbox injection — a callable, in memory, per execution

`sandbox/app/api.py` `/exec` reads `secrets`, validates shape (dict, ≤ 8 entries, str keys matching the name charset, str values ≤ 4096), and passes it to both branches: `runner.execute_isolated(..., secrets=...)` and `worker.execute_code(..., secrets=...)`. In-process (`worker.py:380`):

```python
ns['curio_dataset_path'] = _make_curio_dataset_path(dataset_paths)
ns['curio_secret'] = _make_curio_secret(secrets, saved_names)
```

`_make_curio_secret` closes over a private copy; the closure has no `__wrapped__`/`__closure__`-visible dict (store it in a `types.MappingProxyType` inside a class with `__slots__` and no `__dict__`; accept that Python offers no hard secrecy inside one process — the goal is *no accidental surface*, the hard boundary is the process/uid one already in place). Missing name → `RuntimeError` naming the missing key and the saved names (the API passes `saved_names` for that sentence; values never). Isolated: `protocol.build_exec_request(..., secrets)` → `"secrets"` in the request; `child.run_node` injects at `child.py:484` and `del request["secrets"]` right after; `encode_request` is unchanged (plain JSON over the parent→child pipe, which is a private fd — no file). `zygote.build_namespace_template` is untouched (the template must not carry per-execution secrets; the child injects after fork). A guard test greps the isolation package for any `log.*(...request...)` formatting.

### 3.4 Redaction — the four places a value could still be written

`common/redaction.py`:

```python
def redact(text: str | None, values: Mapping[str, str]) -> str | None
```

replaces each value (only those ≥ 8 chars, longest first) with `«redacted:<name>»`. Applied: (1) `worker.execute_code` / `child.run_node` to captured stdout/stderr **before** they leave the sandbox (so the interactive response, the runner's tails, the runtime journal, the Solve card and the review card are clean without each caller remembering); (2) `verify.verify_endpoint` outcomes when the probe carried a key (`url`, `finalUrl`, `detail`, `bodySample`); (3) `egress.fetch`'s `audit` entries for keyed requests; (4) the sandbox's own `RuntimeError` text never includes values by construction. Node **output data** (the dataframe) is not scanned — a node that returns its key as a column is the user's choice; the memo records this as the one unredacted surface.

### 3.5 The agent path — the key exists as a `use` line, never as a value

`_grounding_context` (`services.py`) reads `ConnectionKeyStore.list(user_key)` in the request thread (and the Solve base carries the refs — `_solve_grounding_base` gains `secrets`); `GroundingContext.secrets` holds `ConnectionKeyRef`s. `_source_grounding_inputs` emits:

```json
"availableSecrets": [{"name": "census", "host": "api.census.gov", "delivery": "query:key",
                      "use": "api_key = curio_secret(\"census\")"}]
```

and the rule clause. `check_grounding` gains the `secret` ref kind: known → grounded ref (Source block shows *Connection key · census · api.census.gov*); unknown → violation with the saved names; a credential-shaped literal → violation. The `credential-gated` branch (`source_grounding.py:565-570`) gains a hint when a saved key's host matches the endpoint: *"a connection key `census` is saved for this host — use its `use` line"*. `_correction_url_evidence` composes keyed probes for `query:`/`header:` deliveries (§2) and redacts. `new_content_prompt.txt:7` gets the companion clause; `node_build_instruction.txt`'s source ladder gains one rung: *"a key-gated endpoint with a saved connection key for its host is a grounded source; without one, name the host and stop."* The `source-missing` remedy (`services.py` `_record_outcome` and the solve-node card) becomes host-aware: when the decline text mentions `key|token|credential|sign-in` and the round's URL evidence names a host, the remedy is *"Add a connection key for `<host>` (Settings → Connection keys), then Solve again"* and the card carries `remedy: {kind: "connection-key", host}` for the frontend action.

### 3.6 Frontend — one settings section, one action, one Source row

`connectionKeysApi.ts` (list/put/delete, typed `ConnectionKeyRef`); `ConnectionKeysSection.tsx` inside the settings modal (masked value input that never receives a saved value; per-row Remove with the truthful line *"Nodes that call `curio_secret("<name>")` will fail until a key with this name is saved again"*); the `source-missing` error rows and the review card's remedy render an **Add key** button when `remedy.kind === "connection-key"`, which opens the modal on that section with `host` prefilled and a suggested `name` (second-level domain, lower-cased, `[^a-z0-9]`→`-`); the review card's Source block gets the `secret` kind label. Styles: tokens only (the colour-literal guard).

### 3.7 What this is NOT

Not an env var (`os.environ` is readable by node code — the survey's decisive finding). Not a widget (widgets are substituted client-side into the code string). Not a chat input (the transcript persists and goes to the provider). Not a proposal (`DEC-006` gates graph/dataset mutations — a key is neither, and an agent must have no way to ask for one). Not encryption (T4 — stated, not implied).

## 4. Data and State Handling

- **Source of truth**: the per-user `connection-keys.json` for values and refs; the node code for *which* names a node uses; nothing in `spec.trill.json`, the runtime journal, or the agents ledger ever holds a value.
- **Derived values**: `availableSecrets` = `store.list(user_key)` at grounding time (request thread); execution `secrets` = `store.resolve(user_key, secret_names(code))` at run time (Play: per request; Solve: per round from the candidate). A key saved *during* a Solve batch is picked up by the next round/node (resolution is per call), never by re-reading mid-round.
- **States**: settings section — loading (list), empty (*"No connection keys yet. A data-loading node reaches a key-gated API through `curio_secret("<name>")`."*), error (list failed: show, do not guess), success (rows). Save: the value field clears on 200; the row shows *saved · never used* until a run resolves it. Remove: optimistic row removal with rollback on error.
- **After actions**: Play with a missing name → the node errors with the sandbox sentence; the Solve card's remedy → Add key → save → the user clicks Solve again (A2: the user's Solve is the trigger; nothing auto-re-runs).
- **Races**: two saves for the same name → last write wins under the per-user lock (the API returns the stored ref); resolve during a write → reads the previous atomic file (rename is atomic). A run that started before a Remove keeps its resolved value for that execution only.
- **No duplication**: one regex for the call shape, one resolver per caller symmetric with `dataset_paths`, one redactor, one store interface.

## 5. UI and UX Requirements

- Settings modal → **Connection keys** section: table `Name · Host · Sent as · Last used · Remove`; form `Name`, `Host` (bare hostname; scheme stripped with a hint), `Sent as` (segmented: *in the code* (default) · *query parameter* → param name · *header* → header name), `Key` (masked, `autoComplete="new-password"`, never populated from the server), **Save**. Copy under the form: *"Use it in node code as `api_key = curio_secret("<name>")`. The key never appears in your dataflow, proposals or chat."*
- **Add key** action on `source-missing` rows (Solve card, solve-node error card, review card remedy) when the remedy carries a host: opens the section with host prefilled and the name suggested. Button label `Add key for api.census.gov`.
- Review card Source block: a `secret` ref renders *"Connection key · census · api.census.gov"* with the existing key-shaped icon vocabulary (no new colour literals).
- Node error surface (Play): the sandbox sentence as-is — it names the key and where to save one.
- Accessibility: the masked input has a visible label and `aria-describedby` pointing at the usage copy; the table has a caption; Remove is a real button with the name in its `aria-label`; focus moves to the form's first field when opened from Add key; the status line after Save is `role="status"`.
- No flicker: the section mounts inside the existing modal; list load shows a skeleton row, not an empty→filled jump; saving disables the form rather than unmounting it.

## 6. Edge Cases

1. **Unknown name in code** — sandbox `RuntimeError` naming the key and the saved names; the gate refuses agent-authored code with the same sentence before the sandbox (agent path); Play surfaces it as the node's error.
2. **Key-shaped literal in agent-authored code** — gate violation before execution (never runs, never journaled); user-typed literals in the editor are *not* blocked on Play (the user's own code is theirs) but a one-time non-blocking editor hint may follow later (recorded, not built).
3. **Value printed by node code** — redacted in stdout/stderr at the sandbox boundary; a key returned as *data* is not scanned (stated).
4. **Concurrent users under isolation** — values ride each execution's request only; the shared execution uid never sees a file or env var; a test asserts `os.environ` inside a run has no `secrets` and the namespace has no dict of values.
5. **Guest mode (`CURIO_NO_AUTH=1`)** — the shared `guest` store; the settings section shows *"Keys saved here are shared by everyone using this local instance"*; hosted deployments run with auth (the launcher already refuses an unguarded sandbox).
6. **Published/imported dataflow** — names travel, values do not; the importer's first Play names the missing key; the Solve remedy offers Add key.
7. **Host mismatch** — code calls `curio_secret("census")` but fetches `example.com`: allowed (the code decides); the grounding Source block shows both refs; the keyed probe is only composed against the key's own host.
8. **Renaming / rebinding** — `PUT` with an existing name and a different host requires `replace: true` (409 otherwise) so a typo cannot silently point a key at another host.
9. **Value too long / empty / whitespace** — 400 with the bound named; values are stripped.
10. **Store unreadable / corrupt JSON** — `list` returns an error the section shows; `resolve` returns `{}` (fail-open like dataset paths) and the sandbox names the key as missing; the backend logs the corruption once without contents.
11. **Delivery `header:Authorization`** — the probe sends `Authorization: <value>` verbatim (the user types `Bearer …` if the API needs the scheme); the memo does not invent auth schemes.
12. **Probe budget** — a keyed composed probe costs one call (+ redirects) from the run's `CallBudget`; dev/115 F6 (budget starvation) is unchanged by this memo and stays open.
13. **Solve job started before a key existed** — the round that runs after the save resolves it; earlier rounds' declines stand in the trail.
14. **Remove while a node references the name** — allowed; the row's confirmation names the consequence; no cascade edits to code.
15. **Reopened modal** — the value field is always empty; the list is re-fetched; no stale "saved" marker from a previous session.

## 7. Testing Strategy

**Backend (required before completion)**

- `test_users/test_connection_keys.py` (new): store round-trip, `0600` mode, atomic replace, name/host/delivery validation, `list` never returns values, `resolve` returns only requested known names and bumps `lastUsedAt`, corrupt file → `list` error / `resolve` `{}`, per-user isolation, guest key; routes: `GET/PUT/DELETE`, 401 without auth when auth is on, 409 rebind without `replace`, response bodies never contain `value` (assert against the raw JSON).
- `test_source_grounding.py`: `secret_names` (ast + regex fallback, cap 8, charset), the `secret` ref kind (known grounded / unknown refused with saved names), the credential-literal violation (positive and negative shapes: a 24-char id in a dataset path is *not* a key), the `credential-gated` hint when a saved host matches.
- `test_backend.py` (`/processPythonCode`): `secrets` in the payload only when the code names a key; unknown names omitted; byte-compat without.
- `test_execution/test_runner.py`: `run_through_node(secrets=...)` rides the payload; byte-compat without.
- `test_verified_rounds.py`: `secrets_fn` resolved per round from the candidate (round 1 without, round 2 with); `availableSecrets` in the correction inputs; the keyed composed probe (fake verify) with redacted evidence and **no** `verified_urls` growth; the host-aware `source-missing` remedy carrying `{kind: "connection-key", host}`.
- `test_verify.py` / `test_egress.py`: `verify_endpoint(headers=…, params=…)` threading; redaction of `url`/`finalUrl`/`detail`/`audit`.
- `test_common/test_redaction.py` (new): longest-first replacement, short values untouched, `None` passthrough, overlapping values.
- Sandbox tests (`utk_curio/sandbox/tests` or the existing sandbox suite): in-process injection (`curio_secret("a")` returns the value; unknown → the sentence with saved names; `os.environ` has no secret; stdout containing the value is redacted in the response); isolated: `build_exec_request` carries `secrets`, `run_node` injects and deletes it from the request, the child namespace has no values dict, `SENSITIVE_PATHS` covers the store file; a grep-guard test that no module under `sandbox/isolation` formats the request into a log call.
- Deterministic mirror of the Census scenario (A3 Task 3 with a key): fake exec fails without the key (HTML), the correction inputs list `availableSecrets`, the corrected code calls `curio_secret("census")`, the fake exec passes → executed review whose Source block lists the key ref and whose trail carries no value.

**Frontend (jest)**

- `connectionKeysApi` (list/put/delete shapes; no `value` in refs).
- `ConnectionKeysSection`: empty/loading/error/success; the value input never receives a saved value; Save clears the field; Remove copy names the consequence; a11y labels.
- Solve card / solve-node error / review card: the **Add key** action renders only for `remedy.kind === "connection-key"` and opens the section with host prefilled; the Source block renders the `secret` kind.
- `tsc --noEmit` clean; colour-literal guard green.

## 8. Acceptance Criteria

1. A user can save a key named `census` for `api.census.gov` in Settings → Connection keys; the response and the list never contain the value; the file is `0600` under `.curio/users/<key>/`.
2. A data-loading node whose code calls `curio_secret("census")` runs on Play with the real key and produces data; the saved spec, the runtime journal record, and the `/processPythonCode` request from the browser contain the name only.
3. The same node under the verified Solve loop (batch and per-node) resolves the key per round; a correction that adopts `curio_secret("census")` runs with it.
4. With no key saved, the Census scenario ends `source-missing` with the remedy *"Add a connection key for api.census.gov …"* and an **Add key** action that opens the form prefilled; after saving and clicking Solve again, the loop lands an executed review whose Source block shows *Connection key · census · api.census.gov* and whose trail carries no key value.
5. Agent-authored code naming an unknown key is refused before execution with the saved names listed; agent-authored code containing a credential-shaped literal is refused before execution.
6. A node that prints its key shows `«redacted:census»` in stdout everywhere it is displayed or stored.
7. Inside a run, `os.environ` carries no key and no file under scratch contains one (isolated mode test).
8. Removing a key makes the next Play fail with one sentence naming the missing key; nothing else changes.
9. No existing behaviour changes for code that calls no `curio_secret` (payloads byte-identical; suites green).
10. Docs: `docs/USAGE.md` and `docs/AGENT-CATALOG.md` describe the feature; dev/03 `DEC-074` row; T4's plaintext-at-rest status stated in both.

## 9. Recommended Commit Breakdown

- **Commit 1 — store + routes + redactor (backend, with tests)**: `users/connection_keys.py`, `common/redaction.py`, the three routes, `test_connection_keys.py`, `test_redaction.py`.
- **Commit 2 — resolution + wire + sandbox injection (both isolation modes, with tests)**: `SECRET_CALL_RE`/`secret_names`, `_resolve_exec_secrets`, `/processPythonCode` and `run_through_node` payloads, `validation.validate_candidate` passthrough, `/exec` shape check, `worker` + `protocol` + `child` injection, stdout/stderr redaction at the sandbox boundary, the env/log guard tests.
- **Commit 3 — agent path (with tests)**: `GroundingContext.secrets`, `availableSecrets` + rule, the `secret` ref kind and the credential-literal violation, the `credential-gated` hint, `secrets_fn` in the loop, keyed composed probes with redaction, the host-aware `source-missing` remedy, the two prompt clauses.
- **Commit 4 — frontend**: `connectionKeysApi.ts`, `ConnectionKeysSection`, the settings-modal wiring, the **Add key** action on the three cards, the Source block kind, jest suites.
- **Commit 5 — docs + ledgers**: `docs/USAGE.md`, `docs/AGENT-CATALOG.md`, `docs/NODE-CATALOG.md`, `docs/09` gate note; `plans/` (untracked): dev/03 `DEC-074` + DEC-022 T4 note, dev/00 row, `BL-P5-20260908-50`, `3.1`, dev/115 F7 closure, this memo's status.

## 10. Engineering Quality Checklist

- One call-shape regex (`SECRET_CALL_RE`) exported from `source_grounding.py`; one resolver per caller mirroring `dataset_paths`; one `ConnectionKeyStore`; one `redact`.
- Values exist in exactly three places at run time: the store file (0600), the execution request in flight, the sandbox namespace closure — and are redacted at the sandbox boundary on the way back.
- No environment variable, no staged file, no log line, no proposal, no transcript, no spec ever holds a value (tests pin each).
- Types explicit: `ConnectionKeyRef` frozen dataclass; TS `ConnectionKeyRef` mirrors it; `secrets: dict[str, str] | None` everywhere on the wire.
- Request-context discipline (dev/115 lesson 1): the user key and the store handle are captured in the request thread; the job thread only calls the closure.
- UI: existing modal, masked input, tokens only, a11y labels, no unmount/remount on save.
- Loading/empty/error/success handled in the section and on the cards' action.
- Tests cover the store, both execution callers, both isolation modes, the gate, the loop, redaction, the cards; the Census mirror scenario is the regression fixture.
- Follows the `curio_dataset_path` precedent the repo already documents; deviations (no staging, deletion from the request after injection) are stated with reasons.
- Honesty lines kept verbatim in docs: plaintext at rest until T4; a key returned as data is not scanned; guest mode shares the store.

## Open questions for the owner (non-blocking — defaults stated)

1. **Name of the helper**: `curio_secret("<name>")` (default; parallels `curio_dataset_path`) vs `curio_key`. Default kept unless the owner prefers the user-facing word.
2. **Keyed probes**: send the key on composed probes for `query:`/`header:` deliveries (default: yes, redacted, one budget call) or never probe with keys and let the run be the only evidence.
3. **Guest mode**: shared `guest` store with the banner (default) or disable the section when `CURIO_NO_AUTH=1`.
4. **Editor hint for user-typed literals** (edge case 2): non-blocking hint in a later memo (default) or in scope now.

## Follow-ups (recorded, not delivered)

- **F1** T4: encrypted-at-rest store behind `ConnectionKeyStore` (one class swap); migrate the LLM key column into it.
- **F2** Streetvision's browser-posted Google Maps key → a connection key.
- **F3** dev/115 F6 (egress budget starvation) — unchanged here; a keyed probe adds one call per failed round.
- **F4** Editor-side hint when a user types a credential literal into node code.

## Live re-test (2026-09-09, gemma4, `curio start` stack, a real Census key saved through Settings → Connection keys)

The owner saved the key in the UI (name `census`, host `api.census.gov`, sent as query parameter `key`); the driver (`live_retest.py task3key`) reused the shared-guest store and never saw the value. Four passes; each failure the deterministic mirror had not predicted became a fixture (dev/54 doctrine):

| Pass | Outcome | Harness gap → fix (all in `ab87e8fb`) |
|---|---|---|
| 1 | Round 1 (proposal's code, no key): Missing Key page, named in the endpoint line. Round 2: the correction used `api_key = curio_secret("census")` and `params["key"] = api_key` — the key reached the API and Census answered its real error, `400 error: invalid 'in' argument`. Round 3 repeated round 2 with only comments changed. FAIL. | (a) a `curio_secret(...)` value in `params` (direct or through a name) made the request non-composable, so no composed or keyed probe ran → it now composes as a placeholder and the probe sends the saved value in its place through the keyed path (uncached, never a verified source, redacted; the entry shows the call). (b) a comment-only repeat → `repeated-attempt`, not run, judged after the gate, the next round told what to change. |
| 2 | Round 2's evidence read *"the egress budget was spent before this URL — not checked"*: the run-wide budget of 4 was gone after round 1 (gate probe + composed probe with redirect + keyed probe). Round 3 reached the API: `400 unknown/unsupported geography hierarchy` (`for=community area:*` is not a Census geography). FAIL. | (c) the verified loop owns its budget (`_LOOP_EGRESS_CALLS = 4·(1+2)+2`) and shares the probe cache/verified map with the caller. dev/115 F6 is thereby answered for the loop; the Dataset Finder's candidate starvation is still open. |
| 3 | gemma4 stopped at the Dataset Finder's candidates card twice and never proposed (DEC-047: the user confirms). Not a harness fault — the driver now emulates the card's builder prompt for the verified `acs5` row. | none |
| 4 | **PASS.** Round 1 (no key): Missing Key, named. Round 2: `api_key = curio_secret("census")`, `for=tract:*`, `in=state:17, county:031` → executed, a dataframe in 9.7 s. The executed review's Source block reads *External · https://api.census.gov/data/2022/acs/acs5 · verified · Connection key · census · api.census.gov*; its preview carries `curio_secret("census")` and no value; leak scans over the reply, the event stream, the node-attachment session and the saved spec found no key material (the driver scanned for the value only when it held it — it did not, so this is a scan for the shape, not the secret). The node's saved content is the pre-Solve code until the user applies the review, as designed. | — |

Acceptance criteria 2–4 and 6–7 are met live; criterion 1 was exercised by the owner in the UI. Suites after the fixes: backend `test_agents` + `test_execution` + `test_backend` + `test_users` + `test_redaction` 1236 passed / 2 skipped (fixtures that scripted the same failing reply every round now vary it); frontend unchanged.
