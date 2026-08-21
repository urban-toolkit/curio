# dev/91 — Package backend sandbox (dev/89 Follow-up A): on-demand, process-isolated execution of agent-generated server-side package code

**Status: IMPLEMENTED (2026-08-21) — commits 1–6 landed (`1f4fca57`, `2adf412a`, `a68ed44a`, `664bc8c4`, `6059c151`, + docs); DEC-061 minted; BL-P5-20260821-34. §0.1 Option 3 adopted (venv deferred, interpreter/overlay parameterized seam).**
Prereqs: dev/89 (build service, DEC-059) and dev/90 (prompt-driven authoring, DEC-060) are complete and live-verified through A16. This memo takes the explicit Follow-up A commitment: *"a permissioned, process-isolated runtime for generated server-side package code — never imported into Curio's host backend process."*

---

## 0. Evidence — what execution looks like today (read before judging the design)

The design below is grounded in a code audit (2026-08-21), not the architecture we wish we had:

- **The existing "sandbox" is not a boundary.** Python node code runs via `exec(f"def userCode(arg):\n{code}", ns)` in a warm, long-lived Flask process (`utk_curio/sandbox/app/worker.py:202`) with **full `__builtins__`** (`worker.py:94`), the backend's **inherited environment** — API keys included (`utk_curio/main.py:591-601`) — no rlimits, no process kill controls, and one global lock serializing all executions (`worker.py:185`). Generated backend code must never extend this surface.
- **Nothing imports package Python server-side today.** A repo-wide search for dynamic import/exec of installed package code finds zero call sites. Package `.py` files under `sources/` are read as *text* for editor starters only (`packages/starters.py:66`). A backend-bearing package is a **genuinely new trust edge**, not an extension of an existing one.
- **The isolation primitive already exists and is proven**: `build_workspace.run_worker` + `WorkerLimits` — ephemeral 4-dir workspace, read-only `input/`, from-scratch minimal env (`_minimal_env`: `PATH=/usr/bin:/bin`, no inherited secrets), rlimits (`CPU/FSIZE/NOFILE` everywhere; `AS/NPROC` Linux-only, honestly recorded in `limits_applied`), `start_new_session=True` + `os.killpg(SIGKILL)`, wall clock, capped output pipes, and `sanitize_diagnostic`. Its docstring states the one hole plainly: **no portable OS network namespace on macOS** — the same honesty this memo adopts.
- **Python deps**: reviewed at build (`build_deps.review_python_dependencies` — nothing installed), pip'd into the **host interpreter** at Apply (`build_promotion.py:220-236`, `pip_runner`). There is no per-package venv anywhere; §0.1 is the full investigation of that surface and the evidence-backed decision on it.
- **The current "package needs a backend" answer is a hand-written first-party blueprint** (`app/streetvision/`, `docs/EXTENDING.md` §"backend"), which agent authoring cannot and must not touch.
- **Frontend dispatch is literal-keyed**, not registry-driven: `CodeEditor.tsx:201` routes to the JS interpreter only for the hardcoded `curio.builtin/js-computation` id; every package template — whatever its declared `engine` — posts to `/processPythonCode`. Backend-handler dispatch must be descriptor-driven, not another literal.

### 0.1 The shared-interpreter dependency surface — the per-package venv investigation

Every package Python dependency in the system lands in **one interpreter**: whichever conda env/venv the backend itself runs under (`sys.executable`, stated as a design choice at `pip_runner.py:14-16`). This subsection is the complete evidence for what that means, and grounds the venv decision below.

**Five distinct write paths into that one interpreter:**

