# dev/105 — The Researcher's reuse ladder loses its footing: a bare package id refuses with a hint it cannot act on, two refusals spend the round budget, and the answer falls back to chat

**Status: IMPLEMENTED (2026-08-25) — commits `51b7b97a` (1, D1), `e122ad3d` (2, D2), `f1d274af` (3, D3/S1/S3), + commit 4 (field-replay lane, docs); DEC-067 minted; BL-P5-20260825-44. Final verification: `test_agents` + `test_packages` 1457 passed / 4 skipped. The field replay (`test_reuse_ladder_field.py`) is the gate: variant A (the live store) ends in one `package.install` proposal pinned to `curio.notes@1` with zero nodes added; variant B (no note template anywhere) reaches the AUTHOR delegation at round 2 — the flow that sat at round 4 of 3 before commit 2.**

Commit 4 notes: **(a)** the roster call site's `except Exception: landscape = None` swallowed the cause silently (the dev/93 D2 shape) — it now logs a warning, behavior unchanged; found because the delegate test harness writes no built-in store package, so the roster vanished without a trace. **(b)** Both fake providers record the ONE mutable message list by reference, so `calls[i][-1]` is always the run's final message — this memo's commit 1–3 assertions on it held by coincidence and are rewritten to read the message history in order (`_results` helpers); dev/93's own `calls[i][-1]` assertions are left as written and flagged in the BL entry. **(c)** §9's commit 4 also carries `docs/AGENTS.md` (a DEC-067 paragraph beside the dev/93/94 vocabulary rules), the dev/03 DEC row, the `00` index row, `3.1`/README status lines.

**S1 re-scoped on evidence (commit 3).** §1 S1 assumed the compute post-it was the *only* Available entry. Re-reading the live landscape: `_available_templates_block` already filters non-authorable rows, so the post-it was never offered — the Researcher's Available list held the **twelve built-in code templates** and no note template, and the model reached for the canvas node's type anyway. So the roster fix is not "mark non-authorable rows" (there were none shown) but "tell a note-composing run that nothing listed renders a note": rows gain an additive `presentation` flag (`behavior` + `editor: none`), and `_available_templates_block(notes_agent=True)` appends `_NO_NOTE_TEMPLATE_LINE` when no shown row is one. Other agents' rosters are byte-unchanged; §8 AC-7 is satisfied in this form. The prompt's REUSE rung additionally states that canvas/dataflow.read node types are not template choices unless listed.

Implementation note (commit 2): the marker is applied at the two mints the field run hit rather than at every `return "refused"` in the module — other mints (plan write, template create, dataset install) keep spending rounds unchanged; widening is a one-line `_refuse_params(...)` per site when a lane shows the same failure, and the broken-store/catalog/spec refusals must stay unmarked (edge 6).

Date: 2026-08-25
Branch / tree: `feat/agentscatalog` @ `16b994b7`. Line numbers pinned to that commit.
Origin: live failure, Researcher session `c59aae2f…` / execution `b18c3461…` in project `46dbf1d8…` (screenshot `Desktop/Screenshot 2026-08-25 at 11.22.12 AM.png`). Model `gemma4` via `openai_compatible`.
Family: dev/90 (Researcher, DEC-060) → dev/93 D4/D5 (the reuse ladder, DEC-062) → dev/94 (executable-instruction rule, DEC-063). This memo is the ladder's first post-implementation field failure; dev/93 is NOT reopened — its mechanisms behave exactly as built. What failed is the seams *between* the rungs.
Prereqs: dev/93 (roster halves, `package.install` grant on the Researcher), dev/84 (`_mint_package_install`), dev/73 (`MAX_TOOL_ROUNDS = 3`, round-cap cutoff card), dev/41 (one request per reply).

---

## 1. Problem Statement

**What the user saw.** Asked "whats the weather in Paris?", the Researcher searched, wrote a correct sourced answer, then placed an **empty** `Post-it Note` compute box on the canvas, told the user it "cannot be used for creating content notes", said `curio.notes` "is not currently available in the catalog", and delivered the findings in chat only. No question note, no answer note, no install proposal, no Package Builder delegation. Run status: `ok`.

