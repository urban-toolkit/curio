# dev/92 — Activation lifecycle for backend-bearing packages (dev/89 Follow-up B): re-scoped after dev/91 — promote/invoke consistency, restart honesty, crash-loop quarantine; resident services descoped demand-driven

**Status: IMPLEMENTED (2026-08-23) — commits 1–4 landed (`e783dfe4`, `0f339338`, `fe49337d`, + docs); DEC-064 minted (planned id DEC-062 was taken by dev/93 while this memo waited); BL-P5-20260823-37. Option 3 adopted; dev/89 Follow-up B closed as re-scoped.**
Prereq: dev/91 (DEC-061) is implemented and live: the on-demand package backend sandbox, `curio.pkgbackend.v1`, probing phase, entry pins, invocation route, registry dispatch.

---

## 0. Evidence — what Follow-up B still means after dev/91

Follow-up B's original mandate (dev/89 §2): *"start/hot-load versus controlled restart, readiness probes, in-flight request/job draining, version routing, rollback to the prior healthy package, crash-loop handling, and clear user-visible restart-required/activating/failed states."* The dev/91 on-demand model **already absorbed most of it structurally**:

| Original B item | Post-dev/91 reality |
|---|---|
| start / hot-load vs restart | Nothing is resident — an upgrade is an ordinary exact-digest promote; the next invocation reads the new pin. No generated process ever starts. |
| readiness probes | The build's `probing` phase + the harness's load-and-resolve health check (dev/91 §3) — a handler that cannot load never reaches Apply. |
| rollback to prior healthy package | The promotion journal's backup/rollback (dev/89 §3.10), unchanged and already honest (`rolled-back` vs `rollback-failed`). |
| version routing | Packages are dir-per-major; nodes reference versioned canonical ids; the route addresses `<pkg>@<major>` explicitly. Cross-major migration was never in scope. |
| activating / failed states | The journal's `awaiting-activation → confirm_registry_ready → confirm_nodes_created` flow (frontend-confirmed, backup held until complete). |

What the code audit (2026-08-21) shows **actually remains** — three real gaps, none of them resident-service-shaped:

**B-1 — the promote↔invoke consistency window.** `_target_lock` serializes *promotions* per (user, target) (`build_promotion.py:119-131`); `backend_runtime.invoke_handler` never takes it. The installer's replace is `shutil.rmtree(final_dest)` **then** `shutil.move(staging, final_dest)` — not atomic: during an Apply, a concurrent invocation can catch the package dir absent (404 "not installed") or catch new files against the not-yet-rewritten pin (409 "reinstall"). The failure direction is SAFE — reads fail loudly, mixed-version code cannot execute (rmtree empties before move) — but the user sees transient, wrong-sounding refusals for a package they are in the middle of installing. Every refusal message lies slightly: "reinstall the package" during the reinstall itself.

**B-2 — the discarded restart signal.** Promote calls `pip_runner.install_python_deps(py_deps)` and **throws away the returned `InstallReport`** (`build_promotion.py:238` — a bare call; the catalog path `services.py:_ensure_user_store_install` likewise). That report's `installed` vs `skipped` split is precisely the dev/91 §0.1 staleness signal: a dep that was **actually installed or upgraded** landed in the one shared interpreter while the legacy warm sandbox keeps executing every node against its boot-time imports (`sandbox/app/worker.py:54-100` pre-imports the heavy stack once into `_globals_cache`; copies of *already-imported* modules go to every node run). A version change is split-brain until Curio restarts — and today **nothing tells anyone**. "Restart required" states were in B's mandate; the honest, cheap version is real today and needs no resident services.

**B-3 — no crash-loop handling.** A backend package whose worker infrastructure keeps failing (timeout, killed, no reply, contract-violating reply) is re-invocable without limit: every Run click spawns a fresh worker that can burn its full wall-clock (30s at the `quick` tier) before failing again. The invocation ledger *records* each failure (dev/91) but never *acts*; the concurrency semaphore bounds parallelism, not repetition. B's "crash-loop handling" reduces, in the on-demand model, to a quarantine breaker — and all the state it needs is already in the ledger row taxonomy (`worker-*`/`no-reply`/`bad-reply` vs the benign `reply-handler-error`).

**Resident generated services have zero demand evidence.** No agent request, recorded scenario, or user ask has needed a long-lived generated process; the one real "package needs a server" case in the codebase (streetvision) is a first-party, hand-written blueprint and stays that way. Every dev/91 refusal surface already names Follow-up B for such needs — none has fired outside tests.

### Evidence-backed decision summary