| # | Path | Where | Conflict check | Failure posture |
|---|------|-------|----------------|-----------------|
| 1 | Launcher startup walker | `main.py:681-789` (`install_manifest_dependencies`) | `resolver.merge_python_deps` — a conflicted dep is **logged as a warning and silently EXCLUDED from the merged install set** (`main.py:770-776`; `merge_python_deps` drops conflicted names from `merged`, `resolver.py:262-277`), so a package can boot with its deps missing | pip failure = `sys.exit(1)` — one bad dep refuses the whole app boot (`main.py:786-789`) |
| 2 | Catalog install | `services.py:108-151` (`_ensure_user_store_install`) | **None** — installs the manifest's deps directly, only per-dep `_is_satisfied` | pip failure rolls back the copied files (`shutil.rmtree`) and surfaces the error |
| 3 | Build-service Apply | `build_promotion.py:220-236` | strongest gate, but at **build review time**: `review_python_dependencies` (`build_deps.py:487-556`) intersects the draft against every installed manifest → `py-conflict` **block** finding; pre-existing installed-vs-installed conflicts are deliberately skipped (`continue`, `:545`) | pip failure at promote = `_rollback_locked` + honest 502 |
| 4 | Manual Libraries UI | `routes.py:1243` (POST `/libraries`) | **None** | pip failure = 502, library not recorded |
| 5 | The sandbox's own pip endpoint | `sandbox/app/api.py:234` (`POST /installPackages`, reachable via backend `api/routes.py:591`) | **None — and no version pin at all**; name-regex validation only | fire-and-report |

**The upgrade blast radius (the sharpest fact):** `install_python_deps` skips a dep only when the installed version already satisfies the constraint (`_is_satisfied`, `pip_runner.py:88-115`); otherwise pip installs the spec. A draft declaring `pandas>=2.3` on a host running 2.2 therefore **upgrades the shared pandas for every package, every node, and Curio's own backend**. The reassuring docstring claim — "never touches Curio's core pyproject deps" (`pip_runner.py:20-24`) — is scoped to **uninstall only** (core libs appear in no manifest, so the manifest walk never selects them); the install direction has no such guard, no `--constraint` freeze of the host env, and pip's resolver may additionally upgrade or downgrade **transitive** dependencies of unrelated packages at its own discretion.

**Uninstall ref-counting is partial:** `uninstall_python_deps` pushes ref-counting to callers (`pip_runner.py:206-212`). The prune path honors it by walking surviving manifests (`_python_deps_unique_to_pruned`, `services.py:626-655`) and the Libraries DELETE checks `_any_package_declares` (`routes.py:1291-1317`) — but the ordinary `DELETE /api/packages/<dir_name>` (`routes.py:474-486` → `installer.uninstall_packageage`) pip-uninstalls **nothing** (deps accrete forever, the safe-but-dirty direction), and the prune's reference set consults manifests **only**: a library the user also added manually through the Libraries UI can be pip-uninstalled out from under them when a package that happened to declare the same name is pruned.

**Warm-process staleness:** the legacy sandbox pre-imports the heavy stack once at boot (`_worker_init`, `sandbox/app/worker.py:54-100`) and every node execution gets a *copy* of those already-imported modules (`ns = dict(_globals_cache)`, `worker.py:201`). An Apply-time pip **upgrade** of a pre-imported library (pandas, geopandas, pyproj…) does not take effect in the running sandbox until restart — nodes keep executing against the boot-time version while the backend's next fresh import sees the new one. Brand-new deps are importable immediately (shared site-packages); it is precisely *version changes* of warm libraries that go split-brain.

**What a per-package venv would actually cost, per consumer:**

- *The legacy warm sandbox (node code)* — infeasible without a redesign: it is ONE resident process whose entire latency design is the shared warm import cache; per-package interpreters contradict it structurally. Changing node execution is explicitly out of this memo's scope.
- *Full venv per package* — technically trivial to create (`python -m venv`, no system site-packages), operationally expensive: the common declared deps are exactly the heavy geo/data stack, so every backend-bearing package would duplicate multi-GB trees (torch-class deps ~5 GB each), multiply Apply-time pip minutes per package, and require a disk-quota story that does not exist. Wrong cost curve for the expected fleet of small handler packages.
- *Per-package overlay* (`pip install --target <pkg-overlay>` + `PYTHONPATH` prepend in the worker env) — the credible middle ground: host site-packages stays untouched (kills the upgrade blast radius for handler deps), cheap for small pure-Python deps, no resident-process problem because backend workers are freshly spawned per invocation. Known sharp edge: overlay shadowing can produce mixed-version import trees (overlay pandas importing base numpy), so it needs compatible-wheel pinning discipline before it can be defaulted.

