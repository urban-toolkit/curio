# dev/98 — The reference preview runner: local deployments graduate from declared-unpreviewed to actually previewed

**Status: IMPLEMENTED (2026-08-24) — commits 1–3 landed (`9b32a88f`, `37f1b7bc`, + docs); BL-P5-20260824-41; no new DEC. Correction to §0: reactflow DOES ship a UMD build (`dist/umd/index.js`) — it is baked into the wrapper when present.**
Prereqs: dev/89 §3.7 (the preview system and its operator-pinned runner contract), dev/90 A9 (`CURIO_BUILD_PREVIEW_POLICY=skip` — the honest gap this closes for local deployments), dev/96 (the card that renders preview verdicts), dev/97 complete. This implements the runner dev/89 already designed the socket for — **no new DEC**; the dev/90 "shipping a reference runner remains follow-up territory" note closes.

---

## 0. Evidence — the runner contract is fully pinned; the toolchain already exists (audit 2026-08-24)

- **The invocation contract is exact and test-pinned.** `run_preview` writes per-template CSP-locked documents plus `preview/plan.json` (`{contract: "1", templates: [{templateId, behaviorKey, document, states[5]}], report: "preview/report.json"}`) into the workspace's `work/` dir, then runs `[runner_path, plan_path]` through `run_worker` — scrubbed env (`PATH=/usr/bin:/bin`, `HOME`/`TMPDIR` remapped into the workspace, only `CURIO_BUILD_{INPUT,CACHE,OUTPUT}_DIR` provided), default `WorkerLimits` (120s wall / 60s CPU / 1 GiB AS Linux-only), killpg. The runner must write `$CURIO_BUILD_OUTPUT_DIR/preview/report.json` — `{contract, templates: {id: {registered: [keys], states: {state: {consoleErrors, width, height, screenshot}}}}}` — plus one screenshot file per state; `_validate_template_report` then enforces registration, zero console errors, dimensions within `[1, 4000]`, and screenshot presence/size. The tests' `_FAKE_RUNNER` encodes this schema line by line — the reference runner satisfies the SAME contract with a real browser.
- **The document deliberately ships without React.** `build_preview_document`'s docstring: *"The harness provides React/ReactDOM/ReactFlow… and drives the states."* The page carries the guards (`window.curio` stub capturing `registerBehavior` into `__curioPreviewBehaviors`, refusing network/storage), `window.__curioPreviewPlan` (behaviorKey + the five fixtures — both content spellings since A15), and the compiled bundle, which references `window.React`/`window.ReactDOM` per the compiler's host-global shims. Driving a state means: inject the host globals, mount the captured hook's `contentComponent` over the fixture, measure, screenshot.
- **The toolchain is already in the deployment.** Python `playwright` imports in the curio-feat env with chromium present in the default browser cache (`chromium-1223`); React/ReactDOM **18.3 UMD** builds sit in the frontend's `node_modules` (`react/umd/react.production.min.js`, `react-dom/umd/react-dom.production.min.js`) — the exact versioned host runtime Curio ships. `reactflow` publishes no UMD build: it will be provided only if resolvable, else absent — a behavior that imports it previews with an honest console failure (the same failure it would have live, since the compiler externalizes it to `window.ReactFlow`).
- **The scrubbed env is the packaging problem.** `PATH=/usr/bin:/bin` and a remapped `HOME` mean the runner cannot find the conda interpreter, the repo, playwright's browser cache, or the UMD assets on its own. The `CURIO_BUILD_ESBUILD=$(which esbuild)` precedent applies: pin by ABSOLUTE path via a generated wrapper that bakes every location at install time and fails loudly at generation if any is missing.
- **A real limits caveat, recorded not hidden:** `RLIMIT_AS` (1 GiB) applies on Linux only — headless Chromium can exceed 1 GiB of *address space* there. macOS (this deployment) ignores AS entirely. The reference runner targets local/dev deployments first; a Linux operator hitting the AS kill gets a truthful `preview runner failed` with the kill status, and raising the preview limits tier is its own future decision — this memo does not silently touch dev/89's worker limits.
- **The A15 tie-in is free coverage:** the runner's state driver passes `nodeState` as `{appearance: data.appearance}` — so previews exercise BOTH documented spellings (`data.appearance` and `nodeState.appearance`) exactly as the live runtime provides them. The blank-note bug class (A15) becomes buildable-time-visible once a runner exists.