- *Option 1 — build the full resident-service lifecycle now* (process supervisor, ports, hot-load, request draining, health/readiness loops, crash-restart backoff, per-version routing): rejected — speculative (zero demand), the largest possible expansion of the generated-code trust surface, and it would re-open exactly the activation complexity dev/91's on-demand design eliminated on purpose.
- *Option 2 — close Follow-up B as "absorbed by dev/91"*: rejected — B-1 is a live defect (wrong-sounding transient refusals during Apply), B-2 is an honesty debt against DEC-057's declared-and-loud posture (a split-brain interpreter with no notice), and B-3 leaves a stated mandate item ("crash-loop handling") genuinely unhandled.
- *Option 3 (RECOMMENDED) — deliver the three real gaps as a thin slice; descope resident services demand-driven* (the DEC-056 Optimization pattern, with recorded re-open conditions). Everything below is Option 3.

## 1. Problem Statement

Three activation-lifecycle defects/debts remain for backend-bearing packages (§0 B-1/B-2/B-3): invocations racing a promote see loud-but-misleading transient failures; Python-dependency upgrades at Apply silently split-brain the running warm sandbox with no restart notice anywhere; and a package whose sandbox workers persistently fail at the infrastructure level can be re-invoked forever, burning a full worker timeout per click with the ledger watching silently. Expected: an Apply and an invocation never interleave observably (the invocation waits briefly or the promote does); every install that *actually changed* a shared library while Curio runs states "restart Curio to pick up X" on its success surface; and repeated infrastructure failures quarantine the handler with an honest, self-expiring 503 that names the way out. Resident generated services stay out of scope with the descope and its re-open conditions on record.

## 2. Scope

Included:

- **B-1 consistency**: `invoke_handler`'s read-and-copy phase (manifest read → pin check → entry/tree read → workspace populate) acquires the same per-target lock promotes hold (`build_promotion._target_lock`, moved to a shared home both modules import); the WORKER runs outside the lock (locks bound file reads, never subprocess wall-clock). Promote keeps holding the lock through `record_entry_pin` (already does), which closes the pin-vs-files window once invocations honor the lock.
- **B-2 restart honesty**: `pip_runner.install_python_deps` callers at both install authorities KEEP the `InstallReport`; a non-empty `installed` list becomes `restartRecommended: {"libs": [...]}` on the promotion journal, the `package.draft.apply` apply payload, and the catalog-install response. Frontend: one shared copy helper (the `retentionCopy.ts` honesty pattern) renders "Restart Curio to pick up <libs> — running nodes keep the previously loaded versions until then" on the apply result turn and the install dialog's success state.
- **B-3 quarantine**: an in-process breaker in `backend_runtime` keyed `(user_key, dir_name, handler)`: **3 consecutive infrastructure failures** (`worker-timeout|worker-failed|no-reply|bad-reply` — a well-formed `handler-error` reply is the handler working as designed and never counts) → invocations refuse 503 `"quarantined after repeated worker failures — retries resume after {cooldown}s; a reinstall clears it immediately"` with a **120s cooldown**; any success, cooldown expiry, or entry-pin change (i.e. a promote/reinstall) resets it. Quarantine events append to the invocation ledger (`status: "quarantined"`). In-process state by design — a server restart clears it, which is the correct semantic anyway.
- **Docs/records**: DEC-064 (Option 3 + the resident-service descope with re-open conditions), ledger entry, `docs/EXTENDING.md` §8 one-paragraph update, dev/89 Follow-up B marked delivered-as-rescoped.

Out of scope (the descope, recorded not implied):

- **Resident generated services** — process supervision, ports/sockets, hot-load, long-lived request draining, readiness loops, restart backoff, load balancing. Re-open conditions: (a) a real package need expressible only as a resident process (not as on-demand handlers + `CURIO_PKG_DATA_DIR`), brought by a user or a recorded agent scenario; (b) the dev/91 §0.1 Option-2 dependency-overlay hardening landed first (a resident process amplifies the shared-interpreter blast radius); (c) an owner-approved memo of its own.
- Secret mediation (unchanged from dev/91), per-handler daily quotas (the ledger enables them when demanded), cross-major node migration, and any change to the legacy warm sandbox itself — B-2 makes its staleness *visible*, fixing it is a different program.

## 3. Recommended Implementation Approach

