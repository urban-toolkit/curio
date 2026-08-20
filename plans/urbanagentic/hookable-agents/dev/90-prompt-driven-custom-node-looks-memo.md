# Dev/90 — Prompt-driven custom node looks: the Researcher agent owns the post-it recipe

Date: 2026-08-20  
Status: implemented (DEC-060; commits 1–4 landed `672e8a07`/`6fff01f1`/`088daa9e`/`bcabdc4f` + amendments A1 `652dab81`, A2 `b9953183`, A3 `dd24dda0`; commit 5 = the consolidated docs pass, incl. dev/89 commit 10)  
Supersedes in part: dev/89 commit 9 (`034965f5`) — the first-party Node Researcher fixture approach  
Evidence base: dev/89 (approved memo + commits `28b02972`…`034965f5`), `docs/EXTENDING.md` §5, `registry/types.ts` (`NodeBehaviorHook`), the published custom-look package `curio.streetvision@1`, `llm-prompts/package_build_instruction.txt`, the shipped build stack (`build_models` → `build_promotion`, `package.draft.apply`), `delegation.py` (depth-1, tool-less children), and `services._mint_content_review_from_delegate` (dev/73 — the one delegate-output→reviewed-proposal mint policy).

## 1. Problem Statement

Dev/89 commit 9 delivered the Node Researcher DOD the wrong way around. It shipped a **first-party canonical post-it component** — `utk_curio/backend/app/packages/fixtures/node-researcher-note.tsx`, its byte-identical frontend mirror `src/tests/fixtures/NodeResearcherNote.tsx` (RTL + parity test), and `node_researcher_reference.py`, a hardcoded "reference draft" tests and agents were meant to reuse verbatim.

That contradicts the premise of the dev/89 capability, and it also put the post-it's *definition* in the wrong place twice over:

- The Package Builder exists so that **agents author custom node looks**. With a repo-committed component, the "agent-built" package is a fixed asset the agent copies — the DOD proves the pipeline moves bytes, not that the capability authors looks. The generality (any look, on par with published packages like `curio.streetvision@1`) is untested.
- Even as a prompt, the post-it recipe does not belong to the Package Builder. The Package Builder is the **generic authoring specialist**; a note-taking use case baked into its instruction would make one caller's scenario part of the shared authoring contract. The scenario belongs to the agent that OWNS it.
- Two sources of truth exist for one component (backend fixture + frontend mirror held together by a parity test) — maintenance surface for code that should not be first-party at all.

The expected behavior:

- A **new roster agent, "Researcher" (`agent.researcher`)** — distinct from the existing `agent.node-researcher` ("Node Researcher", the dev/67-4 web-verification specialist, which is untouched — the naming split is called out everywhere it could confuse. The two agents even cooperate: Researcher may chain verification through Node Researcher) — owns the notes scenario. Its instruction carries the **post-it look recipe** (requirements, not code): square bounded surface, header title, safe markdown-lite body, quiet empty state, per-note color with derived AA ink, optional recolor affordance, no Run control or ports, `editor: none` + `hasCode: false`.
- The Researcher works **reuse-first**: when a notes template is already installed it requests note nodes directly (`node.create` with content + `appearance.backgroundColor`); only when no suitable template exists does it delegate the `package.create-or-extend` intent to the **Package Builder**, passing the recipe's requirements as the delegation inputs.
- The **Package Builder stays generic**: its instruction gains the custom-look **authoring contract** (the `NodeBehaviorHook` shape returning `contentComponent`, `window.curio.registerBehavior`, the React/ReactDOM/ReactFlow externals rule, React-elements-only safe rendering, the shared appearance contract, self-containment) — rules that hold for EVERY look. It never carries the post-it or any other caller's scenario.
- The **Dataflow Builder is not touched** — neither its prompt (`orchestration_instruction.txt`) nor its `delegatesTo`. Wiring Dataflow Builder → Researcher is an explicit follow-up, deliberately deferred so the orchestrator's tested surface stays byte-identical until the Researcher has proven itself as a directly-attachable agent.

