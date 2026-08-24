# dev/97 — Backend dependency overlays (dev/91 §0.1 Option 2): handler deps leave the host interpreter; the shipped seam becomes the boundary

**Status: APPROVED (owner, 2026-08-24) — Option A probe posture adopted. Implementation in progress.**
Prereqs: dev/91 (the sandbox + the Option-3 parameterized seam: `overlay_dir → PYTHONPATH`, proven live by test), dev/92 (restart honesty — whose blast-radius evidence this memo finally shrinks), dev/96 complete. This memo is the recorded §0.1 Option-2 hardening — the prerequisite DEC-064 set for ever re-opening resident services.

---

## 0. Evidence — what the seam already gives, and what the audit adds (2026-08-24)

- **The seam is shipped and proven.** `invoke_from_files` threads `overlay_dir` into the worker's `PYTHONPATH` (dev/91 commit 2; a live test resolves an overlay module in-worker), and `CURIO_BACKEND_SANDBOX_PYTHON` pins the interpreter. Option 2 was designed to be "new parameter values, never a redesign" — this memo supplies the values: a real overlay store, built at Apply, resolved automatically at invocation.
- **The blast radius this kills is measured** (dev/91 §0.1): every pip path lands in ONE shared interpreter; a backend draft declaring `pandas>=2.3` upgrades pandas for every package, every node, and Curio itself, and dev/92's `restartRecommended` can only *report* the split-brain, not prevent it. Backend workers are the one consumer where isolation is structurally cheap: freshly spawned per invocation, no warm-import cache to break.
- **`pip_runner` has no `--target` support** — the new primitive is one function beside the existing two, same timeout/error posture.
- **A live defect the audit surfaced: the probe runs dep-blind.** The `probing` phase (dev/91 commit 3) executes the draft entry in a real worker at BUILD time — but python deps install at APPLY (dev/89 §3.4's deliberate posture). An entry that imports a declared dep at module level therefore fails its probe with `ModuleNotFoundError` **before the dep could ever exist**, and the refusal blames the import rather than naming the timing. Nothing in the prompt contract warns authors. (Tests never caught it because every test handler imports stdlib only.)
- **Uninstall does not keep dev/91's own promise.** §6.7's data-dir cap message says "the handler (or an uninstall) must clear it" — but `uninstall_packageage` removes only the package dir: data dirs and pin entries survive uninstall today (pins self-heal on reinstall via `record_entry_pin`; data dirs simply leak). Overlay cleanup must not repeat this, and the fix should sweep all three together.
- **The shadowing sharp edge is real but bounded**: `pip --target` installs the declared deps *and their transitive closure* into the overlay, so the prepended `PYTHONPATH` shadows consistently for everything declared; the residual risks are a stale overlay after a partial write (fixed by wipe-before-build) and an overlay that breaks module-level imports (caught by a post-Apply probe against the installed entry + real overlay, with the promotion's existing rollback as compensation).
- **pip-at-build would be a posture change, not a convenience**: dev/89 §3.4 deliberately keeps python review-only at build (`review_python_dependencies` installs nothing); building a hermetic probe overlay at build time would put PyPI network into the build phase and break registry-less/offline deployments that build fine today. The JS precedent (registry fetch at build) is operator-gated by `CURIO_JS_REGISTRY_URL` — python has no equivalent gate.

### Evidence-backed decision summary

- *Probe-vs-deps — Option A (RECOMMENDED): the lazy-import contract + a fix-naming refusal.* Handlers import declared dependencies **inside `handle()`**, not at module level; the probe (load + resolution) then stays meaningful without deps, and when an author gets it wrong the probe failure text names the exact fix ("declared dependency 'X' is not importable at build time — import it inside your handler function; it installs at Apply into the package's overlay"), which the dev/93 D5 correction rounds feed straight back to the delegate that wrote it. Zero posture change.
- *Probe-vs-deps — Option B: hermetic pip into the build workspace, probe with real deps.* Rejected for this slice: network-at-build posture change, offline-deployment breakage, double pip cost — and Option A plus the post-Apply probe covers the honesty gap. Re-open alongside any future operator-gated python registry.
- *Overlay routing:* backend-bearing packages' python deps go to the **overlay only**, EXCEPT when the same manifest also carries a python-engine `hasCode` template (its node code runs in the warm sandbox, which cannot see overlays) — then host **and** overlay, both stated. Derived from the manifest, no new schema key (one declaration, `dependencies.python`, stays the one home).

## 1. Problem Statement

Backend handler dependencies still land in the shared host interpreter, so the dev/91 §0.1 blast radius applies to exactly the packages the sandbox was built to contain — and dev/92 can only report the fallout. Meanwhile the probing phase refuses any draft whose entry imports a declared dep at module level, with a message that blames the wrong thing, and uninstall leaks backend residue (data dirs, pins) contrary to dev/91's stated behavior. Expected: at Apply, a backend-bearing package's python deps install into a per-package overlay (`pip --target`, wiped and rebuilt each promote) that workers receive on `PYTHONPATH` automatically; the host interpreter is touched only when the manifest also has warm-sandbox python templates; a post-Apply probe with the real overlay gates activation with rollback compensation; the probe's dep-import refusal names the lazy-import fix and the prompt contract teaches it; and uninstall sweeps overlay + data dir + pin in one honest pass.

## 2. Scope

Included:

- **`pip_runner.install_python_deps_to_target(deps, target_dir, on_line=None)`** — `pip install --target <dir> --no-input <specs>`; same timeout/error/streaming posture as its siblings; no skip logic (the caller wipes first — a fresh target has nothing to skip); returns the installed spec list.
- **Overlay store**: `.curio/users/<key>/package-backend-overlays/<dir_name>/` (sibling of the data/ledger homes). Wipe-before-build at every promote (deterministic; a crashed write cannot go stale). Post-install size check against `CURIO_BACKEND_OVERLAY_MAX_MB` (operator-tunable, default 512): over-cap fails the promote honestly ("torch-scale dependencies do not fit a handler overlay") with rollback.
- **Promotion + catalog wiring**: for a backend-bearing manifest, python deps → overlay; host pip runs additionally ONLY when a python-engine `hasCode` template coexists (the derived rule above). `restartRecommended` (dev/92) triggers on the HOST portion only — overlay changes never split-brain anything (workers are fresh); the journal records `overlay: {libs, bytes}`.
- **Post-Apply probe**: after the overlay builds, ONE probe invocation against the INSTALLED entry with the real overlay (the same `invoke_from_files` engine); a failure rolls back through the existing promotion compensation with the probe's error verbatim — the shadowing sharp edge caught at Apply, never at the user's first Run.
- **Invocation**: `invoke_handler` auto-resolves the package's overlay dir when present (the explicit `overlay_dir` parameter stays as the test seam and always wins).
- **Probe refusal honesty + contract**: the build-time probe failure for a `ModuleNotFoundError` on a DECLARED dep gains the fix-naming message; the Package Builder prompt's backend section gains the lazy-import rule; `_BUILD_REQUEST_CONTRACT` mirrors it (A8 — the delegate sees the schema it must satisfy).
- **Residue sweep**: `backend_runtime.remove_backend_residue(user_key, dir_name)` — overlay + data dir + pin entry — called from package uninstall/prune; the invocation LEDGER deliberately survives (append-only audit history is retention's to expire, never uninstall's).
- **Tests**: a REAL `pip --target` E2E with a hand-built minimal wheel imported from the overlay inside a live worker (the A9 real-toolchain rule); promote routing matrix (overlay-only / both / non-backend untouched) with fake pip; over-cap refusal; post-Apply probe failure → rollback; probe fix-naming refusal through the agent lane; residue sweep incl. the ledger-survives pin; auto-resolution.
- **Docs**: DEC-066; BL-40; `docs/EXTENDING.md` §8 dependency paragraph; dev/91 §0.1 Option-2 note annotated delivered; memo flip.

Out of scope: per-package venvs (unchanged rejection), pip at build (Option B, recorded), any change for non-backend packages or the warm sandbox, a python package registry, overlay sharing/deduplication across packages (correct-first; size is capped and measured in the journal for a future dedup decision).

## 3. Recommended Implementation Approach

One primitive in `pip_runner` (never a second pip invocation path elsewhere); one overlay-home helper trio in `backend_runtime` beside the data/ledger homes; routing decided in ONE place (a small `_dep_destinations(manifest)` in promotion returning `overlay/host/both` with the derived rule and its reason string, reused by the catalog path); the post-Apply probe reuses `invoke_from_files` + `bc.probe_payload()` verbatim (one probe, three callers now: build, Apply, and the harness's own health semantics). Refusal texts follow A4 (name the fix); the lazy-import rule lands in both prompt and server contract with marker tests (the A15 two-places rule).

## 4. Data and State Handling

The overlay is derived state — rebuilt from the manifest at every promote, swept at uninstall, never edited in place. The journal gains `overlay` (libs, bytes) as immutable provenance; `restartRecommended` semantics narrow to host-portion-only (a behavior change dev/92's tests must be updated to pin deliberately). Invocation reads the overlay path only inside the existing target-lock read phase (B-1's consistency covers overlay swaps for free, since promote holds the same lock while wiping/rebuilding).

## 5. UI and UX Requirements

No new components. The dev/96 card's Dependencies section gains one line when the draft is backend-bearing: where the deps will live ("installs into the package's isolated overlay — the shared interpreter is not touched" / "…plus the shared interpreter, for its python node templates"), composed server-side into the existing bounded payload. The dev/92 restart notice simply fires less often — correctly.

## 6. Edge Cases

1. pip --target fails mid-promote: overlay wiped, promotion rolls back, honest 502 (the existing compensation).
2. Over-cap overlay: promote fails naming the cap and the env knob; nothing half-installs.
3. Reinstall/upgrade: wipe-before-build → no stale members; the B-1 lock means no invocation reads a half-built overlay.
4. Mixed manifest (backend + python node template): both destinations, both stated, restart notice from the host half only.
5. Handler imports an UNDECLARED dep lazily: runtime `handler-error` naming the module (dev/91 edge 9 unchanged — declaration stays the contract).
6. Module-level import of a DECLARED dep: build probe refuses naming the lazy-import fix; correction rounds carry it back.
7. Overlay shadows a module-level import chain at Apply (the mixed-tree edge): the post-Apply probe fails → rollback, error verbatim.
8. Uninstall: overlay + data dir + pin swept; ledger survives; a quarantine breaker entry dies with its pin.
9. Legacy installed backend packages (deps in host from pre-dev/97): keep working (host site-packages remains reachable behind the overlay on `PYTHONPATH`); the next promote migrates them to the overlay.

## 7. Testing Strategy

Real-toolchain E2E (hand-built wheel → overlay → imported in a live worker through the auto-resolved path); routing matrix; cap refusal; post-Apply probe rollback; fix-naming refusal through the delegate lane with correction rounds; residue sweep; dev/92 restart-notice narrowing re-pinned; full suites.

## 8. Acceptance Criteria

1. A backend-only package's declared deps never touch host site-packages; its handlers import them from the overlay.
2. The mixed-manifest rule routes to both, stated on the journal and the card.
3. A module-level dep import is refused at build with the lazy-import fix named; the corrected draft passes.
4. A broken overlay cannot survive Apply (post-Apply probe + rollback).
5. Uninstall leaves no overlay, data dir, or pin behind; the ledger remains.
6. dev/92's restart notice fires only for host-portion installs.

## 9. Recommended Commit Breakdown

- Commit 1 — `install_python_deps_to_target` + overlay homes + invocation auto-resolution + the real-wheel E2E.
- Commit 2 — promotion/catalog routing + post-Apply probe + journal/card lines + restart-notice narrowing + residue sweep; tests.
- Commit 3 — probe fix-naming refusal + lazy-import rule in prompt/contract + delegate-lane DOD; tests.
- Commit 4 — docs: DEC-066, BL-40, EXTENDING §8, dev/91 annotation, memo flip.

## 10. Engineering Quality Checklist

- [ ] One pip primitive, one routing decision point, one probe engine — nothing duplicated.
- [ ] Wipe-before-build everywhere an overlay is written; no in-place edits.
- [ ] Every refusal names the fix; the lazy-import rule lives in prompt AND contract with marker tests.
- [ ] dev/92's narrowed restart semantics are re-pinned deliberately, never silently.
- [ ] The ledger's survival of uninstall is asserted, not assumed.