- **One lock home**: move `_target_lock` (and its guard dict) to a small `packages/target_locks.py` consumed by `build_promotion` and `backend_runtime` — no behavior change for promotes; `invoke_handler` wraps ONLY its filesystem phase (`package_dir` → `load_packageage_manifest` → pin verify → `_backend_tree` → `invoke_from_files`'s input assembly). To keep the worker outside the lock, `invoke_from_files` gains a `prepared_inputs` seam or — simpler — `invoke_handler` performs reads under the lock into memory (it already builds a `files` dict in memory) and releases before `invoke_from_files`; the only in-lock addition is the pin re-read. Lock hold time = reading ≤64 files/8 MiB — microseconds against a promote's seconds.
- **Report retention**: `promote` assigns `report = pip_runner.install_python_deps(py_deps)`; `journal["restartRecommended"] = {"libs": report.installed}` when non-empty (skipped-only installs recommend nothing — idempotent re-Applies stay quiet); `_apply_package_draft` copies it onto the apply payload; `_ensure_user_store_install` returns it up through the catalog install route. No detection heuristics, no module-list intersection — pip's own installed-list IS the truth, and "recommended" (not "required") is the honest strength: new-dep-only installs work without restart; version changes need one.
- **Breaker mechanics**: `dict[(str, str, str), _BreakerState(consecutive, quarantined_until, pin)]` under one module lock; checked after pin verification (so a reinstall's new pin resets before the check); incremented exactly where the ledger rows already classify outcomes — one classification, two consumers (the A15 one-spelling rule).
- Naming/conventions: statuses and copy follow the honest-failure house style; every refusal names the way out (A4).

## 4. Data and State Handling

Journal (persisted) carries `restartRecommended`; breaker state is in-process (documented; restart clears — semantically correct); ledger stays append-only (quarantine rows added, nothing rewritten); no new persisted stores. Apply payload additions are additive fields — absent means "nothing to say", never false.

## 5. UI and UX Requirements

- Apply result turn (agent chat) and the install dialog success state show the restart line only when `restartRecommended` is present, listing the libs verbatim; no modal, no blocking — a notice, because the *frontend* artifacts work immediately and only warm-interpreter execution lags.
- A quarantined Run surfaces the 503 text in the node's existing error surface (the dev/91 §5 no-silent-failure rule); the message carries the remaining cooldown.
- Accessibility: both are plain text in existing surfaces; no new interaction patterns.

## 6. Edge Cases

1. Invocation arrives mid-promote: waits on the lock, then reads the NEW pin+files consistently — no transient 404/409 (B-1's defect gone); a promote arriving mid-invocation-read waits microseconds.
2. Re-Apply of the same artifact (journal idempotency): pip skips everything → no restart notice (test-pinned).
3. pip upgrades a lib the sandbox never pre-imported: still recommended (pip installed it; other processes may hold it) — "recommended" wording absorbs the imprecision honestly.
4. Handler-error replies never count toward quarantine (a correctly-failing handler is not a crash loop).
5. Two handlers of one package: quarantine is per-handler — a broken handler never blocks its healthy sibling.
6. Reinstall during quarantine: new pin resets the breaker immediately (test-pinned).
7. Cooldown expiry: the next invocation runs (half-open); success resets, failure re-quarantines at once (counter kept).
8. Server restart: breaker state gone — acceptable and stated; the ledger still shows history.
9. Concurrent invocations of one target: both take the lock briefly in sequence; the semaphore still bounds worker parallelism.

## 7. Testing Strategy

- B-1: a promote and an invocation interleaved via threading events on the shared lock — the invocation never observes absent-dir/pin-mismatch (regression for the exact §0 window); promote behavior byte-identical when uncontended.
- B-2: promote with a fake pip runner returning installed vs skipped → journal/apply-payload/catalog-response carry (or omit) `restartRecommended`; idempotent re-Apply quiet; frontend jest for the copy helper + both surfaces.
- B-3: three infrastructure failures quarantine (503 with cooldown text), handler-errors don't count, per-handler isolation, reinstall resets, cooldown half-open behavior (injectable clock), ledger quarantine rows.
- Full suites + the dev/91 DOD unchanged.

## 8. Acceptance Criteria

1. No invocation observes a mid-promote package state; the interleaving test proves it.
2. An Apply that pip-installed anything states the restart line with the exact libs on both success surfaces; re-Applies and skipped-only installs stay silent.
3. Three consecutive infrastructure failures quarantine the handler with the specified 503; handler-level errors never trigger it; reinstall or cooldown restores service; all transitions appear in the ledger.
4. Resident services remain refused with the Follow-up B finding — now pointing at DEC-064's re-open conditions.
5. Everything existing (promotion journal semantics, dev/91 status matrix, DOD suites) passes unamended except where a test pinned the old transient behavior.

## 9. Recommended Commit Breakdown

- Commit 1 — `target_locks.py` + invoke read-phase locking + interleaving regression (B-1).
- Commit 2 — pip-report retention + `restartRecommended` through journal/apply/catalog + backend tests (B-2 backend).
- Commit 3 — frontend restart-notice copy helper + surfaces + quarantine breaker with ledger rows + tests (B-2 frontend, B-3).
- Commit 4 — DEC-064, ledger entry, `docs/EXTENDING.md` §8 update, dev/89 Follow-up B closure note, memo flip.

## 10. Engineering Quality Checklist

- [ ] One lock implementation, two consumers — no second serialization mechanism invented.
- [ ] The pip report is consumed, never re-derived; "recommended" wording matches its actual precision.
- [ ] Quarantine counts exactly the ledger's infrastructure statuses — one classification, two consumers.
- [ ] All new states are honest and name the way out; nothing blocks that used to work.
- [ ] The descope is a recorded decision with re-open conditions, not a silent omission.