**Evidence-backed decision (venv posture for this memo):**

- *Option 1 — full per-package venvs now*: rejected on the cost evidence above (duplication of the heavy stack, quota story, Apply latency).
- *Option 2 — `--target` overlay now*: attractive, but it changes the dependency story for the whole package system (review rows, SBOM meaning, `is_satisfied` semantics, the launcher walker) mid-memo; the shadowing edge needs its own validation. Too much scope riding on a sandbox memo.
- *Option 3 (RECOMMENDED) — defer, but make the seam a parameter*: slice 1 keeps review-at-build + pip-at-Apply exactly as promoted packages do today, and `backend_runtime.invoke_handler` treats the **interpreter path and an optional `PYTHONPATH` overlay dir as invocation parameters** (operator-pinnable `CURIO_BACKEND_SANDBOX_PYTHON`, per-package overlay dir reserved in the workspace layout). Overlay isolation (Option 2) then lands later as a contained hardening — new parameter values, zero contract or harness changes. Until then, the blast radius above is the *documented, reviewed* reality: the build path (row 3) is the only pip path with a conflict gate, and backend-bearing drafts go through it.

This memo makes the shared-interpreter reality **strictly better observed, never worse**: backend deps ride the same block-capable review gate as all draft deps, the probe phase catches import-level breakage before Apply, and edge case 9 (§6) plus the staleness fact above get regression coverage.

## 1. Problem Statement

Agents can author complete frontend packages (dev/89/90), but any need with a server-side component — compute that shouldn't run in a browser, libraries with no JS equivalent, deterministic heavy transforms — dead-ends at a refusal: the Package Builder reports *"generated backend execution awaits the Curio package backend sandbox (Follow-up A)"* (dev/89 §5, DOD item 15). The refusal is correct: the only server-side execution surfaces today are (a) the warm `exec` process with full builtins and the backend's secrets in env, and (b) first-party blueprints imported into the host process. Loading generated code into either would hand model-authored code the host's credentials, filesystem, and database locks.

Expected behavior: a package draft may carry declared backend **handlers** — small pure Python entry points — that execute **on demand, one request per short-lived, resource-limited, env-scrubbed worker process**, under a versioned JSON contract, invoked through one authenticated host endpoint, with per-invocation audit records and honest failure surfaces. The host never imports the code; a crashed or hostile handler can burn its own worker's CPU quota and nothing else.

Why it matters: this is the last structural refusal in the authoring surface (correctness/completeness); it closes it **without weakening** dev/89's boundaries (review, provenance, exact-digest promotion), and the on-demand model deliberately avoids resident generated services — which is what keeps Follow-up B (activation/restart lifecycle) a separate, smaller problem.

## 2. Scope

Included:

- **Manifest/schema (additive, `node-package.v4`)**: optional top-level `backend` object — `{ "entry": "backend/<file>.py", "handlers": [{ "name": "<a-z0-9-]+", "timeoutClass": "quick"|"standard" }] }`; optional per-template `backendHandler: "<name>"` linking a template's Run to a handler. A `backend` declaration REQUIRES the `server-code` permission string in `permissions[]` (surfaced at review); network use additionally requires `server-network`.
- **Installer**: new allowed top-level dir `backend/` (same path-safety rules as `sources/`); installed handler entry digest recorded in the project lockfile row at promote time (verify-on-read at invocation).
- **New runtime `packages/backend_runtime.py`** + Curio-owned harness `packages/backend_harness.py`: `invoke_handler(user_key, dir_name, handler, payload)` spawns one `build_workspace.run_worker` per invocation.
- **Contract `curio.pkgbackend.v1`** (versioned envelope, §4).
- **Build service integration**: `build_models` accepts `backend` files + declaration under existing caps; a static policy scan with *blocking findings*; a **probe phase** (harness dry-run of every declared handler with a synthetic ping inside the build workspace) that gates Apply exactly as preview gates looks; provenance records handlers, scan verdicts, probe results, and applied limits.
- **Host route** `POST /api/packages/<dir_name>/backend/<handler>` (auth'd; 404 unknown/undeclared, 403 missing permission, 413 payload cap, 422 malformed envelope, 502 honest sanitized worker failure).
- **Audit ledger**: append-only per-package day files `.curio/users/<key>/package-backend-ledger/<dir_name>/YYYY-MM-DD.jsonl` (invocation id, handler, payload/result byte sizes, status, duration, limits applied — never payload contents); a `packageBackendLedgerDays` key joins the dev/88 `agents-retention.json` declaration (documented in `docs/RETENTION.md`; the unknown-key warning list gains it).
- **Frontend**: registry-descriptor-driven dispatch — a node whose descriptor carries `backendHandler` runs through the new endpoint instead of `/processPythonCode`; loading/error/success through the existing node feedback surfaces. `usePackageBackendRun` hook owns the call; no behavior-bundle network (the dev/90 authoring contract's "no network in behaviors" stands — dispatch lives in the runner, not the behavior).
- **Prompts/contract**: the Package Builder instruction's backend-refusal paragraph is replaced by the backend authoring contract (§5 of the prompt); `_BUILD_REQUEST_CONTRACT` (A8) gains the backend keys and the handler shape; refusals for what remains unsupported (resident services, secrets, undeclared network) name this memo's boundaries.
- **Docs**: `docs/EXTENDING.md` §8 backend paragraph rewritten; DEC-061 minted in dev/03; build-ledger entry; `docs/RETENTION.md` row.

Out of scope (explicit, most deferred to Follow-up B or later hardening):

- **Resident/long-running generated services, ports, WebSockets, background jobs** — Follow-up B territory; the on-demand model is the whole point of this slice.
- **Secret mediation**: workers get a scrubbed env and NO credentials, period. A mediated token broker is future work; a handler needing an API key is a blocking finding, not a smuggled env var.
- **Per-package Python virtualenvs / dependency overlays**: deferred per the §0.1 evidence-backed decision (Option 3) — deps continue to review-at-build + pip-at-Apply into the host interpreter, the only pip path with a conflict-blocking gate. The worker runs that interpreter binary with a scrubbed env, and §3 keeps the interpreter path + overlay dir invocation *parameters* so overlay isolation lands later without touching the contract or harness.
- **Dataset/DuckDB/store access from handlers**: none. Handlers are pure `payload → result`; node inputs arrive in the payload. No DB locks, no data-policy surface.
- **OS-level network namespacing on macOS** (impossible portably — the build_workspace precedent): the layered posture in §3 applies.
- Modifying the legacy warm-exec sandbox, first-party blueprints, or `/processPythonCode` semantics for existing nodes.

## 3. Recommended Implementation Approach

**Execution model — one worker per invocation, nothing resident.** `invoke_handler`:

1. Reads the installed package's `backend/` entry file, re-hashes it against the lockfile-pinned digest (verify-on-read — the staging-store pattern; a mismatch is a 409-class refusal naming reinstall, never a silent run).
2. Creates a `build_workspace` (`input/` = harness + handler file + `payload.json`, read-only; `work/`, `output/` writable), plus one writable **persistent** per-package data dir passed as `CURIO_PKG_DATA_DIR` (`.curio/users/<key>/package-backend-data/<dir_name>/`, byte-capped, size re-checked after each invocation — over-cap = handler error next run until it cleans up, stated in the contract).
3. Runs `run_worker([interpreter, harness, ...])` under `WorkerLimits` chosen by the handler's `timeoutClass` (reusing `LIMITS_BY_TIMEOUT_CLASS`), concurrency-capped by an in-process semaphore (default 2 — the sandbox never multiplies load unboundedly). The interpreter path is a parameter (default `sys.executable`, operator-pinnable via `CURIO_BACKEND_SANDBOX_PYTHON`) and the workspace layout reserves a per-package overlay dir slot — the §0.1 Option-2 hardening (a `pip --target` overlay on `PYTHONPATH`) becomes new parameter values, never a redesign.
4. The harness (Curio-owned, copied fresh per invocation — never from the package) loads the handler file with `runpy`-style isolated namespace **inside the already-limited child**, locates `def handle(payload):`, applies the in-process network guard (below), calls it once, and writes the reply envelope to `output/reply.json`.
5. `backend_runtime` validates the envelope, caps sizes, sanitizes diagnostics, appends the audit record, returns.

**The trust boundary, stated honestly (the build_workspace posture):** the HARD guarantees are process isolation, rlimits, wall-clock + `killpg` termination, from-scratch env (no secrets exist to steal), read-only inputs, and byte caps. The network layers are: (1) `server-network` **declared permission** reviewed by the user at install (the existing package permissions dialog); (2) an in-process socket guard the harness installs when the permission is absent — loud, but documented as advisory (adversarial code can undo in-process guards; benign generated code cannot accidentally exfiltrate); (3) an optional operator-pinned strengthener `CURIO_BACKEND_SANDBOX_ISOLATOR` (e.g. `bwrap`/`unshare -n` on Linux), version-probed into provenance — the DEC-057/A9 operator-declaration posture: declared and loud, never silently assumed.

**Contract `curio.pkgbackend.v1`.** Request `payload.json`: `{ "contract": "curio.pkgbackend.v1", "handler": "<name>", "payload": <JSON ≤ 2 MiB> }`. Reply: `{ "contract": "curio.pkgbackend.v1", "ok": true, "result": <JSON ≤ 8 MiB> }` or `{ "ok": false, "error": "<sanitized>", "kind": "handler-error"|"contract-error" }`. Runner-level failures (timeout, output-limit, killed) are reported by `backend_runtime` from `WorkerResult.status`, never invented by the handler. The `ping` request (`{"__probe__": true}`) must be answered `{"ok": true}` by every handler — that is the build-time probe and the Apply-time health check.

**Build pipeline placement.** New phase `probing` between `validating` and `previewing` (forward-only order preserved; skipped when the draft has no `backend`). The static policy scan runs in `validating`: blocking findings for `import ctypes`, `subprocess`, `multiprocessing`, `eval(`/`exec(`/`compile(`, `__import__`, `open(` outside `CURIO_PKG_DATA_DIR` idioms is NOT blocked (filesystem writes are already rlimit/workspace-bounded — don't pretend a regex is a jail; the scan blocks only the escape-hatch families and warns otherwise). Socket/net imports are a **warning** when `server-network` is declared and a **block** when not. Every finding names the fix — the A4/A5 refusal lesson.

**Why on-demand and not resident:** no activation/restart problem (Follow-up B shrinks to "resident services, versions, draining"); no crash-loop state machine; upgrade = ordinary exact-digest promote (next invocation reads the new digest); rollback = existing promotion rollback. Latency cost (~worker spawn) is acceptable for node-run compute and stated in the docs.

**Ownership/naming** follows dev/89's component style: `backend_runtime.py` (runtime + audit), `backend_harness.py` (child-side), `backend_policy.py` (scan), probe logic in `build_pipeline.py` beside preview. One contract constant module-owned like `PREVIEW_CONTRACT_VERSION`.

## 4. Data and State Handling

- **Source of truth**: the installed package dir (exact promoted digest) for code; the project lockfile row for the pinned handler-entry digest; `agents-retention.json` for ledger retention; provenance for scan/probe verdicts.
- **Request flow**: node Run → `usePackageBackendRun` → `POST /api/packages/<dir>/backend/<handler>` → `invoke_handler` → worker → envelope → node output state. The node's upstream input and `data.code`-style content ride the payload; the reply's `result` becomes the node output through the existing output path.
- **No cross-invocation state** except `CURIO_PKG_DATA_DIR` (explicitly persistent, byte-capped, package-scoped, user-scoped).
- **Races**: the per-target promote lock already serializes install vs. invocation digest reads (verify-on-read makes a mid-promote invocation fail loudly, not run half-installed code); the concurrency semaphore bounds parallel workers; repeated user Runs are idempotent at the contract level (the runtime never retries silently — the dev/90 "report failure plainly" rule).
- **Loading/empty/error/success**: the node surfaces the existing run feedback; a 502 carries the sanitized diagnostic; a probe-failed draft never reaches Apply, so "installed but broken" requires drift, which verify-on-read catches.

## 5. UI and UX Requirements

- The **review card** for a backend-bearing draft states, above the fold: "Runs server-side code in the package sandbox" plus the declared permissions (`server-code`, `server-network` when present) and the handler list with timeout classes — the user judges the trust edge before Apply, exactly like dependency/SBOM findings today.
- The **install permissions dialog** (DEC-035 surface) lists `server-code`/`server-network` with one-line plain-language meanings.
- Node Run on a handler-backed template shows the standard running state; failures render the sanitized error in the node's existing error surface — no toast-only errors, no silent console-only failures.
- Accessibility: permission rows and error text are ordinary text nodes in existing components (no new interaction patterns); the review card additions are announced as part of the card group.
- No layout shift: the backend rows reuse the card's existing meta-row styles.

## 6. Edge Cases

1. Handler file missing/renamed after install (manual tampering): digest verify-on-read refuses with reinstall guidance.
2. Handler never returns / infinite loop: wall clock + CPU rlimit → `killpg`; status `timeout` reported honestly.
3. Handler prints megabytes: capped pipes → `output-limit`, sanitized.
4. Reply not valid JSON / wrong contract version / oversized `result`: `contract-error`, the raw bytes never reach the client.
5. Undeclared handler name, or handler declared but permission missing from manifest: 404 / build-time blocking finding respectively — the mismatch cannot survive the build.
6. Two nodes invoking concurrently: semaphore queues; both complete; ledger records both.
7. `CURIO_PKG_DATA_DIR` over cap: next invocation gets a stated handler-visible error until the handler (or uninstall) clears it.
8. Package uninstalled between node render and Run: 404 with the standard stale-package message.
9. Python dep of the handler missing at runtime (host-interpreter drift — the §0.1 shared-interpreter reality: another package's uninstall/prune or a manual Libraries removal can strip a dep after this package's review): harness import error surfaces as `handler-error` naming the module — matching the existing workflow-deps check surface, plus review-time deps were already SBOM'd.
9b. A later install/Apply **upgrades** a shared dep past what this package's handler was probed against (§0.1 upgrade blast radius): unlike the warm sandbox's split-brain staleness, backend workers are freshly spawned, so they see the new version immediately and fail loudly (a `handler-error` naming the import/behavior mismatch) rather than silently running two versions; the invocation ledger's recorded failure is the diagnosis trail.
10. macOS vs Linux limits divergence: `limits_applied` recorded per invocation in the ledger and probe provenance — never claimed stronger than applied (the build_workspace honesty rule).
11. Malicious-looking payloads (huge, deeply nested): 2 MiB cap + JSON depth cap at the route; 413/422 before any worker spawns.
12. Model tries to ship a Flask blueprint / `app.route` / resident loop: policy-scan blocking finding naming the on-demand contract.

## 7. Testing Strategy

- **Unit (backend)**: envelope parse/validate + size caps; policy scan block/warn matrix (each family, declared vs undeclared network); digest verify-on-read refusal; ledger append + retention-key recognition; `_minimal_env`-based no-secret assertion (worker env contains no key from a poisoned parent env); data-dir cap.
- **Integration (backend, real subprocess)**: a genuine handler runs end-to-end (`handle` returning payload-derived JSON); timeout kill; output-limit kill; probe phase pass/fail gating a build; promotion pins the handler digest; route auth/404/403/413/422/502 matrix; concurrent invocations under the semaphore.
- **Build-service**: `build_models` backend parsing (caps, path rules, handler-name grammar); pipeline order with `probing`; provenance contents; packager includes `backend/` deterministically.
- **Agents (DOD-style, `test_backend_package_dod.py`)**: fake-provider Researcher/Package-Builder chain authors a backend-bearing draft → scan/probe → review card fields → Apply → route invocation returns the computed result; and the violating scenario (subprocess import) blocks with the naming finding.
- **Frontend (jest)**: descriptor-driven dispatch chooses the backend route for `backendHandler` templates and `/processPythonCode` otherwise; error state renders the sanitized message; permissions rows render on the review card.
- **Regression**: existing suites (installer allowlist, promotion journal, preview gating, A8 contract markers) extended, never weakened.

## 8. Acceptance Criteria

1. A reviewed, applied backend-bearing package answers `POST /api/packages/<dir>/backend/<handler>` with the handler's computed result; the host process never imports the handler module (assertable: no `sys.modules` entry, invocation works with host-side import of the file monkeypatched to raise).
2. Worker processes run with scrubbed env (no inherited secrets), rlimits, wall-clock kill, and capped I/O; what was actually applied is recorded per invocation.
3. A draft whose backend fails the policy scan or the probe **cannot reach Apply**; the finding names the violated rule and the fix.
4. Undeclared handlers, missing permissions, oversized payloads, and contract violations return the specified 4xx/502s with sanitized text; nothing raw from the worker reaches the client.
5. The review card and install dialog state server-code (and network, when declared) before Apply; nothing about the trust edge is discoverable only after install.
6. Every invocation appends one audit record; retention honors the operator declaration; unknown-key warnings stay intact.
7. Handler-backed node templates Run through the new route via registry dispatch; every other template's execution path is byte-identical to today.
8. The Package Builder authors backend handlers under the prompt contract; needs beyond the contract (resident service, secrets, undeclared network) are findings naming Follow-up B / the deferred hardening — never inventions.
9. All existing tests pass unamended except where a test pinned the old refusal text.

## 9. Recommended Commit Breakdown

- **Commit 1 — contract + manifest + installer**: `backend` manifest object, `backendHandler` template field, `server-code`/`server-network` permissions, schema v4 additive update, installer `backend/` dir + path rules, envelope module with `curio.pkgbackend.v1`; unit tests.
- **Commit 2 — runtime + harness + ledger**: `backend_runtime.invoke_handler` (verify-on-read, workspace, semaphore, data dir, audit append), `backend_harness.py`, retention key + docs row; unit + real-subprocess integration tests.
- **Commit 3 — build service**: `build_models` backend parsing, `backend_policy.py` scan, `probing` phase in jobs/pipeline, provenance + packager + promotion digest pinning; tests.
- **Commit 4 — route + review surfaces**: the authenticated route with the full status matrix; review-card fields + install-dialog permission rows (backend mint carries the handler summary); backend tests + jest for the card.
- **Commit 5 — frontend dispatch**: registry-descriptor `backendHandler` dispatch + `usePackageBackendRun` + node feedback wiring; jest.
- **Commit 6 — prompts, DOD, docs**: Package Builder backend contract section (replacing the refusal), `_BUILD_REQUEST_CONTRACT` backend keys, `test_backend_package_dod.py`, `docs/EXTENDING.md` §8 rewrite, DEC-061 in dev/03, build-ledger entry.

## 10. Engineering Quality Checklist

- [ ] No generated code is imported or exec'd in the host backend or the legacy warm sandbox — the only execution path is the per-invocation worker.
- [ ] One envelope contract module; route, runtime, harness, probe, and prompt all reference it — no drifting duplicate shapes (the A15 lesson: two spellings need a pinning test).
- [ ] Isolation claims match `limits_applied` reality per platform; nothing stronger is claimed than applied.
- [ ] Refusals and findings name the fix (A4/A5 lesson); policy scan families are blocked/warned per declared permissions, never silently stripped.
- [ ] Review-before-apply, exact-digest promotion, provenance, and journal semantics are untouched in strength.
- [ ] Frontend dispatch is registry-driven; no new hardcoded template literals.
- [ ] Secrets: none reach workers; the deferral of mediation is documented, not fudged.
- [ ] Ledger/retention integrate with the dev/88 declaration; day files archive by move, never rewrite.
- [ ] Follow-up B's remaining scope (resident services, draining, version routing) is restated at the end of the docs update.
