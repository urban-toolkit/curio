# Dev/90 — Prompt-driven custom node looks: the Researcher agent owns the post-it recipe

Date: 2026-08-20  
Status: approved 2026-08-20 — implementation in progress per the §9 commit breakdown  
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

## 10. Engineering Quality Checklist

- [ ] The authoring contract lives in ONE prompt section (Package Builder); the Researcher's recipe states requirements and defers the contract to the specialist.
- [ ] "Researcher" vs "Node Researcher" is disambiguated in purpose lines, docs, and a roster test.
- [ ] The Dataflow Builder prompt/manifest byte-parity is test-pinned, not just promised.
- [ ] The delegate-mint path reuses `_mint_package_draft_apply` (one mint policy — dev/73's rule) rather than a second build/validation path.
- [ ] No test asserts on generated-code internals beyond the contract; looks may vary by model.
- [ ] Scenario sources are labeled as simulated model output inside tests; no dangling fixture imports remain.
- [ ] dev/89's trail records commit 9 as superseded-in-part by dev/90, never silently rewritten.