### Evidence-backed decision summary

- *Engine — Playwright/Chromium (RECOMMENDED)*: already installed in the env (zero new deps for dev), real layout and real screenshots — the report's dimensions and PNGs are honest. *jsdom-style DOM emulation* is rejected structurally: no layout engine (fabricated `width`/`height`) and no screenshots — it cannot satisfy the existing validator without lying, and weakening the validator to fit a fake renderer inverts the point of previews.
- *Packaging — a generated pinned wrapper (RECOMMENDED)*: `python -m utk_curio.tools.install_preview_runner` writes one executable wrapper baking absolute paths (interpreter, repo, browser cache, UMD assets), the esbuild-pinning precedent. A bare `#!/usr/bin/env python3` script is rejected: the scrubbed `PATH` resolves the SYSTEM python, which has no playwright.
- *No new DEC*: dev/89 §3.7 decided the runner-shaped hole and DEC-057/A9 decided the skip posture; this ships the reference implementation. BL entry only.

## 1. Problem Statement

Every deployment without an operator-built browser harness — including this one — runs `CURIO_BUILD_PREVIEW_POLICY=skip`: custom behaviors reach review honestly labeled *NOT rendered before review*, and rendering bugs (the A15 blank-note class) surface live on the canvas instead of at build time. Curio designed the runner socket but ships nothing to plug into it. Expected: a first-party reference runner — Playwright driving headless Chromium — that satisfies the existing plan/report contract byte for byte (registration, five states, real dimensions, real screenshots, console errors), plus an installer CLI that generates the pinned wrapper and prints the one-line operator setup, so a local deployment's `POLICY=skip` becomes `CURIO_BUILD_PREVIEW_RUNNER=<wrapper>` and failed previews block Apply as dev/89 intended. No contract, validator, or limits change.

## 2. Scope

Included:

- **`utk_curio/tools/preview_runner.py`** — the reference runner. `--version` prints one line (`curio-preview-runner/1 playwright/<v> react/<v>`) for `runner_from_env`'s probe and provenance. For each plan template: load the document over `file://`; init-inject the host globals (React + ReactDOM UMD sources read from the baked paths; ReactFlow when available) and the state DRIVER; per state, render the captured behavior hook's `contentComponent` over the fixture inside a minimal component (`ReactDOM.flushSync` for deterministic paint; `nodeState = {appearance: data.appearance}` — the A15 spellings), measure the root's bounding box, screenshot the element to `$CURIO_BUILD_OUTPUT_DIR/preview/<tpl>/<state>.png`, and collect console/page errors merged with the document's own `window.__curioPreview.errors`; write the report in the exact `_FAKE_RUNNER` schema. Runner-level failures exit nonzero with the reason on stderr (the worker tail carries it).
- **`utk_curio/tools/install_preview_runner.py`** — the generator CLI: resolves interpreter, repo root, playwright browser cache, and the React/ReactDOM UMD files at generation time (each missing item is a loud, named failure — never a wrapper that breaks later in the scrubbed env); writes an executable wrapper (default `.curio/preview-runner`) exporting the baked paths and exec-ing the runner; prints the `export CURIO_BUILD_PREVIEW_RUNNER=…` line and the reminder to drop `CURIO_BUILD_PREVIEW_POLICY=skip`.
- **Tests** — the REAL lane (the A9 rule), environment-guarded with an honest skip reason when playwright/chromium are absent: generator output shape + missing-asset refusals; `runner_from_env` probes the generated wrapper; `run_preview` end-to-end over a hand-written bundle registering a real behavior (status `ok`, five states, real dimensions, PNG screenshots collected, `runnerVersion` in provenance); the failure twins (a behavior that throws in one state → that state's consoleErrors → `failed`; an unregistered key → `failed`); and the dev/96 card rendering a real runner's verdict payload.
- **Docs** — operator setup in `docs/EXTENDING.md` §8 (runner first, skip as the fallback it was meant to be); the dev/90 memo's operator-setup note updated; BL-P5-…-41; memo flip. **No new DEC.**

Out of scope: any change to the preview contract, validator, fixtures, or worker limits (the Linux AS caveat is recorded in §0 and the docs — a limits-tier change is its own decision); bundling browsers (playwright's own install flow owns that; the generator names the command when the cache is missing); screenshot persistence beyond the build (unchanged — digest-only in provenance, dev/96's recorded posture); CI wiring.

## 3. Recommended Implementation Approach

One runner file, stdlib + playwright only, speaking the contract the fake already pins (the schema test asserts fake and reference agree on shape); one generator writing one wrapper; zero changes inside `app/` — the entire feature lives behind the existing `CURIO_BUILD_PREVIEW_RUNNER` seam, which is the point: the reference runner is an OPERATOR CHOICE like any other harness, not a privileged code path. Driver JS is inline-injected (the document's CSP allows inline scripts by design); errors never fabricate dimensions — a state that fails to mount reports its console error and omits measurements, and the existing validator does the refusing.

## 4. Data and State Handling

Stateless per invocation: inputs are the plan + documents in `work/`, outputs land in the workspace output dir and die with the build (screenshots persist as digest+size in provenance, unchanged). The wrapper is generated state — regenerate after env moves (conda path, node_modules reinstall); the generator is idempotent and says what it baked.

## 5. UI and UX Requirements

No frontend changes: the dev/96 Preview section simply starts showing `ok` with per-template verdicts (and `failed` with real reasons) instead of the skip line, from data that already flows. The generator CLI's output is copy-pasteable setup.

## 6. Edge Cases

1. Playwright installed but no chromium in the cache: generation fails naming `playwright install chromium`; a wrapper generated earlier fails the version probe loudly (`runner_from_env` logs and returns None — the existing posture).
2. node_modules absent/reinstalled elsewhere: generation refuses naming the missing UMD file; a stale wrapper fails at run with the missing path on stderr.
3. A behavior importing `reactflow`: previews fail honestly with the console error naming `ReactFlow` — identical to its live failure mode.
4. Hook renders nothing (empty contentComponent): 0-dimension refusal by the EXISTING validator — the runner reports what it measured, never rounds up.
5. Slow first Chromium launch: within the 120s wall for local hardware; a timeout is a truthful `preview runner timeout` worker status.
6. Linux `RLIMIT_AS` kill (§0 caveat): truthful runner-failed status; documented; limits stay dev/89's.
7. Multiple templates in one draft: one browser, one page per document, sequential — determinism over speed.
8. The skip policy left set alongside a configured runner: the runner wins (`runner_from_env` resolves first — existing precedence), and the docs say to drop the stale skip.

## 7. Testing Strategy

Real-toolchain E2E as §2 (guarded, honest skip reason); generator unit matrix; schema-agreement test between fake and reference runner outputs over the same plan; full suites unchanged elsewhere.

## 8. Acceptance Criteria

1. On this deployment, one generator command + one env line replaces `POLICY=skip`, and a custom-look draft's card shows a real `Preview — ok` with five exercised states.
2. A behavior that breaks in any state fails the build with the state and error named; Apply stays blocked.
3. The runner satisfies the existing validator with measured dimensions and real screenshots — no validator, contract, fixture, or limits change anywhere.
4. Every generation-time gap (browser, UMD, interpreter) refuses loudly with the fix named; nothing generates a wrapper that lies later.

## 9. Recommended Commit Breakdown

- Commit 1 — `preview_runner.py` + `install_preview_runner.py` + generator unit tests + the direct real-browser E2E against `run_preview`.
- Commit 2 — pipeline-level integration (a drafted behavior previews ok / fails honestly through `run_build`), the fake↔reference schema-agreement test, provenance `runnerVersion` assertions.
- Commit 3 — docs: EXTENDING §8 operator setup, dev/90 note update, BL-41, memo flip.

## 10. Engineering Quality Checklist

- [ ] Zero changes under `app/` — the runner lives entirely behind the existing operator seam.
- [ ] The reference runner and the test fake are pinned to ONE schema by a shared assertion.
- [ ] Every baked path is resolved at generation with a named refusal; the wrapper never guesses.
- [ ] Dimensions and screenshots are measured, never fabricated; validator untouched.
- [ ] The Linux AS caveat and the reactflow gap are documented, not discovered.