**What actually happened** (execution record `toolCalls`, in order): `web.search` ok (4.5 s) → `node.create` **refused** (3 ms) → `package.install` **refused** (7 ms) → final prose. Three tool rounds, `MAX_TOOL_ROUNDS = 3` (`agents/services.py:5096`), budget exhausted.

**Live state of the project at the time** (reproduced with `packages_services.template_landscape('guest', '46dbf1d8…')`):

| roster half | template | `authorable` | dirName |
|---|---|---|---|
| Available (lockfile `[]`, backfilled) | `curio.postits/post-it-note` | **False** — Python *computation* template: `engine: python`, one JSON output port, no `behavior` | — |
| Installed but NOT enlisted | `curio.notes/note-surface` | **True** — `editor: none` + `behavior: note-behavior` (the dev/89 post-it profile) | `curio.notes@1` |

So dev/93's roster did its job: the correct note template was offered on rung 2, with its dirName, and the Researcher held the `package.install` grant. The ladder still failed, at three separate seams:

**D1 — Rung 2 refuses a fixable spelling with a hint the agent cannot execute.** The model sent `dirName: "curio.notes"` (its own prose names exactly that). `_mint_package_install` (`services.py:2290-2318`) does an exact-key lookup in `agent_catalog_overview` and refuses: *"package 'curio.notes' is not in the Nodes Catalog — propose only dirNames from packages.catalog results"*. The Researcher **has no `packages.catalog` tool** (`agents/builtin.py:349-351`: `dataflow.read, web.search, web.fetch, node.create, package.install, package.draft.apply`). Verified: `curio.notes@1` passes every check and mints; `curio.notes` and `curio.notes/note-surface` (the template id the roster line *leads* with) both refuse. This is the DEC-063 defect shape again — an instruction that is not executable on the path its agent runs on — now in a refusal message instead of a prompt.

**D2 — Refused rounds consume the same budget as productive ones, so rung 3 is unreachable after two misses.** The loop (`services.py:6805-6812`) increments `rounds_used` for every request, refused or not. Search (1) + a refused `node.create` (2) + a refused `package.install` (3) = cap. The AUTHOR delegation the prompt mandates as the last resort (`researcher_notes_instruction.txt:11`) could not have been emitted in this run no matter what the model decided. dev/73 set 3 for a *three-productive-step* flow; a validation refusal is a 3–7 ms round-trip that produced nothing.

**D3 — The give-up is taught, and the state claim is false.** `researcher_notes_instruction.txt:31` — *"If a delegation, build, or proposal fails, report the failure plainly and stop"* — does not distinguish a build failure (stop) from a **parameter refusal** (correct the parameter, or take the next rung). The model followed it, and then asserted "not currently available in the catalog", which the refusal never said and which is false (`curio.notes@1` is in the store and in `agent_catalog_overview`). A17 in dev/90 forbids claiming a package exists before Apply; nothing forbids claiming one *doesn't* exist.

**Secondary (in scope, small):**
- **S1** — `_mint_node_create` correctly refused `curio.postits/post-it-note@1` ("does not hold authored content"), but the model had already picked it because it was the *only* Available entry and the REUSE rung says "look at Available for a notes template". The roster does not mark non-authorable templates, so a weak model tries them first and burns a round.
- **S2** — The empty Post-it box on the canvas predates this run (it is in `spec.trill.json`; the refused `node.create` minted nothing). It is a dev/93-era artifact, but the user reads it as this run's output. Out of scope to delete; in scope to make sure this run never adds another.
- **S3** — Planning prose leaked into the reply ("*Since I must emit one tool request per reply, I am starting with…*"). Cosmetic; the one-request rule is real (`content.py:44-46`) and the model narrated it.

**Why it matters.** The Researcher's whole product is "findings become nodes". dev/93 closed the proliferation failure (author a duplicate package per question); the ladder now fails the *other* way — it places nothing — and reports `ok`. Every rung existed and was correctly populated; the agent lost on spelling, budget, and a prompt line. A weak local model (the deployment target per project memory) needs contracts that self-correct on the first miss, not exact-match lookups with hints for tools it lacks.

---