Why it matters: correctness of the capability's claim (agent-authored, not agent-copied), the right ownership boundary (scenario prompts live with the scenario's agent; the authoring contract lives with the authoring agent), maintainability (no duplicated blessed component), and orchestration safety (the Dataflow Builder's prompt is regression-pinned; growing its delegation roster is a separate reviewed step).

## 2. Scope

Included:

- **New built-in `agent.researcher`** ("Researcher", the 21st roster entry): net-new instruction carrying the post-it recipe + reuse-first + delegation posture; capabilities, tools, `delegatesTo: agent.package-builder` (and `agent.node-researcher` for optional finding verification); roster/manifest/prompt tests (20 → 21).
- **`llm-prompts/package_build_instruction.txt`**: a new generic custom-look authoring-contract section (no scenario content).
- **The delegate-draft mint path** in `agents/services.py`: a successful package-authoring delegation whose child reply carries a build-request payload becomes a runtime-minted `package.draft.apply` proposal at the parent's attachment (the dev/73 `_mint_content_review_from_delegate` sequence, extended to package drafts — details in §3).
- Removal of the first-party fixture surface: `app/packages/fixtures/node-researcher-note.tsx`, `node_researcher_reference.py`, `src/tests/fixtures/NodeResearcherNote.tsx`, `src/tests/components/NodeResearcherNote.test.tsx`, and the parity test.
- Rewrite of `test_node_researcher_dod.py` → `test_custom_look_dod.py`: prompt-driven scenarios through the **Researcher** (post-it + one visually dissimilar look + one contract-violating refusal), authored sources test-local as simulated model output.
- A deviation note in dev/89's ledger trail (commit 9 superseded in part by dev/90; commits 1–8 untouched).

Explicitly retained (generic infrastructure, unaffected): the whole build stack (dev/89 commits 2–7), `package.draft.apply` mint/apply, the shared appearance utilities and `NodeColorControl`, the appearance round-trip and bridge, and the two commit-9 contract fixes (detected runtime-external imports are notes; the draft-class tail budget with its smuggling re-check) — each keeps its tests.

Out of scope / explicit follow-ups:

- **Follow-up D — Dataflow Builder → Researcher wiring**: adding `agent.researcher` to the Dataflow Builder's `delegatesTo` (and any plan-step vocabulary), as its own reviewed change once the Researcher is proven. Until then the Researcher is directly attachable (node/canvas) like any built-in.
- Any first-party "notes" package in the published catalog (a product decision that would ship through the normal `packages/` publish path, never `app/packages/fixtures/`).
- Runtime SDK growth, Follow-ups A/B/C (dev/89), and the dev/89 commit 10 docs (which land after this memo so the docs describe the corrected shape).

## 3. Recommended Implementation Approach

### The Researcher agent (roster entry)

- `agent.researcher`, name **"Researcher"**, category `node`, targets `node` + `canvas`, roles `("authoring",)`, `review-before-apply`.
- Capability: `research.notes.compose` — turn findings (the attachment's mission, a chat reply, web-search results) into canvas note nodes.
- Reads: `mission`, `targetContext`, `installedTemplates`.
- Tools: `dataflow.read` (ground reuse-first in what exists), `node.create` (reviewed note creation on an installed template, with `appearance`), and `package.draft.apply` **as the runtime-mint authorization only** (DEC-017: a declaration grantable for proposal purposes; the DRAFT CONTENT always comes from the Package Builder delegate — the Researcher's instruction forbids composing manifests/sources itself, and the tests pin that its tail never carries a self-authored draft).
- `delegatesTo: ("agent.package-builder", "agent.node-researcher")` — authoring, plus optional verification of findings before they become notes.
- Net-new instruction (`researcher_notes_instruction.txt`): the post-it recipe as REQUIREMENTS the delegated package must meet; reuse-first (`installedTemplates` before any authoring); one note per finding with palette-name or six-digit-hex colors; content is the finding text verbatim (never invented); honest-failure rules (a failed build/delegation is reported, never papered over).

### The delegation mechanic (why a mint path is needed)

Depth-1 children are structurally tool-less (`delegation.py`): the Package Builder running as a delegate cannot emit its own `package.draft.apply` toolRequest. Dev/73 already solved this shape for content: the parent's runtime turns a successful delegation's bounded reply into the reviewed proposal — one mint policy, several callers. Extend it: when the Researcher's `package.create-or-extend`-intent delegation returns a reply whose payload parses as a build request, the runtime calls the existing `_mint_package_draft_apply` path with those params at the Researcher's attachment. A reply that does not parse is a tool-result-style failure the parent recovers from in chat — never a silent drop, never an unreviewed mutation. The proposal, review card, apply, promotion, and registry-before-canvas flow are byte-identical to a directly-attached Package Builder run.

### The Package Builder stays generic

Its instruction gains one authoring-contract section (hook shape → `contentComponent`; `registerBehavior` keys must match the manifest; externals rule; React-elements-only rendering with https-only links; the shared appearance contract; self-containment; "the preview sandbox enforces all of this — a violating draft fails, loudly"). No recipe, no scenario. Different callers (Researcher today, Dataflow Builder after Follow-up D, users directly) bring their own look requirements through delegation inputs or chat.

### Tests own their scenarios

The DOD suite constructs drafts inline as simulated model output: `_postit_scenario()` (may resemble the deleted fixture — it is now test DATA), `_badge_scenario()` (visually dissimilar), `_violating_scenario()` (raw HTML / network access — refused by policy/preview). The recorded route-level scenario runs through the **Researcher**: user message with findings → Researcher's faked reply emits the delegation → the Package Builder child's faked reply returns the draft → runtime mints → review → apply → colored notes at `metadata.appearance`.

## 4. Data and State Handling

- No new persistent state. The delegated draft rides the child's bounded reply (`DELEGATE_RESULT_MAX_CHARS` — 24 000 chars; a post-it-scale draft fits; an oversized draft is a truncated-reply failure the parent reports honestly, and the bound is NOT raised in this memo).
- The runtime-minted proposal persists exactly like a direct mint (same `_store_proposal` path, same bounded provenance, same staging TTL).
- Deleting `node_researcher_reference.py` removes the only importer of `app/packages/fixtures/`; the directory goes away. Installed packages created from the old reference draft in dev sessions remain valid installed packages.

## 5. UI and UX Requirements

- No UI changes. Review card, preview payloads, appearance controls, and registry-before-canvas are unchanged from dev/89 commit 8.
- The Researcher appears in the roster/catalog as "Researcher" with a purpose line that disambiguates it from "Node Researcher" (verification) at a glance.
- User-visible behavior: attaching the Researcher and asking for post-it notes yields a reviewed package draft (first time) or reviewed note creations (template already installed) — never both silently, never an unreviewed canvas change.

## 6. Edge Cases

- **Package Builder not installed in the project**: the delegation resolves `not-installed` → the existing missing-specialist `project.install` proposal (REQ-ORCH-001); the Researcher reports the dependency instead of authoring itself.
- **Notes template already installed**: reuse-first — `node.create` proposals only; no delegation, no rebuild (recolor/content updates keep riding the existing reviewed paths).
- **Child reply is not a parseable draft** (prose, truncation, refusal): a recoverable failure surfaced in the Researcher's chat; nothing minted.
- **Child returns a draft violating the authoring contract**: the build service refuses (policy/preview) and the mint returns the findings as data — same as a direct Package Builder run.
- **Both "Researcher" and "Node Researcher" installed**: distinct ids, names, capabilities; delegation resolution is capability-keyed so no ambiguity arises; a roster test asserts the ids/capability sets stay disjoint.
- **Dataflow Builder asked for notes today**: it has no Researcher delegation yet (Follow-up D); it behaves exactly as before this memo — its prompt and manifest are byte-identical.

## 7. Testing Strategy

- **Roster tests** (`test_builtin.py`): count 20 → 21; the Researcher's manifest surface (capability, tools, delegatesTo order: package-builder before node-researcher); Dataflow Builder's manifest and `orchestration_instruction.txt` asserted UNCHANGED (byte-parity for the prompt file); instruction markers for the recipe ("post-it", the palette/hex rule, "reuse first", "never compose a manifest yourself").
- **Package Builder prompt tests**: authoring-contract markers (`registerBehavior`, `contentComponent`, "never raw HTML", externals, appearance contract) — and NO post-it marker.
- **Delegate-mint tests**: parseable child draft → minted proposal at the parent attachment; unparseable child reply → recoverable failure; oversized reply → honest truncation failure; injection resistance (a draft-shaped payload in ordinary chat text never mints — only the delegation-result path does).
- **Generic DOD suite** (`test_custom_look_dod.py`): the three scenarios of §3 end-to-end; recolor-never-rebuilds; two-colors-one-template independence; the route-level recorded Researcher scenario.
- **Removal regressions**: `git grep node_researcher_reference` and `packages/fixtures` empty; frontend suite passes without the mirror; commit-9 contract-fix tests untouched and green.

## 8. Acceptance Criteria

1. `agent.researcher` ("Researcher") exists as the 21st built-in with the recipe-bearing instruction, reuse-first posture, and `delegatesTo` = Package Builder (+ Node Researcher); it never authors manifests/sources itself.
2. The Dataflow Builder's prompt file and manifest are byte-identical to before this change; Follow-up D records the deferred wiring.
3. The Package Builder's instruction teaches the generic authoring contract and contains no scenario recipe.
4. A successful Researcher→Package Builder delegation becomes a runtime-minted, reviewed `package.draft.apply` proposal; unparseable/oversized/violating child output is a recoverable, visible failure.
5. No first-party look component exists: the fixtures directory, reference module, frontend mirror, and their tests are gone.
6. The DOD suite passes with two visually distinct test-local scenarios plus one refused violating scenario, driven through the Researcher.
7. Dev/89 commits 1–8 behavior and the commit-9 contract fixes remain byte-identical/in force.
8. Full agents + packages + frontend suites pass.

## 9. Recommended Commit Breakdown

- Commit 1: Researcher roster entry + net-new instruction + roster/prompt tests (incl. Dataflow Builder byte-parity pins).
- Commit 2: Package Builder instruction — generic authoring-contract section + prompt-marker tests.
- Commit 3: Delegate-draft mint path in `agents/services.py` (dev/73 sequence extended) + mint/injection/failure tests.
- Commit 4: Remove the fixture surface; rewrite the DOD suite as `test_custom_look_dod.py` (Researcher-driven scenarios); removal regressions.
- Commit 5 (docs; folds into dev/89 commit 10): `docs/EXTENDING.md` agent-authored-looks note, roster docs 21, dev/89 deviation record, Follow-up D, ledger.

## Amendment A1 (2026-08-20) — the Researcher gathers its own findings

The reference recording (`plans/urbanagentic/dataflow-builder/Screen Recording 20260629 at 31522 PM 1.mp4`) shows the full loop: the user asks a question ("what's the weather in Paris?"), the agent searches the internet, and the answer lands as post-it notes. The §3 Researcher as first approved could only compose findings it was HANDED — it had no way to gather them.

Change: the Researcher's manifest gains the existing policy-gated read tools `web.search` and `web.fetch` (dev/67-4 contracts — SSRF-guarded egress, ≤4 web calls per run, honest "not configured" error when the deployment has no `CURIO_SEARCH_URL` provider). Its instruction gains the gathering rule: answer questions by searching first, put each finding's source into the note body as an https link, and report an unconfigured or failed search plainly instead of inventing findings. Verification-grade checks may still chain to Node Researcher; everyday lookup is the Researcher's own.

Tests: the manifest-surface and instruction-marker tests extend accordingly, and the DOD suite gains the recorded video scenario — "what's the weather in Paris?" → `web.search` (mocked provider) → findings delegated with the post-it requirements → runtime-minted draft → Apply → a colored note carrying the weather text and its source link.

Unchanged: Dataflow Builder (still byte-pinned), the Package Builder's generic contract, the delegate-draft mint, and every never-rule (the Researcher still never authors packages itself).

## Amendment A2 (2026-08-20) — the operator's search provider is a trusted egress host

Field finding: with A1 landed, the live app still answers "the web search provider is not configured" — and configuring one locally is impossible, not just omitted. Public SearXNG instances disable the JSON API or rate-limit it, and the DEC-053 egress policy refuses loopback/private addresses after DNS resolution, so the standard local recipe (SearXNG in Docker on ``localhost``) is refused by the very policy that guards model-supplied URLs.

The SSRF rationale does not apply to the provider host: ``CURIO_SEARCH_URL`` is OPERATOR deployment configuration, not model output. Change, scoped narrowly: ``egress.fetch`` accepts an optional ``trusted_host`` (hostname, port) that exempts EXACTLY that host from the post-DNS address refusal — schemes, redirect re-checking (a redirect hop to any OTHER host gets the full policy), body caps, and the per-run budget all stay. Only ``web.search`` passes it, derived from the configured template; ``web.fetch`` (model-supplied URLs) keeps the full default-deny policy, and no model text can influence the trusted host.

Tests: egress-level (loopback refused by default, allowed only under the matching trusted host, cross-host redirect still refused — injectable transport/resolver, no network in CI) and tools-level (the trusted host is derived from ``CURIO_SEARCH_URL``; ``web.fetch`` never passes one).

## Amendment A3 (2026-08-20) — public search APIs, no servers, no new dependencies

A2 unblocked self-hosters; the remaining ask is a provider WITHOUT running anything. LangChain was considered and rejected: it is not a dependency today, and pulling an agent framework into the backend for one HTTP GET contradicts the lean posture (the existing egress module already speaks HTTP under policy).

Change, again narrow: ``web.search``'s response ADAPTER widens to the shapes the common public JSON search APIs return over a plain keyed GET — ``results`` (SearXNG), ``organic_results`` (SerpAPI, SearchApi.io), ``items`` (Google Programmable Search), and ``web.results`` (Brave-shaped proxies) — with the row aliases ``url|link|href`` and ``snippet|content|description``. The operator simply sets, e.g.::

    CURIO_SEARCH_URL="https://www.googleapis.com/customsearch/v1?key=<KEY>&cx=<CX>&q={q}"
    CURIO_SEARCH_URL="https://serpapi.com/search.json?q={q}&api_key=<KEY>"

Nothing else moves: same template mechanism, same egress policy (public hosts need no A2 exemption), same bounded rows, same honest not-configured error. Header-authenticated APIs (Brave direct, Serper, Tavily) stay unsupported — the template contract is GET-with-key-in-URL, stated honestly rather than half-supported.

## Amendment A4 (2026-08-20) — create-mode target ergonomics + diagnosable coordinate errors

Field finding (a live Package Builder run): the agent tried to create ``curio-notes`` three times and gave up, concluding "service unavailable — validation loop". Two compounding defects: (1) ``parse_build_request`` REQUIRED ``target`` even in create mode, where it is redundant (the cross-check forces it to equal ``manifest.id@major``); the agent reasonably omitted it and was refused with "got None". (2) When it then supplied ``curio-notes@1``, the true failure was the ID GRAMMAR — package ids are reverse-DNS, two-plus dot-separated segments (``curio.notes``) — but the error re-stated the format template the value already appeared to satisfy. Undiagnosable error → wrong self-diagnosis → a capability reported broken that was working as (badly) specified. This is exactly the "weak models need self-correcting contracts" rule: the refusal text must carry enough to fix the request.

Change: ``target`` becomes OPTIONAL in both modes — derived from ``manifest.id`` + ``compatibility.major``; when provided it must still match (unchanged cross-check). Coordinate failures now say the grammar ("reverse-DNS: two or more dot-separated lowercase segments … single-segment ids like 'curio-notes' are invalid") with a valid example, at both the derived and provided paths. The ``package.draft.apply`` ToolContract description states target-optional + the id grammar. Regression tests reproduce the transcript: omitted target mints; single-segment id refuses with the grammar in the text.

## Amendment A5 (2026-08-20) — dependency-minimal authoring is the default

Companion to A4, same live run: the agent's curio-notes plan declared ``react-markdown``, which requires an operator-approved JS registry — unconfigured in most deployments, so the draft would block. The right default for small presentation behaviors is ZERO dependencies: a ~30-line markdown-lite renderer beats importing a markdown library through a supply chain. Changes: the Package Builder's authoring contract gains the prefer-zero-dependencies rule (declare a JS dependency only when the look genuinely cannot be self-contained, and expect the registry requirement); the ``js-registry-missing`` finding now carries the fix ("author the behavior self-contained instead"); and a route regression replays the corrected curio-notes request — ``curio.notes``, no target, no dependencies, self-contained markdown-lite — through mint → build → preview → Apply.

## Amendment A6 (2026-08-20) — authoring delegations get the plan-class inputs budget

Field finding (live screenshot, the Paris weather run): the Researcher's ``node.kind.author`` delegateRequest — carrying the full post-it look specification plus the findings, exactly as its instruction requires — blew the classic 3KB delegate-inputs cap (and the 4KB whole-tail cap). Per DEC-043 the invalid block failed OPEN as visible JSON text: nothing was delegated, no proposal minted, and the model then falsely claimed "I have placed this finding on your canvas as a note". The tests never caught it because their fixture inputs were tiny.

Change, the same shape as the dev/89 draft-budget fix: ``PACKAGE_AUTHORING_CAPABILITIES`` becomes canonical in ``content.py`` (the tail contract must size these; ``services`` aliases it — one truth), ``_parse_delegate_request`` gives authoring capabilities the plan-class budget while every ordinary delegation keeps the classic cap, and the oversized-tail gate + payload-key re-check admit authoring delegateRequests exactly (a capability string smuggled inside another payload stays refused). Regressions: content-level budget/smuggle tests, plus a route replay of the screenshot — a >4KB look-spec delegation that parses, delegates, mints, and leaks no raw JSON into visible parts.

Standing lesson for the tail contract: any part type whose payload grows with REAL content (plans, drafts, authoring inputs) needs an explicit budget decision with a live-sized regression — the classic 4KB default silently kills it in production while toy fixtures pass.

## Amendment A7 (2026-08-20) — the delegate's reply shape: teach it AND accept it

Field finding (live screenshots, after A6): the delegation now executes, but the mint reported "no parseable package draft" twice. The mismatch was self-inflicted: the Package Builder's instruction teaches it to surface drafts as a ``curio.v1`` ``package.draft.apply`` toolRequest — but a depth-1 delegate is structurally tool-less, and ``_extract_draft_params`` accepted only bare/``json``-fenced draft objects. The child's most instruction-faithful reply was exactly the shape the extractor refused.

Change, both sides: (1) the extractor also accepts ``curio.v1`` fences and UNWRAPS a ``package.draft.apply`` toolRequest's ``params`` into the draft (never executed as a tool; a different tool's request never unwraps); (2) the instruction gains the delegate posture — when the task begins with "[delegated task from …]" reply with EXACTLY ONE JSON build request in a ``json`` fence, nothing after it. Regressions: extractor-shape units + a route replay of the screenshots (child answers in the toolRequest shape → the draft mints).

Standing lesson, paired with A6's: when a prompt teaches an output contract, every RUNTIME PATH that consumes that agent's output must accept the taught shape — a contract taught in one mode and rejected in another is a bug factory.

## Amendment A8 (2026-08-20) — authoring delegates receive the build-request contract as an input

Field finding (live screenshots, after A7): the child now answers in JSON — but with an INVENTED schema (``"package"``/``"behaviors"``/``"behaviorKey"``, a single-segment id), twice, even after the Researcher "refined the request". Root cause: nobody in the delegation chain has ever SEEN the build-request schema. It lives in the ``package.draft.apply`` ToolContract description, which rides the grants paragraph — and DEC-046 children are tool-less, so the Package Builder-as-delegate never receives it; the Researcher cannot teach a schema it does not carry either.

Change — the dev/67-6 enrichment pattern: ``_enriched_delegate_inputs`` appends a server-owned ``buildRequestContract`` (the full shape, the reverse-DNS id rule, the registerBehavior/contentComponent rules, prefer-zero-deps, and an explicit "there is no 'package', 'behaviors', or 'behaviorKey' key" countering the observed invention) to every authoring delegation's inputs; model-supplied keys are never overwritten. The instruction's delegate paragraph points at the supplied contract. Tests: enrichment units (authoring capabilities gain it, others untouched, never overwritten) and a route assertion that the CHILD's framed user message carries the schema.

Standing lesson, completing the A6/A7 set: a delegate can only honor contracts that are IN ITS CONTEXT — schemas that live in tool grants must be re-supplied server-side when the consumer is a tool-less child.

## Amendment A9 (2026-08-20) — real toolchain shakeout + the declared preview skip

Field finding (live run, after A8): the whole chain now works — the draft minted and the build ran — and failed honestly at the deployment gate: no ``CURIO_BUILD_ESBUILD``. Two consequences handled:

1. **Real-binary shakeout.** Running the compiler against a real esbuild (0.28.2, installed into the project conda env) caught a flag bug the fake toolchain could never see: ``--sourcemap=false`` is not a valid esbuild value — the flag is simply OMITTED (absence = no sourcemap, the fixed policy). With the fix, a real TSX behavior compiles to a deterministic bundle with ``window.React`` aliasing, byte-identical across workspaces.
2. **The declared preview skip.** With a compiler configured, the next gate is the preview runner — heavy browser infrastructure no local deployment has, making the feature unusable locally by design. New operator declaration (the DEC-057 posture): ``CURIO_BUILD_PREVIEW_POLICY=skip`` lets a runner-less deployment pass a custom behavior to review UNPREVIEWED, with the skip recorded in the draft's provenance ("SKIPPED BY OPERATOR POLICY … NOT rendered before review"). The default stays fail-closed; unknown values read as ``required``; a configured runner always wins over the policy; and the fail-closed refusal now names the declaration option.

Operator setup for local dev is therefore: ``npm i -g esbuild`` (in the project env) + ``CURIO_BUILD_ESBUILD=$(which esbuild)`` + ``CURIO_BUILD_PREVIEW_POLICY=skip`` (until a pinned runner exists — shipping a reference runner remains follow-up territory alongside the rich review card).

## Amendment A10 (2026-08-20) — the decorated request: honor the request the model actually made

Field finding (live session 12:55, diagnosed from the persisted transcript rather than the screenshot): the reply carried TWO ``curio.v1`` blocks — the ``delegateRequest``, then a terminal ``suggestedPrompts`` block (the model obediently followed the tail instruction's "end with suggested prompts"). The terminal-only tail rule made the suggestion block win: parts = ``[suggestedPrompts]``, ``delegations: null``, and the request fence rendered as inert chat text — indistinguishable, from the screenshot alone, from the long-fixed A6 symptom. The blocking AND streaming routes both handled the single-block shape correctly; only the decorated shape failed.

Change: ``extract_content`` gains the decorated-request rule — when the terminal block is VALID but carries no request, exactly ONE earlier ``curio.v1`` block that parses to a single tool/delegate request wins, stripped from the visible text; the decoration parts drop (the dev/41 request-exclusive rule already says a request turn is a request turn). The conservative boundary is explicit: zero or multiple earlier request blocks, or no valid terminal block at all, keep the pre-A10 behavior byte-identically. Regressions: content-level shape tests + a route replay of the live two-block reply (delegation executes, proposal mints, no fence text leaks).

Diagnosis lesson (the debugging, not the fix): the identical user-visible symptom — "raw delegateRequest in chat" — had TWO different root causes (A6 size cap, A10 terminal demotion). The persisted session turn (text + parts + execution.toolCalls/delegations) disambiguated in minutes what screenshots could not; read the transcript file before re-touching code that already has a green regression.

## 10. Engineering Quality Checklist

- [ ] The authoring contract lives in ONE prompt section (Package Builder); the Researcher's recipe states requirements and defers the contract to the specialist.
- [ ] "Researcher" vs "Node Researcher" is disambiguated in purpose lines, docs, and a roster test.
- [ ] The Dataflow Builder prompt/manifest byte-parity is test-pinned, not just promised.
- [ ] The delegate-mint path reuses `_mint_package_draft_apply` (one mint policy — dev/73's rule) rather than a second build/validation path.
- [ ] No test asserts on generated-code internals beyond the contract; looks may vary by model.
- [ ] Scenario sources are labeled as simulated model output inside tests; no dangling fixture imports remain.
- [ ] dev/89's trail records commit 9 as superseded-in-part by dev/90, never silently rewritten.