## 2. Scope

**In:**
- `utk_curio/backend/app/agents/services.py` — `_mint_package_install` (:2290-2360) dirName resolution + refusal text; the tool-round loop (:6795-6830, and the sibling loop at :7151-7158) round accounting for refused validations; `_available_templates_block` (:5000-5028) / `_template_line` non-authorable marking (S1).
- `utk_curio/llm-prompts/researcher_notes_instruction.txt` — rung-2 parameter wording (:9), failure semantics (:31), the false-negative claim rule; and the materialized copy under `.curio/users/guest/agents/agent.researcher@1.0.0/prompts/` follows via the dev/60 roster-bytes authority (no manual sync).
- `utk_curio/backend/app/agents/tools.py:206-219` — the `package.install` contract description (it says "dirName from packages.catalog results"; the Researcher's roster line is the other legitimate source).
- Tests: `test_agents/test_routes.py` (`TestReuseLadder`), `test_agents/test_builtin.py` (Researcher prompt-content + any sha pin), a new `test_agents/test_reuse_ladder_field.py` regression lane, `test_packages/test_available_templates.py` (roster marking).
- Docs on close: the repo memo-closing convention from dev/93 (index row in `00-development-phase-index.md`, `3.1` build-log line, BL id).

**Out:**
- Reopening dev/93's roster design, DEC-062's vocabulary, or the D4 grant posture — they worked.
- Making the Package Builder's *delegate* path roster-aware (dev/94 closed it).
- Deleting the pre-existing empty Post-it node (S2) — user's canvas, user's call.
- Raising `MAX_TOOL_ROUNDS` globally for all agents (rejected in §3.2).
- Frontend changes. None are needed; every fix is server-side prompt/mint/loop.
- The DFB→Researcher delegate path (dev/95) — it degrades honestly by design and never reached these seams.

---

## 3. Recommended Implementation Approach

### 3.1 D1 — resolve the dirName the way the roster spells it; refuse with an executable hint

`_mint_package_install` gains **one** resolver, `_resolve_catalog_dir_name(dir_name, rows) -> (row | None, hint)`, tried in order against the overview rows:
1. exact `dirName` (`curio.notes@1`) — unchanged;
2. bare package id (`curio.notes`) → the unique row whose `dirName` splits to that id (`dirName.rsplit("@", 1)[0]`); **two majors present → refuse naming both** (never guess a major);
3. a template id (`curio.notes/note-surface`, optionally `@1`) → strip the `/template` part and repeat (2), through dev/93's `canonical_template_id` vocabulary — never a second parser.

The refusal for a true miss stops naming `packages.catalog` unconditionally. It names what the *caller's* roster offered: *"package 'X' is not in the Nodes Catalog — use the dirName shown in parentheses in the 'Installed but NOT enlisted in this project' list (e.g. `curio.notes@1`), or a `packages.catalog` result when that tool is granted"*. The `granted` set is already on `loop_ctx`; the hint branches on it (the DEC-063 rule: executable on every path the agent runs on).

Same tolerance is **not** added to `_mint_node_create` — dev/93 already accepts both `pkg/tpl` and `pkg/tpl@major` there; the two mints stay in vocabulary lock-step and a test pins that they resolve the same strings the same way.

### 3.2 D2 — a refused validation is not a round

In both loops, a request whose mint returns `("refused", …)` from *parameter validation* (before any store/provider/delegate work) does not increment `rounds_used`; instead a separate `refusals_used` counter caps at `MAX_REFUSED_ROUNDS = 2` per run, after which the existing cap path (dev/73 cutoff card) applies. Rationale: a refusal is 3–7 ms and produces the correction text the model needs; the quota (REQ-QUOTA-001) is about *cost*, and the round cap was set by dev/73 for three productive steps. Raising `MAX_TOOL_ROUNDS` globally was rejected: it would let every agent spend more provider calls, whereas this change spends none — the provider is called once more only to consume the correction.

Implementation: `_mint_from_request` already returns the status; the loop keys off `status == "refused" and reason_is_validation` — expressed as a third return element (or a `RefusedValidation` marker) so a *store-broken* refusal ("Nodes Catalog is unavailable") still counts as a round (that one costs real work and should not loop).

### 3.3 D3 — the prompt distinguishes "fix it" from "stop"

`researcher_notes_instruction.txt`:
- :9 (ENLIST): *"Emit package.install with `"dirName"` set to the value in parentheses after `(package …)` on that list — the versioned dirName, e.g. `curio.notes@1`, never the bare id, never the template id."*
- :31 split into two sentences: a **refused tool request** ("the runtime says the parameters were wrong") → *correct the parameter or take the next rung, in the same run*; a **failed delegation, build, or applied proposal** → *report plainly and stop*.
- New rule beside A17: *"Never tell the user a package or template does not exist, is not installed, or is not in the catalog unless the refusal text said so verbatim; a refused request is not evidence of absence."*
- New rule: *"Do not narrate the one-request-per-reply mechanism to the user; just emit the request."* (S3)

The Researcher prompt is content-tested, not sha-pinned (`test_builtin.py` pins the DFB sha, not this file) — the content test gains the three new markers.

### 3.4 S1 — the roster marks templates that cannot take content

`_template_line` appends ` — no content (not usable for notes)` when `authorable` is False and the composing agent declares the `research.notes.compose` capability; simplest form: `_available_templates_block` takes the manifest's capabilities and passes a `mark_non_authorable` flag. The Available list stays complete (plans may still use compute templates) — it just stops reading as an invitation. dev/93's `resolve_template(..., require_authorable=True)` is the existing truth; this only surfaces it in the roster so the model never needs a refusal to learn it.

### 3.5 Candidate decision — DEC-067 (to be minted at implementation)

*A proposal refusal must be self-correcting on the path that produced it: it accepts every spelling its own roster taught, and when it refuses it names a source the refusing agent can actually read; validation refusals are free of the round budget.* Extends DEC-063 from prompts to refusal texts and loop accounting.

---

## 4. Data and State Handling

- **Source of truth unchanged**: `agent_catalog_overview` (lockfile ∪ locked store ∪ committed catalog) for install; `template_landscape` one-snapshot roster (dev/99 R1.1) for both halves. The resolver reads the overview rows it already fetched — no second read, no tear.
- **Derived**: the bare-id→dirName map is computed per mint from those rows (a dict of ≤ tens of entries), never cached across runs.
- **Round accounting**: `refusals_used` is loop-local like `rounds_used`; it appears in the execution record (`execution.refusedRounds`) so a run that hit the refusal cap is auditable, mirroring how `toolCalls[].status` already records each refusal.
- **Proposals**: unchanged — a resolved dirName mints the identical `package.install` part with `pins.dirName` set to the **canonical** dirName (not the model's spelling), so `_apply_package_install` (:2923) sees exactly what it sees today.
- **No new stores**, no frontend state, no migration.

---

## 5. UI and UX Requirements

No new UI. What the user must see change, through existing surfaces:
- One **Install package · Simple Notes** review card appears on the first turn (rung 2), or — when nothing is enlistable — a Package Builder delegation trace followed by the reviewed package draft card (rung 3). Never a chat-only answer while a rung remains.
- After Apply, the standard A16 jointly-pending sequence: yellow **Question** note card, green answer note card(s), applied in any order.
- Refusals that do surface keep the A4 posture: the reason and the way out are named in the agent's text; no "not in the catalog" unless true.
- The reply does not narrate internal mechanics (S3).
- Accessibility: unchanged — existing card components only.

---

## 6. Edge Cases

1. Bare id matches **two majors** in the catalog (`curio.notes@1`, `curio.notes@2`) → refuse naming both dirNames; never pick.
2. Bare id matches a **built-in** → existing "always present" refusal, unchanged.
3. Bare id matches an **already-enlisted** package → existing "already installed" refusal; the roster would not have listed it on rung 2 anyway.
4. Template-id form whose package is **not in the store** → true miss; hint names the roster list (and `packages.catalog` only if granted).
5. `refusals_used` reaches 2 → dev/73 cutoff card for a mutate request; text kept; execution record shows both counters.
6. A refusal caused by a **broken catalog** ("unavailable: …") still counts as a round (it is not a parameter error) — so a dead store cannot loop.
7. Lockfile `[]` with backfill (this project's exact state): Available holds the backfilled compute template marked non-authorable; rung 1 correctly skips it; rung 2 offers `curio.notes@1`.
8. Store holds **no** note template at all → rungs 1–2 empty, rung 3 delegation reachable within budget: search (1) + delegate (2) — verified by test, since this is the flow that was structurally impossible before.
9. Model sends canonical `curio.notes@1` (the happy path) → byte-identical behavior to today.
10. Second research question while the first install proposal is pending → unchanged A16/dev/84 semantics.
11. Delegate-path Researcher (dev/95) → untouched; it never mints from its own reply.

---

## 7. Testing Strategy

**Unit (`test_agents/test_routes.py` → `TestReuseLadder`, or a new `TestPackageInstallResolver`):**
- `curio.notes@1`, `curio.notes`, `curio.notes/note-surface`, `curio.notes/note-surface@1` all mint the **same** proposal with `pins.dirName == "curio.notes@1"`.
- Two majors → refused, both named. Built-in / already-installed → existing refusals unchanged (regression).
- True miss with `packages.catalog` NOT granted → hint names the roster list and does not mention `packages.catalog`; granted → hint names both.
- Node-create/package-install vocabulary lock-step: the same template-id string resolves to the same package in both mints.

**Loop (`test_agents/test_routes.py` fake-provider lanes):**
- A refused validation does not increment `rounds_used`; `refusals_used` increments; the record carries `refusedRounds`.
- Refusal cap: third validation refusal on a mutate tool → cutoff card, run ends `ok` with the card visible.
- Catalog-unavailable refusal counts as a round (edge 6).

**Regression — the field run, replayed (`test_agents/test_reuse_ladder_field.py`, new):** fixture store = `curio.postits@1` (compute template) + `curio.notes@1` (note behavior), lockfile `[]`; scripted model replies = search → `node.create` on the post-it → `package.install` `dirName: "curio.notes"` → (on correction) `package.install` `dirName: "curio.notes@1"`. Assert: exactly one pending `package.install` proposal for `curio.notes@1`, zero nodes added to the spec, reply text contains no "not in the catalog" / "not available". Second scripted variant: store without any note template → assert a `node.kind.author` delegation is reached within the budget (edge 8).

**Roster (`test_packages/test_available_templates.py` + composed-prompt test):** non-authorable Available rows carry the marker for a `research.notes.compose` agent and not for the Dataflow Builder; the marker keys on roster-emitted text only (dev/93's negative-assertion lesson).

**Prompt (`test_builtin.py` Researcher content test):** pins the versioned-dirName sentence, the refused-vs-failed split, the no-false-absence rule, and the no-narration rule.

Required before the change is complete: all of the above; the field replay is the gate.

---

## 8. Acceptance Criteria

1. In project state {Available = one non-authorable compute template; Installed-not-enlisted = `curio.notes@1`}, asking a research question yields, in one run, a searched answer **and** a pending `Install package · Simple Notes` card — no chat-only fallback.
2. `package.install` with `dirName` ∈ {`curio.notes`, `curio.notes@1`, `curio.notes/note-surface`} mints the same proposal pinned to `curio.notes@1`; ambiguous majors refuse naming both.
3. A refusal message never directs an agent to a tool it was not granted.
4. A parameter-validation refusal does not consume a `MAX_TOOL_ROUNDS` round; at most 2 such refusals per run, then the dev/73 cutoff card.
5. With no note template anywhere, the AUTHOR delegation is reached within budget (search + delegate) and produces the reviewed draft card.
6. The Researcher's reply never states a package/template is absent unless the refusal text said so; never narrates the one-request rule.
7. The Available roster marks non-authorable templates for note-composing agents; the Dataflow Builder's roster is byte-unchanged.
8. Existing dev/84/93/94/95 tests pass unchanged; DFB sha pin unchanged.
9. The execution record of a run that hit refusals shows `refusedRounds` alongside `toolCalls[].status`.

---

## 9. Recommended Commit Breakdown

- **Commit 1 — resolver + refusal text (D1)**: `_resolve_catalog_dir_name`, grant-aware hint, `tools.py` contract description, unit tests incl. lock-step test. No behavior change for canonical spellings.
- **Commit 2 — round accounting (D2)**: validation-refusal marker from the mints, `refusals_used` + `MAX_REFUSED_ROUNDS` in both loops, `execution.refusedRounds`, loop tests incl. catalog-unavailable-counts.
- **Commit 3 — prompt + roster marking (D3, S1, S3)**: `researcher_notes_instruction.txt` edits, `_template_line` marker, prompt-content and roster tests.
- **Commit 4 — field regression lane + docs**: `test_reuse_ladder_field.py` (both variants), DEC-067 minted, `BL-P5-20260825-NN`, index/build-log rows per the dev/93 closing convention, this memo's status → IMPLEMENTED.

Pathspec commits only (`git commit -- <paths>`); the index currently holds foreign staged work.

---

## 10. Engineering Quality Checklist

- [ ] One resolver, reused by the mint; template-id parsing goes through dev/93's vocabulary, no second parser.
- [ ] No duplicated roster logic — S1 marks in `_template_line`, the single line formatter.
- [ ] Refusal-vs-round distinction is a typed marker, not string-matching on reason text.
- [ ] Canonical dirName is what gets pinned; the model's spelling never reaches `_apply_package_install`.
- [ ] Both loops (`:6805`, `:7151`) changed identically; a test exercises each.
- [ ] Hints branch on `granted`, never on agent id (any future agent with the same grants gets the same truth).
- [ ] Prompt changes are content-tested; DFB byte pin untouched.
- [ ] Field replay test is the gate; it fails on `16b994b7` and passes after commit 3.
- [ ] No frontend change, no new state, no flicker surface.
- [ ] Docs closed per the repo convention; memory note updated to point here.

---

## Amendment A1 (2026-08-25, after the live test) — D4: the frontend's install review gate only knows the committed catalog

**Status: IMPLEMENTED (2026-08-25) — commit 5: `usePackageInstallReview.beginReview` loads the store (`listInstalled`) and the catalog in parallel, store row first, probe set = store dirNames; hook jest lane 10/10 (5 new/extended); `tsc --noEmit` reports no errors in the touched files (pre-existing errors elsewhere untouched).**

### A1.1 Live result of commits 1–4

Re-asked "what's the weather in Paris?" in project `46dbf1d8…` (session `ebcb0c4b…`, screenshot `Desktop/Screenshot 2026-08-25 at 1.53.47 PM.png`) against the reloaded backend (`use_reloader` on; worker restarted 13:46 after the commits). D1–D3 hold in the field: the Researcher searched, stated the answer, and on the **first turn** minted **Install package · Simple Notes** (`curio.notes@1`) with the reason "I need a note template to display the current weather findings on the canvas" — no chat-only fallback, no false "not in the catalog" claim, no narration. The ENLIST rung is now reached and proposed exactly as dev/93 designed.

**Apply then failed in the frontend**, before the backend was called: the card's error line reads *"package curio.notes@1 is no longer in the Nodes Catalog"*.

### A1.2 Root cause

`usePackageInstallReview.beginReview` (`utk_curio/frontend/urban-workflows/src/components/agents/attach/usePackageInstallReview.ts:54-57`) resolves the proposal's `dirName` against `packagesApi.catalog()` = `GET /api/packages/catalog` (`packages/routes.py:333-394`), which scans **only the committed `<repo>/packages/` catalog**. A store-only, agent-authored package — precisely what dev/93 D4 made proposable by teaching `agent_catalog_overview` to enumerate the user's store — is never in that list, so the hook throws before opening the dialog. The backend apply (`_apply_package_install` → `agent_resolve_report`, `packages/services.py`) already treats the store index as installable and would have succeeded; dev/93's "enlist-then-create end to end" test proved the backend path and never exercised the frontend gate. The same hook also derives the conflict-probe's `installed` set from the catalog rows' `installed` flag, which likewise omits store-only packages — a second, latent inaccuracy in the same lookup.

### A1.3 Fix (one hook, one lookup rule)

`beginReview` loads **both** feeds in parallel — `packagesApi.listInstalled()` (`GET /api/packages`, the user's store, same `PackagePayload` shape per the route docstring) and `packagesApi.catalog()` — and resolves the row as *store row first, else catalog row*; the conflict probe's `installed` set becomes the store's dirNames (what "every user-store package" in the existing comment actually means). The "no longer in the Nodes Catalog" error remains for a true miss in both feeds and its text gains "or your installed packages". No backend change; no new endpoint; the dialog, `confirm`, and `cancel` are untouched.

Rejected: (a) adding store rows to `/api/packages/catalog` — that route is the fixture-backed *catalog* with families/collision semantics, and the drawer relies on its meaning; (b) a new agent-specific endpoint — `agent_catalog_overview` exists server-side but the dialog needs the full `PackagePayload` (permissions, dependencies), which `/api/packages` already serves.

### A1.4 Tests

`src/tests/attach/usePackageInstallReview.test.tsx`: mock `listInstalled` alongside `catalog`; (1) a store-only package (absent from the catalog mock, present in the store mock) opens the dialog with the store row and the probe list includes every store dirName + the candidate; (2) a catalog-only package still resolves (regression); (3) a package in neither feed rejects with the (extended) error before any dialog; (4) the probe's `installed` set comes from the store feed even when the catalog marks nothing installed. `tsc --noEmit` on the touched files.

### A1.5 Acceptance

Applying the live **Install package · Simple Notes** card opens the package install review dialog for `curio.notes@1`; Install enlists it (lockfile gains `curio.notes@1`, `curio.notes/note-surface` becomes available); the Researcher's next turn creates the yellow Question and green answer notes. §8 AC-1 is amended to include this frontend step.

### A1.6 Commit

- **Commit 5 — frontend review gate reads the store too**: the hook change + the four jest lanes; BL-44 gains a "found by the live test" deviation line; this amendment's status → IMPLEMENTED.

---

## Amendment A2 (2026-08-25, after the second live test) — D5: the notes land, white and untitled — `node.create` never carries what the note behavior renders

**Status: IMPLEMENTED (2026-08-25) — commit 6: `node.create` contract names `title`/`goal`/`appearance.backgroundColor`; `_mint_node_create` stores a bounded `title` (echoed in the summary) and fills the A13 default (`_NOTES_DEFAULT_COLORS`, indexed by the run's `_note_creates` counter) only for a `research.notes.compose` run on a `presentation` template with no color given; `_apply_node_create` forwards `title` to `_insert_node`; dev/95's delegate rows map `title → title`; prompt REUSE rung names the exact params. Tests: field variant C (two uncolored creates → `Question`/yellow, `Weather in Paris`/green on the applied nodes), A13 narrowness lanes (explicit color wins; Researcher on a code template and Node Builder on a note template stay uncolored), contract + prompt markers; `test_agents` + `test_packages` 1460 passed / 4 skipped.**

### A2.1 Live result of commits 1–5

Session `90f6fccc…` (screenshot `Desktop/Screenshot 2026-08-25 at 2.09.15 PM.png`): after enlisting `curio.notes@1`, the Researcher minted TWO `node.create` proposals in one run (`toolCalls`: `ok, proposed, proposed` — the A16 sequence), both applied, and two `curio.notes/note-surface` nodes exist on the canvas with the right content (question; markdown answer with the source link). **The ladder is closed end to end.** But both notes render **white** with the header **"Note"** instead of yellow "Question" / green "Weather in Paris".

### A2.2 Root cause — three gaps on ONE path, all server-side

The stored nodes carry `goal: "User Question"` / `goal: "Weather Answer"`, `content`, and **no `title`, no `metadata.appearance`**. The `curio.notes` behavior renders `data.title || 'Note'` and `nodeState.appearance?.backgroundColor || 'white'`, and the frontend already round-trips exactly `node.title` and `node.metadata.appearance` for agent-created nodes (`useAgentCanvasMutations.ts:57-66`, the dev/89 typed round-trip). Nothing put them there:

- **G1 — the contract never names them.** The `node.create` tool contract the model reads at the tail (`agents/tools.py:229-233`) documents `{"nodeType", "content", "goal"}` only. The Researcher prompt asks for "a short title, and an appearance color" (`researcher_notes_instruction.txt:7`) — a parameter the tool's own description does not admit. The model did the reasonable thing: it sent `goal`. DEC-063/DEC-067 shape again — an instruction not executable through the contract it is given.
- **G2 — the mint drops `title` and apply never forwards it.** `_mint_node_create` reads `content`, `goal`, `appearance` (dev/89) and ignores `params.title`; `_apply_node_create` calls `_insert_node(spec, node_type, content, goal, appearance=…)` although `_insert_node` already accepts `title=` (used by the package-draft apply). `goal` is the node's purpose line, not its header.
- **G3 — no A13 default on the attachment path.** dev/95's delegate mint fills `_NOTES_DEFAULT_COLORS[min(index, 1)]` (question yellow, answers green) when a row omits its color; the Researcher's OWN attachment runs — the path the user actually uses — have no equivalent, so an omitted color means white.

(Not a defect: dev/93/95's E2E lanes asserted `metadata.appearance` in the spec when the model DID pass it; nothing asserted the path where it did not.)

### A2.3 Fix

1. **Contract (G1)** — `tools.py` `node.create` description names the full accepted shape: `{"nodeType", "content", "goal" (optional purpose line), "title" (optional header), "appearance": {"backgroundColor": "<palette name or #RRGGBB>"} (optional)}` — the same vocabulary `package.draft.apply`'s `nodes[]` already teaches at :257-260, so one shape, twice stated.
2. **Mint + apply (G2)** — `_mint_node_create` reads `params.title` (string, stripped, bounded like `goal`), stores it on the proposal (`proposal["title"]`) and echoes it in the summary (`Create a new Note node · Question`); `_apply_node_create` passes `title=proposal.get("title")` to `_insert_node`. Both proposal mirror and turn part are additive (absent when not given). dev/95's delegate mint switches its row mapping from `goal: row["title"]` to `title: row["title"]` so the header renders there too — `goal` stays for a row that carries one.
3. **A13 default on the attachment path (G3)** — in `_mint_node_create`, when `appearance` is absent AND the run's manifest declares `research.notes.compose` AND the resolved template is a `presentation` template (the dev/105 S1 flag), fill `_NOTES_DEFAULT_COLORS[min(k, 1)]` where `k` = the number of `node.create` proposals already minted in this run (`loop_ctx["minted"]`-derived — the first note yellow, the rest green). Model/user-supplied colors always win; other agents and non-presentation templates are byte-unchanged. The defaults live in ONE tuple (`_NOTES_DEFAULT_COLORS`) shared with dev/95.
4. **Prompt** — one clause on the REUSE rung: the exact `node.create` params `{"nodeType", "title", "content", "appearance": {"backgroundColor": …}}`, mirroring the contract.

### A2.4 Tests

- Contract test: the description names `title` and `appearance.backgroundColor`.
- Mint: `title` stored and bounded; absent title → no key; summary carries it. Apply: `title` and `metadata.appearance` land on the node (`_insert_node` round-trip).
- A13 default: Researcher run, presentation template, no `appearance` → first note `yellow`, second `green` (normalized hex via `node_appearance`); explicit color wins; a Dataflow Builder / Node Builder `node.create` without appearance stays without; a non-presentation template stays without.
- dev/95 delegate lane: rows now produce `title` (and `goal` only when given).
- Field lane `test_reuse_ladder_field.py` gains a third variant: the enlisted-store run (`curio.notes@1` in the lockfile) → two `node.create` requests without colors → applied nodes carry `title` and `yellow`/`green` appearance.

### A2.5 Acceptance

Re-running the live sequence yields a yellow note headed **Question** and a green note headed **Weather in Paris** (or the model's title), content unchanged; the DFB/Node Builder create flows are unchanged; the delegate path's notes gain headers.

### A2.6 Commit

- **Commit 6 — `node.create` carries title + appearance, A13 defaults on the attachment path**: tools contract, mint/apply, delegate row mapping, prompt clause, tests incl. field variant C; BL-44 deviation line; this amendment → IMPLEMENTED.
