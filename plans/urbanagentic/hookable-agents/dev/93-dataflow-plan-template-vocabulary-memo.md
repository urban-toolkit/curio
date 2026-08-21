# dev/93 — Agents cannot create nodes: a plan path that speaks one spelling, a reuse-first path with no door, and a package store that oscillates

**Status: IMPLEMENTED (2026-08-21) — commits landed as `aa6f5c95` (2), `fb30b658` (6), `307fd112` (1), `2d70c6b2` (3), `9876ae9d` (4), `f2c5f669` (5), + docs; DEC-062 minted; BL-P5-20260821-35. All five defects (D1–D5) closed; deviations and A/B verification recorded in amendments A1–A4.**

Two follow-ups surfaced and are deliberately NOT in scope here: readers taking the seed lock to close the swap's two-rename absence gap (A1), and roster-aware delegate runs — a delegate composes only preamble + instruction with `tools=[]` (DEC-046) and the frontend context rides the *parent's* request, so the Package Builder cannot know a suitable package already exists at the moment it is asked to author one. That is the deepest root of the duplication this memo fixed from both ends.

Date: 2026-08-21
Branch / tree: `feat/agentscatalog` @ `53b33f37` (dev/91 commit 6). Every line number below is pinned to this commit; the previous draft of this memo was pinned to `b5915198` (dev/90 A16), which is an ancestor — all findings were re-verified here, and dev/91's six commits do not fix any of them.
Family: A4 / dev/90 A14 — "one value with two legal spellings, and only one validator that accepts both"

**Evidence**
- Screenshots `Screenshot 2026-08-21 at 11.23.26 AM.png`, `Screenshot 2026-08-21 at 11.24.04 AM.png` — **Dataflow Builder** session `c82b4195`, since deleted by the user
- **Researcher** session `a4baf769117e439ca3c010288edf9af3` ("Paris weather inquiry") and its **Package Builder** delegate session `7f47d37ee5dc449a8eb034f3ce28a064`
- **Dataflow Builder** session `3c7c236d96504a1bb8a132155f3470d5` ("Clear Nodes Request", 12:08) — a removal-only plan that *succeeded*, which is itself a finding
- A live, non-mutating repro executed against the running project on this branch (§1, "Reproduced now")

Project: guest / `a9a1afc7-48af-4d82-97ac-315de50fbe9a`. Provider `openai_compatible`, model `gemma4`, `maxOutputTokens: 4096`.

**Two Curio agent sessions failed to create nodes, for two different reasons that share one root.** The Dataflow Builder looped on template-id spellings (D1–D3). The Researcher could not reuse a note template the user already had installed, so it authored a *new package* instead — twice in one run (D4–D5). Everything traces back to one project-scoped roster that is sometimes degraded, spelled inconsistently, and unable to say "this exists but is not enlisted here" — and to a codebase habit of swallowing the real error and reporting something else.

---

## 1. Problem Statement

### What the user saw

The Dataflow Builder was asked: *"Plan a dataflow that explores my data over time: create a list with random values to plot."* Every attempt was refused. The last turn is the agent reasoning about its own refusals:

> "I apologize for the repeated errors regarding the template IDs. I am carefully re-examining the 'Installed node templates' list provided in the prompt. Since `curio.builtin/data-loading@1` is listed but was rejected by the validation system, I will use the simplified base IDs that correspond to the functional types provided in the system description."

followed by the terminal card:

> **Plan not proposable** — ERROR
> `plan node 'gen_data' uses 'DATA_LOADING', which is not an available template for this project`

33.1k tokens, 4 correction rounds, nothing produced. The model is not confused: it quoted an id from a list its own prompt gave it, was refused, and — with no other hypothesis available — fell back to the legacy enum spelling and was refused again. A guaranteed loop, and the *second* report of this exact loop (dev/90 A14 recorded the first, on the `node.create` path).

### Reproduced now, on this branch, against the live project

The plan path and the `node.create` path disagree about what a template id is. This is a read-only check — `available.get(...)` is exactly what `_mint_dataflow_plan` does (`agents/services.py:1385`), `_available_template` is what `node.create` does (`:5086`):

| nodeType | plan mint | node.create |
|---|---|---|
| `curio.builtin/data-loading` | **PROPOSE** | OK |
| `curio.builtin/data-loading@1` | **REFUSE** | OK |
| `curio.postits/post-it-note@1` | **REFUSE** | OK |
| `DATA_LOADING` | REFUSE | REFUSE |
| `curio.notes/note-surface` | REFUSE | REFUSE |

Read the third row carefully. `curio.postits/post-it-note@1` is the type of **the node currently sitting on this user's canvas**, and it is the exact string the runtime itself wrote into its own proposal preview eight minutes earlier (session `3c7c236d…`, 12:08: *"− Remove: 852f1241… · curio.postits/post-it-note@1"*). The Dataflow Builder cannot write a plan referencing a node type it can see, in the spelling the runtime uses to show it. The last row is D4: `curio.notes/note-surface` is installed in the user's store right now and refused everywhere.

### The removal-only plan that worked

At 12:08 a Dataflow Builder plan **succeeded** — "clear nodes", applied, two nodes removed. It succeeded because a removal-only plan carries **zero** nodes, so the loop at `services.py:1384-1392` never executed. The plan path works precisely when it does not have to validate a nodeType, and fails whenever it does. That is the cleanest available statement of the defect's shape.

---

### D1 — The built-in package store oscillates between complete and truncated, so the entire built-in vocabulary intermittently vanishes

`_ensure_user_seeded` (`packages/routes.py:246-280`) runs on four request handlers — `GET /api/packages` (`:287`), `GET /api/packages/catalog` (`:317`), `GET /api/packages/defaults` (`:1198`), `POST /api/packages/defaults` (`:1234`) — and calls `seed_dev_packageages`. Inside the seeder, the built-in package is re-seeded **unconditionally, on every single call**:

```python
# utk_curio/backend/app/packages/seed.py:207-236
is_builtin = src.name == keep_builtin_name
if force or is_builtin:
    do_seed, reason = True, "forced-builtin" if is_builtin else "forced-by-env"
...
if dest.exists():
    shutil.rmtree(dest)          # <-- the LIVE directory is deleted
try:
    shutil.copytree(src, dest)   # <-- then rebuilt file by file
except OSError as exc:
    log.warning(...); continue   # <-- a failed copy leaves whatever partial tree exists
```

`rmtree`-then-`copytree` into the live path is neither atomic nor serialized, and the frontend fires several of those endpoints around canvas mount and drawer open. Any overlap leaves the directory deleted or half-populated; a `copytree` that races a peer raises, is swallowed as a warning, and the partial tree is kept.

**Observed, three times, without touching any code:**

| Time | `.seed-state.json` `seededAt` | Store contents | `available_templates` |
|---|---|---|---|
| 11:19:32 | 1787329172.59 | `integrity.json` **only** | 2 (note surfaces) |
| 11:23:26 | — | truncated | 2 → the screenshot's refusal |
| 11:35:59 | 1787330159.33 | complete | 12 built-in |
| 13:29:15 | 1787336955.79 | complete (current) | 13 |

At 11:19 the directory held exactly one of its three files. `manifest.json` and `README.md` were gone while `integrity.json` still listed checksums for both, and the manifest load failed outright:

```
ManifestError: missing manifest.json in .curio/users/guest/packages/curio.builtin@1
```

Every numbered user (`.curio/users/1..30`) has a healthy 12-template built-in manifest; only `guest` — the user the dev app runs as — was broken, and only transiently. **The store is healthy as of this writing, which is exactly what makes this dangerous: inspect it at a lucky moment and nothing is wrong.** Nothing in dev/91 changed the seeder.

While truncated, the vocabulary the backend believed the project had was two note-surface templates — no `data-loading`, no `computation-analysis`, no `vis-vega`, no `merge-flow`. The dataflow the user asked for was unbuildable in any spelling.

### D2 — The failure is silent at every layer, so it surfaces as a false statement three layers away

`available_templates` (`packages/services.py:257-260`) swallows an unreadable package:

```python
try:
    manifest = load_packageage_manifest(path)
except (ManifestError, OSError):
    continue
```

No log, no metric, no signal to the caller. `_available_templates_block` degrades the same way (`agents/services.py:4802-4805`, `except Exception: return None`). Nothing verifies a seeded package against the `integrity.json` it ships with. So a corrupted install reaches the model as *"`curio.builtin/data-loading@1` … is not an available template for this project"* — a sentence that blames the model for a broken install and feeds it into correction rounds it cannot win.

### D3 — The plan path refuses the versioned spelling. This is dev/90 A14, unfixed on the plan path

Two rosters reach the same run, in two spellings, under two headings:

| | Source | Heading | Spelling | Scope |
|---|---|---|---|---|
| (a) | backend `_available_templates_block`, `agents/services.py:4796-4817` | "Available node templates" | **unversioned** `curio.builtin/data-loading` | project-available ∩ `authorable` |
| (b) | frontend `installedTemplates`, `agentRunContext.ts:125-130` | "Installed node templates" | **versioned** `curio.builtin/data-loading@1` | whatever the client registry has in the palette |

List (b) is what the agent quoted. The client registry keys descriptors by the versioned canonical (`registry/nodeRegistry.ts:6-13`, `registry/packagesClient.ts:51,208`), and the Dataflow Builder declares that read (`agents/builtin.py:223`). `graphContext` is a third versioned source — spec nodes carry `data.nodeType` versioned — and, as the 12:08 session shows, the runtime's own proposal previews are a fourth.

The plan mint exact-matches the unversioned key only:

```python
# utk_curio/backend/app/agents/services.py:1381-1392
available = {t["id"]: t for t in packages_services.available_templates(user_key, project_id)}
for node in plan["nodes"]:
    entry = available.get(node["nodeType"])      # exact match; no @major tolerance
    if entry is None:
        return "refused", f"plan node {node['ref']!r} uses {node['nodeType']!r}, which is not an available template for this project", None
```

The A14 fix — accept the versioned form by stripping the major — lives at `:5100-5107` and **only** there. Three plan-path checks never got it:

- `services.py:1385` — plan mint (the screenshot's refusal)
- `services.py:1718` — per-node plan apply (`"node type … is no longer available"`)
- `services.py:2554` — whole-plan apply (`"plan node type(s) no longer available"`)

A version-stripping helper sits 120 lines above the mint — `_strip_type_version` (`:1260-1264`) — used for *existing spec* node types but never for `plan["nodes"][i]["nodeType"]`. And a third spelling is in play: `NodeType.DATA_LOADING = "curio.builtin/data-loading"` (`frontend/src/constants.ts:13-30`), whose legacy keys are normalized client-side by `aliasNormalize` and are unknown to the backend.

Worth noting for context: dev/91 explicitly invoked this lesson while building the new subsystem — `backend_policy.py` owns "the ONE grammar (A14: one value, one parser)" for backend declarations. The lesson was applied to the new code and still not to the plan path.

### D4 — Reuse-first has no door: a package the user has installed is invisible to a project that has not enlisted it, and the agent that needs it cannot enlist it

The second failing session. The Researcher's transcript, in its own words:

> "The current weather in Paris is approximately 19°C … **Since there is no installed notes template on your canvas, I will request the creation of a new notes package** to display this information.
> I apologize for the error. It seems **the package builder failed to return a valid proposal** from my previous request. I will refine the delegation…"

Its execution record shows **two** `node.kind.author` delegations in that one run (`3ebce8db…`, `6b1f8ad7…`, both `status: ok`). The Package Builder's session shows what each produced: the first authored **`curio.notes`** (template `note-surface`), the second **`curio.postits`** (template `post-it-note`). Only the second minted a proposal. One question about the weather produced two package-authoring attempts under two different ids.

`available_templates` is *store ∩ project lockfile* plus built-ins (`packages/services.py:246-249`). Measured on this branch, right now:

```
store:            curio.builtin@1, curio.notes@1, curio.postits@1, curio.weather@1
project lockfile: {curio.postits@1}
available (13):   12 × curio.builtin/*  +  curio.postits/post-it-note
                  curio.notes/note-surface is INSTALLED and NOT OFFERED
```

So a note template purpose-built for this job, already in the user's store, is not in the Researcher's roster, and a `node.create` naming it is refused with *"not an available template for this project"* — true, and unusable, because **the Researcher has no way to make it available**:

- its tools are `dataflow.read`, `web.search`, `web.fetch`, `node.create`, `package.draft.apply` (`builtin.py:332-333`) — **no `package.install`**;
- `package.install`, the reviewed lane that adds an installed package to a project (`agents/tools.py:206-219`, dev/84), is granted only to `agent.package-recommendation` (`builtin.py:260-261`);
- its delegates are `agent.package-builder` and `agent.node-researcher` (`builtin.py:334`) — **not** `agent.package-recommendation`.

Authoring a new package is the only door open to it. The store's history is the receipt: four generations for one job — `curio.notes@1`, `curio.postit@1` (tombstoned 2026-08-20 17:05), `curio.postits@1`, `curio.weather.notes@1` (tombstoned 2026-08-21 11:35). dev/90 A14 made note templates *authorable*; nothing made an existing one *reachable*, so reuse-first inverts into package proliferation.

The roster also cannot express the distinction the model needed. It has one bucket, so "no note template exists anywhere" and "one exists but this project hasn't enlisted it" are indistinguishable — and the Researcher told the user the first when the truth was the second.

### D5 — An unparseable delegate draft is a dead end: no correction round, and the delegation still reports success

When the Package Builder's reply does not parse as a build request, `_mint_package_draft_from_delegate` (`agents/services.py:5810-5855`) discards it and hands the parent:

> "the authoring delegate returned no parseable package draft (expected one JSON build request); its reply was kept as text — refine the delegation inputs and try again"

No parse error, no offending fragment, no line number (`_extract_draft_params`, `:5701`, returns bare `None`). The delegation part the user sees records **`status: "ok"`** — `content.py:861` derives status from whether the child *ran*, not whether it *produced* anything — so the card reads "Delegated task · ok" beside a summary saying nothing was produced. With no diagnostic to act on, the parent's "refinement" was to re-delegate under a *different package id*. That is how duplicate #2 was born.

This is the one mutation lane with no correction round, and the pattern it needs exists twice in the same file:

| Path | Correction rounds | Error fed back |
|---|---|---|
| `dataflowPlan` | yes — dev/54, `services.py:2095` + `:2173` cap → "Plan not proposable" | validation errors → same model |
| `node.content.generate` | yes — `services.py:4154` (`_VALIDATE_CORRECTION_ROUNDS = 2`), loop `:4292-4310` | `previousAttempt` + `validationError` → same delegate |
| **package draft via delegation** | **none** | **nothing — one shot, vague hint to the parent** |

With `gemma4` at 4096 output tokens emitting a long JSON body containing an embedded `.tsx` source, a slightly malformed reply is the *expected* case. A one-shot contract there is a design mismatch.

A diagnosability note, deliberately **not** counted as a defect: the persisted child reply is capped at 2000 characters (`services.py:5472`) for the transcript only — the full text is what gets parsed. Both stored drafts are exactly 2000 chars, so the transcript cannot explain a failed draft after the fact. The parse error should be persisted beside it.

### Expected behavior

1. A project whose built-in package is on disk must expose all 12 built-in templates to plans and to `node.create`. A truncated store must self-heal, loudly.
2. Every template-id validator must accept every spelling the system emits into a model's context: unversioned canonical, versioned canonical, and the legacy enum name.
3. When the registry is degraded, the refusal must say so, not blame the id.
4. A run must carry **one** roster, under **one** heading, in **one** spelling.
5. An agent told to reuse must have a reviewed way to obtain what it can see the user owns, and the roster must distinguish "usable here" from "installed, not enlisted" from "nowhere". Authoring is the last door, not the only one.
6. A delegated draft that fails to parse or validate gets the same capped correction rounds as a plan or a generated node content, with the real error fed back — and a delegation that produced nothing never reports `ok`.

### Why it matters

Two of the four agents attached to this canvas cannot do the thing they exist to do, and both failures are manufactured by validators and rosters rather than by anything the models got wrong. "Plan a dataflow" is the product's headline gesture; on this branch it works only when the plan contains no nodes. The Researcher's reuse-first contract — the entire point of dev/90 — inverts into authoring a duplicate package per question, growing the store without bound, littering it with tombstones, and leaving canvases pointing at packages that come and go. And every one of these failures teaches the *user* that the agents are unreliable, when the truth is that the agents were handed contradictory instructions and punished for following them.

---

## 2. Scope

### In scope

**Packages domain (the outage + the silence)**
- `packages/seed.py` — atomic, serialized, self-healing seeding; drop the per-request forced re-seed.
- `packages/routes.py:246-280` — `_ensure_user_seeded` becomes cheap and idempotent.
- `packages/services.py:217-288` — `available_templates` reports degradation instead of swallowing it; the new shared resolver and the store-scoped companion listing live here.
- `packages/seed_state.py` — a health marker if the self-heal decision needs one.

**Agents domain (the loop)**
- `agents/content.py:350-425` — canonicalize `nodeType` at parse time (`:408` is the single assignment).
- `agents/services.py` — `_mint_dataflow_plan` (`:1353`, check at `:1385`), per-node apply (`:1718`), whole-plan apply (`:2554`), `_available_template` (`:5086`) all route through the one resolver; `_available_templates_block` (`:4796`) fixes its header, scope, and truncation logging.
- `utk_curio/llm-prompts/orchestration_instruction.txt:7` — name the single roster.

**Agents domain (the reuse door — D4)**
- `agents/services.py:4796-4817` — the roster gains an "installed, not enlisted" section.
- `agents/builtin.py:317-335` — the Researcher gains a reviewed enlist path.
- `utk_curio/llm-prompts/researcher_notes_instruction.txt` — the reuse → enlist → author ladder.

**Agents domain (draft correction rounds — D5)**
- `agents/services.py:5701` (`_extract_draft_params`) and `:5810-5855` (`_mint_package_draft_from_delegate`) — verbose parse errors + capped rounds modeled on `:4292-4310`.
- `agents/content.py:840-863` — `make_delegation_part` must report the outcome, not the child's run status.
- `agents/services.py:5460-5480` — persist the parse error beside the bounded reply.

**Frontend**
- `components/agents/attach/agentRunContext.ts:125-130` — the duplicate `installedTemplates` roster.

**Tests**
- `backend/tests/test_packages/` — seeding atomicity, concurrency, self-heal.
- `backend/tests/test_agents/test_routes.py` — versioned + enum nodeType through the plan mint and both apply paths; the reuse ladder; draft correction rounds.
- `frontend/.../tests/attach/agentRunContext.test.ts:143`.

### Out of scope

- **dev/91's backend-sandbox work.** It is landed and healthy; D5's fix wraps `_mint_package_draft_apply`, which dev/91 commit 4 just extended with backend provenance — coordinate, do not revert. No dev/91 behavior changes here.
- The correction-round machinery for plans (dev/54) and the "Plan not proposable" card — they behaved correctly, faithfully reporting a refusal that should not have happened.
- The plan grammar, fan-in/merge validation (dev/67-3), removals (dev/59), Solve, delegation transport.
- The client registry's versioned keying (`nodeRegistry.ts:6-13`) — deliberate, stays.
- Package install/publish/promotion flows, except where they share the atomic-move helper.
- Making `curio.builtin` installable/uninstallable differently; it stays always-present.

### Check but do not change unless required

- `packages/installer.py:422-500` — the staging + `os.replace` pattern to reuse.
- `projects/storage.py:137-180` — `spec_write_lock`'s thread-lock + `flock` pattern to reuse.
- `packages/target_locks.py` (untracked in the working tree) — confirm whether it already offers the per-key lock this needs before adding another.

---

## 3. Recommended Implementation Approach

Five defects, three separable fixes. **D1 is the intermittent outage**, **D3 is the reported loop**, **D4/D5 are the second session's failure**, and **D2 is why none of it was visible.**

### 3.1 Fix D1 — seed atomically, seed once, self-heal

**(a) Never mutate the live directory in place.** Copy into a sibling staging dir and swap: `copytree` → `os.replace(dest, trash)` → `os.replace(staging, dest)` → `rmtree(trash)`, with a crash-tolerant trash sweep. Reuse the installer's established pattern (`installer.py:493`, "the same filesystem so `os.replace` still moves atomically"). A reader then sees either the old complete tree or the new complete tree — never a half tree.

**(b) Serialize seeding per (user, package)** with the dual lock `spec_write_lock` already uses — an in-process `threading.Lock` plus a cross-process `flock` — so the Werkzeug reloader's two processes and concurrent request threads cannot interleave. Factor `projects/storage.py:162-180` into a shared helper rather than writing a second `flock` block; check `packages/target_locks.py` first.

**(c) Stop force-re-seeding on every request; re-seed only when stale or unhealthy.** Replace `if force or is_builtin` (`seed.py:208`) with:

```python
if force:
    do_seed, reason = True, "forced-by-env"
elif is_builtin and not _package_is_healthy(dest):
    do_seed, reason = True, "builtin-unhealthy"      # self-heal, logged at WARNING
else:
    do_seed, reason = seed_state.should_seed(record, runtime_exists=dest.exists(), fixture_mtime=fixture_mtime)
```

`_package_is_healthy(dest)` = `manifest.json` loads **and** every path named in `integrity.json` exists — one manifest parse plus a few `stat`s, cheap enough for the request path. The "users cannot end up without the default kinds" guarantee that motivated the force survives: `should_seed` already returns True for a missing copy, and the health check covers the corrupt case the force never addressed. This removes the race *window* from the overwhelming majority of requests; (a) and (b) make the remaining seeds safe. Full checksum verification stays behind `CURIO_VERIFY_PACKAGES` — too expensive per request to default on.

### 3.2 Fix D3 — one resolver, canonicalize at the boundary

**The single source of truth**, in the domain that already owns all template knowledge (`ADR-AG-007`):

```python
# utk_curio/backend/app/packages/services.py
_LEGACY_TEMPLATE_ALIASES = {"DATA_LOADING": "curio.builtin/data-loading", ...}   # the 11 constants.ts NodeType values

def canonical_template_id(node_type: str) -> str:
    """Every spelling the ecosystem emits → the unversioned canonical id.
    Accepts 'pkg/tpl', 'pkg/tpl@major', and the legacy enum names that trill
    files and older prompts still carry. Shape only — no availability."""

def resolve_template(user_key: str, project_id: str, node_type: object,
                     *, require_authorable: bool = False) -> tuple[dict | None, str]:
    """Resolve any spelling against available_templates. Returns
    (entry | None, error_text) — the single availability gate for plans,
    node.create, and both apply paths."""
```

`resolve_template` owns the refusal text, so plans and `node.create` finally speak with one voice, and it can distinguish "this project has no such template" from "the registry is degraded" (D2).

**Canonicalize at the boundary, validate once, store canonical.** In `content.py:408`, as the plan is parsed:

```python
"nodeType": packages_services.canonical_template_id(str(node_raw["nodeType"]).strip()),
```

This is the load-bearing choice. Once the parsed plan carries the canonical id, the stored proposal, the pinned shape digest, and **both apply-time re-checks** (`:1718`, `:2554`) are correct with no further edits — they compare canonical to canonical by construction. Adding `@`-stripping at four call sites would leave the fifth for the next person to find; normalizing at the one entry point cannot. Keep the boundary shape-only (no I/O); availability stays where refusals are minted.

Then swap the raw dict lookup at `:1385` for `resolve_template` per node. Note the asymmetry to make explicit: plans intentionally allow **non-authorable** templates (a plan places a typed placeholder; content comes later from Solve), so the mint passes `require_authorable=False` while `_available_template` passes `True`. Today that difference is an accident of two separate implementations.

**Prompt honesty.** `_available_templates_block` (`:4796-4817`) needs three corrections:
- Its header says *"a node.create nodeType MUST be exactly one of these ids"* — the wrong tool for a planner holding `dataflow.plan.write` (the block is gated on either grant at `:4731`). Name both, and state that the versioned form is accepted.
- It filters to `authorable` (`:4806`) while plans may use any available template, so the planner's advertised vocabulary is a strict subset of its legal one — `merge-flow`, which the instruction explicitly tells it to use (`orchestration_instruction.txt:7`), is only listed if it happens to be authorable. List every available template for a plan-capable run, marking which hold authored content.
- Keep the `_TEMPLATES_BLOCK_MAX_ENTRIES = 60` bound and **log when truncation drops entries** (no silent caps).

### 3.3 Fix D4 — give reuse-first a door, and make the roster say which door

**Three buckets, not one.** Extend the block to two labelled sections:

```
Available node templates (usable now — a node.create nodeType or a plan nodeType
MUST be one of these ids; the versioned form '<pkg>/<tpl>@<major>' is accepted):
- curio.postits/post-it-note — Post-it Note: …

Installed but not enlisted in this project (propose package.install to use one —
do NOT author a duplicate package):
- curio.notes/note-surface — Note (package curio.notes@1)
```

The second section needs a store-scoped companion in the packages domain (e.g. `installed_templates_not_in_project(user_key, project_id)`) sharing the manifest walk, so exactly one place still reads manifests. Bound both sections together under the 60-entry cap and log truncation.

This alone would have prevented the incident: the Researcher would have read "a note template exists, enlist it" instead of concluding none existed.

**Give the Researcher the enlist lane.** Two options:

- **(a) Grant `agent.researcher` the `package.install` tool** (`builtin.py:332-333`). It is already the reviewed lane (dev/84): the user approves through the package-install dialog, permissions/dependencies/conflicts are checked, built-ins are refused by contract. No new machinery, no extra hop.
- (b) Add `agent.package-recommendation` to its `delegates_to`. Architecturally tidier — recommendation owns installs — but adds a provider round-trip and another weak-model hop for what is a one-parameter action.

**Recommend (a)**, with the instruction carrying the ladder explicitly: *reuse an available template → else enlist an installed-but-not-enlisted one via `package.install` → else delegate authoring.* This widens the Researcher's mutation surface by one reviewed proposal type; both options keep every mutation behind user review, so neither weakens `REQ-REVIEW-001`.

**Do not** attempt cross-project template use without enlisting: the project lockfile is load-bearing for reproducibility (dev/81/82) and must keep meaning "what this project declares".

### 3.4 Fix D5 — the draft delegation gets the correction rounds every other lane has

Restructure `_mint_package_draft_from_delegate` (`:5810-5855`) around the loop `node.content.generate` already uses (`:4292-4310`):

```python
for round_index in range(1 + _DRAFT_CORRECTION_ROUNDS):     # cap it, like plans
    params, parse_error = _extract_draft_params_verbose(child_text)
    if params is not None:
        status, text, part = _mint_package_draft_apply(...)   # dev/91-extended; do not fork it
        if status != "refused":
            return part, text
        parse_error = text                                    # build-service refusal
    child_text = re-delegate(inputs | {"previousAttempt": child_text[:6000],
                                       "validationError": parse_error[:2000]})
```

Three requirements fall out:

1. **`_extract_draft_params` must explain itself.** It returns bare `None` today (`:5701`). It needs a verbose sibling returning `(params | None, error_text)` — the shape `_parse_dataflow_plan_verbose` (`content.py:350`) and `_available_template` already use. Without a real error there is nothing to correct against.
2. **A run that produced nothing must not report `ok`.** `make_delegation_part` (`content.py:861`) must take the caller's outcome: `ok` only when a proposal was minted, `failed` with the real reason and rounds spent otherwise.
3. **The parent must be told "fix the draft", never "rename the package".** The current text invites exactly the duplicate-id retry that happened. After the cap, name the parse error, say the *same* package id should be retried or the attempt abandoned, and — when a same-purpose package already exists — point at the enlist lane from §3.3.

Also persist the parse error into the transcript beside the bounded reply (`:5460-5480`), so the next person debugging this has more than a reply truncated at 2000 chars. And keep dev/90 A12's note reconciliation (`_reconcile_draft_notes`, `:5781`, called at `:5846`) applying to whichever round finally parses.

### 3.5 Fix D3's duplicate roster — retire the client list

The frontend's `installedTemplates` fragment exists to give the planner vocabulary, but the server appends an authoritative roster to the same run (`:4728-4734`), gated on exactly the grants that need it. Two lists, two spellings, two scopes — and the client's can name templates the server does not offer, the direction that manufactures refusals. It caused the Dataflow Builder loop and has no remaining job.

**Recommendation: drop the `installedTemplates` producer** (`agentRunContext.ts:125-130` → `return null`), leaving the server block as the run's only roster. Once `canonical_template_id` accepts the versioned form, keeping the client list is *safe* but still redundant and still contradictory — it advertises palette templates that are not project-available, exactly the rows that lied in this incident. Removing the producer keeps the declared read on the manifest (no manifest churn) and single-sources the roster. If a reviewer prefers to keep it, the minimum bar is: emit the unversioned id, filter to project-available templates, and use the *same heading* as the server block — at which point it is the server block, computed worse.

---

## 4. Data and State Handling

**Source of truth for availability:** `packages_services.available_templates(user_key, project_id)` — unchanged, and still the only manifest reader. Every agent-side check goes through `resolve_template`, so the agents module keeps owning no template knowledge (`ADR-AG-007`), and the alias table lives with the rest of that knowledge.

**Source of truth for ids on disk:** the seeded package `manifest.json`. `integrity.json` becomes the completeness oracle for the health check — it is already written at seed time and is otherwise dead weight for store packages.

**Canonical form:** the unversioned `<packageId>/<templateId>`, as `available_templates` documents (`packages/services.py:229-232`) and as pinned spec `nodeType`s already use. Versioned and legacy-enum forms are *accepted inputs*, never stored outputs. Conversion happens exactly once, at the parse boundary.

**Two scopes, named explicitly.** The store (what the user has installed) and the project lockfile (what this project declares) are different sets, and conflating them is what made D4 invisible. After this change the roster names both, and only the lockfile-scoped set is instantiable. Enlisting moves a package from the second scope to the first through the reviewed `package.install` path — never implicitly.

**State after user actions.**
- *Plan proposed* → the stored proposal holds canonical `nodeType`s; the shape digest pins that canonical form.
- *Plan applied* → canonical compared to canonical against live availability; a package genuinely uninstalled between propose and apply still correctly yields `stale`.
- *Package enlisted* → the next run's roster reflects it; availability is re-checked at mint and again at apply, so an install applied mid-run cannot produce a stale refusal.
- *Seeding* → the swap is atomic, so no request observes a partial store; `.seed-state.json` is written only after a successful swap.
- *Draft correction rounds* → each round's attempt and error are transcript state; only the round that parses mints a proposal, so a retry can never produce two proposals or two packages.

**Degraded-registry states.** Today `ManifestError` → `continue` → an under-populated roster indistinguishable from a legitimately small project. After this change `available_templates` logs at WARNING with the package path and reason and exposes the skip to callers (prefer a companion `available_templates_report()` so the hot path keeps its list-return shape). `resolve_template` uses it to choose its refusal: *"the built-in template package is unreadable — the server is repairing it; retry"* versus the ordinary *"not an available template"*. The §3.1(c) self-heal means the repair happens on the next package request rather than needing a restart.

**Avoiding races:** the seed lock removes seeder-vs-seeder; the atomic swap removes seeder-vs-reader. No new in-process cache, so nothing new can go stale.

---

## 5. UI and UX Requirements

Agent-facing surfaces mostly; visible chrome barely changes.

- **The "Plan not proposable" card must be true and actionable.** Unknown id → name the id, the accepted spellings, and the roster. Degraded registry → say the package store is unreadable and being repaired. Never blame an id for a broken install.
- **One roster heading per run.** After §3.5 the model sees exactly "Available node templates" (with its two sections). No prompt should ever again contain two similarly-named lists.
- **The palette and the agents must agree.** While the store was truncated, the palette still rendered 12 built-in kinds from a registry snapshot while the server offered 2 — a user could drag a `data-loading` node the planner swore did not exist. The self-heal closes this; no palette change and no new banner are proposed.
- **The enlist proposal reuses the existing package-install dialog** (permissions, dependencies, conflicts) — no new review surface, and the Researcher's chat must say where the review awaits, per the standing "never claim it exists before the user applies" rule.
- **Delegation cards must not read "ok" when nothing was produced.** The card is the user's only window into a delegated failure.
- **No latency regression:** the health check *replaces* an unconditional `rmtree` + 12-file `copytree` on every package request, so `GET /api/packages` gets measurably faster. No new visual states, no layout shift, no flicker.
- **Accessibility:** unchanged surfaces; the error card and install dialog keep their existing semantics.

---

## 6. Edge Cases

**Seeding / store health**
1. Concurrent `GET /api/packages` + `GET /api/packages/catalog` on canvas mount (the actual trigger) — never expose a partial store.
2. The Werkzeug reloader's two processes seeding simultaneously — cross-process `flock` required; a thread lock alone is insufficient.
3. Process killed mid-swap — leftover staging/trash dirs swept (extend `_purge_stale_staging`, `seed.py:155-159`) and never mistaken for a package (`PACKAGE_DIR_RE` excludes dot-prefixed names — verify).
4. Staging and destination on different filesystems → `os.replace` raises; fall back to today's behavior with a loud log rather than losing the package.
5. `integrity.json` missing or unparseable → unhealthy, re-seed.
6. Fixture catalog absent (production build) → seeder returns `[]`; the health check must not then delete a working store.
7. A legitimately uninstalled non-built-in package must not be resurrected — the tombstone path stays untouched.
8. Read-only / permission-denied package dir → log, never crash the request.
9. **The truncated state must be repaired without manual `rm -rf`.** It is currently healthy, so reproduce it deliberately (delete `manifest.json`) and assert the next request restores it.

**Template id spellings**
10. `curio.builtin/data-loading@1` (versioned, from the client list, `graphContext`, or the runtime's own proposal previews) → accepted.
11. `DATA_LOADING` (legacy enum) → accepted via alias.
12. `curio.builtin/data-loading@99` — a major that is not installed. Decide deliberately: strip-and-accept (A14's `node.create` behavior; the registry is unversioned anyway) versus refuse-with-"major not installed". **Recommend strip-and-accept for parity**, with the refusal staying honest when the family itself is absent.
13. Bare `data-loading` with no package id → still refused as ambiguous, and the message must say why. Existing tests depend on this (`test_routes.py:4493`, `:4535`).
14. Case variants (`Curio.Builtin/Data-Loading`) → recommend **no** case folding for the canonical part (ids are case-sensitive by contract) while legacy aliases match exactly on the documented uppercase names. Document the choice.
15. Whitespace/quotes → `content.py:408` already strips; keep that before canonicalization.
16. A plan mixing spellings across nodes (likely from a confused model) → each canonicalizes independently; the plan succeeds.
17. Two available templates colliding on the unversioned id across majors → `available_templates` already dedupes highest-major-first (`packages/services.py:265-267`); the resolver inherits it.
18. **A proposal minted before this change, applied after.** Its stored `nodeType` may be a raw versioned string whose digest was computed over that string. Canonicalize only at *parse*, and have the apply checks canonicalize the **comparison**, not the stored value — the in-flight proposal still applies and its digest keeps hashing what it hashed at mint. Test this.
19. A non-authorable template in a plan → must be **allowed** (placeholder now, content from Solve). Explicit test.
20. Genuinely empty roster → the block is omitted (`:4807`) and every plan is refused; the refusal must then say the store is empty, not that the id is wrong.
21. **Removal-only plans must keep working** — zero nodes means the availability loop never runs (that is why the 12:08 plan succeeded). Regression-test it so the refactor cannot break the one path that works.

**Reuse door (D4)**
22. Installed-but-not-enlisted → listed in section two only; `node.create` on it still refuses, with a message naming `package.install`.
23. Nothing installed and nothing enlisted → both sections empty; the ladder falls through to authoring, and the refusal says the store has no candidate.
24. The same template id in two not-enlisted packages → list both with their dirNames; `package.install` takes a dirName, so this stays unambiguous.
25. `package.install` for a built-in → already refused by contract (`tools.py:216-217`); keep built-ins out of section two entirely.
26. `package.install` for an already-enlisted package → no-op refusal pointing at the usable list.
27. A package enlisted mid-run → the subsequent `node.create` must succeed, not refuse on a stale roster.
28. Enlisting resurrects a tombstoned package (`curio.postits@1` and `curio.weather.notes@1` have both been tombstoned and reinstalled during this investigation) → the seed tombstone must not fight a user-approved install.

**Draft correction rounds (D5)**
29. Unparseable then parseable on round 2 → one proposal, no duplicate package, both attempts in the transcript.
30. Unparseable through the cap → delegation reports `failed` with the real parse error; the parent is told to retry the same id or stop, never to rename.
31. Parses but the build service refuses → same loop with the build refusal as the fed-back error; classify and break on refusals that cannot improve (e.g. a permissions denial).
32. Empty reply / timeout / child error → no rounds (nothing to correct), `failed` immediately, honest reason.
33. The delegate changes the package id between rounds → a correction failure, not a new package; pin the id from round 1.
34. Parent lacks `package.draft.apply` → unchanged existing message (`:5827-5831`); no rounds spent.
35. Rounds must respect the run's budgets (`MAX_TOOL_ROUNDS`, `runsPerDay`, `maxOutputTokens: 4096`) and surface the rounds spent.
36. dev/90 A12's note reconciliation still applies on the round that parses.
37. **dev/91 interaction:** `_mint_package_draft_apply` now emits backend provenance and the trust-edge card. The retry loop must call it unchanged — a backend-bearing draft that fails its probe is a *refusal*, and refusals that cannot improve must break rather than loop.

**Roster/duplication**
38. `installedTemplates` returning `null` after §3.5 → `composeAgentRunContext` must still compose its other fragments (`agentRunContext.ts:172-176` filters nulls; confirm nothing assumes a fragment count).
39. Other agents declaring `installedTemplates` (`agent.package-recommendation`, `builtin.py:259`) — removing the producer changes their context too. Confirm each also receives the server block; it is gated on `node.create`/`dataflow.plan.write`, and Package Recommendation holds **neither** (`builtin.py:260-261`: `packages.catalog`, `packages.resolve`, `package.install`, `dataflow.read`), so it would lose its roster entirely. **Resolve this before removing the producer** — either extend the server block's gate to `package.install`, or keep the producer for that agent, repaired per §3.5's minimum bar.

---

## 7. Testing Strategy

### Unit — packages domain
- `canonical_template_id`: unversioned → itself; `pkg/tpl@1` → `pkg/tpl`; every `NodeType` legacy name → its canonical value; bare slug unchanged (so the resolver refuses it); whitespace stripped; empty/non-str handled.
- Alias-table completeness, **parametrized over the 11 `constants.ts` `NodeType` members**, so a new built-in kind cannot be added on the frontend without the backend learning its legacy name. Read them from the TS source or from a checked-in fixture regenerated by a script — either way, drift must fail CI.
- `resolve_template`: found unversioned / versioned / via alias / absent / absent-because-degraded (distinct messages); `require_authorable=True` refuses a non-authorable template and `False` accepts it.
- `available_templates` with an unreadable package: returns the readable ones, **logs a warning**, and reports the skip (assert on `caplog`).
- `_package_is_healthy`: complete → True; missing `manifest.json` → False; missing a file named in `integrity.json` → False; malformed `integrity.json` → False.
- `installed_templates_not_in_project`: excludes built-ins, excludes enlisted packages, includes the store-only ones with their dirNames.

### Integration — seeding
- **Regression for the observed corruption:** a store dir holding only `integrity.json` → `_ensure_user_seeded` restores it fully and `available_templates` returns all 12 built-ins.
- **Concurrency:** N threads seeding one user while M threads read `available_templates`; no reader ever sees a partial store (every read yields a complete tree), and the final store is complete. This is the test that would have caught D1.
- Two processes racing the swap → still complete.
- Crash mid-swap (monkeypatch `os.replace` to raise after the first move) → the next call repairs; no orphan dirs survive the sweep.
- Healthy store + unchanged fixture → **no re-seed** (assert `rmtree`/`copytree` are not called). The per-request-destruction regression must be locked out.
- Uninstall tombstones still honored.

### Integration — plans (D3)
- **The screenshot, replayed:** a `dataflowPlan` whose nodes use `curio.builtin/data-loading@1` and `curio.builtin/vis-vega@1` → **proposed**, with the stored proposal carrying unversioned ids. Today this refuses; it is the primary regression test and the coverage gap that remains real on this branch (`grep` finds one versioned `nodeType` in `test_routes.py`, at `:3441`, and it is a spec fixture, never a plan input).
- **The canvas's own type:** a plan naming `curio.postits/post-it-note@1` — the versioned id the runtime itself printed in its 12:08 proposal preview — → proposed.
- `DATA_LOADING` → proposed (or, if the alias is deliberately rejected for plans, a message naming the canonical id; test the decision, not both).
- A genuinely unavailable id → refused, with the roster-pointing message.
- Apply after propose for versioned/aliased/legacy-stored plans, per-node and whole-plan; **edge case 18** does not spuriously go `stale`.
- A non-authorable template in a plan → proposed (edge case 19).
- **A removal-only plan still applies** (edge case 21).
- Degraded registry → the refusal names the unreadable package, not the id.
- `_available_templates_block`: names both tools, states the versioned form is accepted, includes non-authorable templates for a plan-capable run, logs truncation past 60.
- `node.create` parity: all three spellings still work after the refactor (guards A14 while its implementation moves).

### Integration — reuse door (D4)
- **Regression for the Researcher's failure:** a project whose lockfile lacks `curio.notes@1` while the store has it → the roster contains a non-empty "installed but not enlisted" section naming `curio.notes/note-surface`. Today the roster is silent, which is what produced "there is no installed notes template on your canvas".
- `node.create` on a not-enlisted template → refused with a message naming `package.install`.
- `package.install` proposed and applied → the template moves to the usable list and the follow-up `node.create` succeeds.
- Built-ins never appear in section two; `package.install` for one is refused.
- `agent.researcher`'s granted tools include `package.install` (`test_builtin.py` roster assertions updated).
- Both sections together respect the 60-entry cap and log truncation.

### Integration — draft correction rounds (D5)
- **Regression for the duplicate package:** a delegate whose first reply is unparseable and whose second is valid → exactly **one** proposal, one package id, no second authoring attempt. This is the test that would have caught `curio.notes` → `curio.postits`.
- Unparseable through the cap → the delegation part reports `failed`, the summary carries the real parse error, no proposal is minted.
- A delegate renaming the package between rounds → correction failure, not a new package (edge case 33).
- A build-service refusal fed back → retried once, then reported honestly; a non-improvable refusal breaks immediately.
- **dev/91 guard:** a backend-bearing draft whose probe fails → refused, not looped, and the trust-edge card/provenance behavior from dev/91 commit 4 is unchanged (assert the existing dev/91 DOD tests still pass).
- `make_delegation_part` unit test: child ran `ok` + produced nothing → part reports `failed`.
- dev/90 A12 note reconciliation still applies on the round that parses.
- The parse error is persisted in the transcript.

### Frontend
- `agentRunContext.test.ts:143` — update the `"Installed node templates:"` expectation to match §3.5 and assert the other fragments still compose when it returns null.
- If the producer is kept for Package Recommendation (edge case 39): assert it emits unversioned, project-available ids only.

### Manual verification (required before this is called done)
Restart the backend, open the canvas, confirm the roster shows 13 usable templates plus `curio.notes/note-surface` under "installed but not enlisted", then re-run the exact failing prompt — *"Plan a dataflow that explores my data over time: create a list with random values to plot"* — and confirm a plan is proposed on the **first** round. Then ask the Researcher a fresh weather question and confirm it enlists or reuses rather than authoring a fifth notes package. Both bugs were found in live runs; they get signed off in live runs.

---

## 8. Acceptance Criteria

**Store health (D1)**
1. `GET /api/packages` no longer deletes and re-copies the built-in package: a healthy, unchanged store performs zero writes.
2. Concurrent package requests can never expose a partial or missing built-in package; the concurrency test passes repeatedly.
3. A truncated built-in package is repaired automatically on the next package request, logged at WARNING, with no manual filesystem intervention.
4. `available_templates` for the live project returns the full set (12 built-in + enlisted packages) on every request, not intermittently.

**Vocabulary (D3)**
5. A `dataflowPlan` using versioned ids (`curio.builtin/data-loading@1`, `curio.postits/post-it-note@1`) is **proposed**, not refused.
6. A plan using a legacy enum name resolves per the §6.11 decision and never yields "not an available template" for a template that exists.
7. Stored proposals carry canonical unversioned ids regardless of what the model sent.
8. Both apply paths accept exactly what the mint accepted — no spelling is proposable-but-unappliable — and proposals minted before the change still apply.
9. `node.create` accepts every spelling it accepted before (A14 preserved).
10. Exactly one code path decides template availability; `grep` finds no second `t["id"] == node_type` comparison in the agents module.
11. Removal-only plans still apply.

**Truthfulness (D2)**
12. A degraded store produces a refusal naming the unreadable package, never claiming a real template is unavailable.
13. `available_templates` logs a warning whenever it skips a package.
14. The roster names the plan tool as well as `node.create`, states that the versioned form is accepted, and lists every template a plan may use.

**Reuse door (D4)**
15. The roster distinguishes "usable in this project" from "installed but not enlisted"; a template the user has installed is never invisible.
16. The Researcher can enlist an installed package through the reviewed `package.install` lane; authoring is reachable only after that option is exhausted.
17. Re-asking "what's the weather in Paris?" against a store that already holds a notes package produces **zero** new packages.
18. A `node.create` refusal for a not-enlisted template names the enlist lane instead of implying the template does not exist.

**Draft correction rounds (D5)**
19. An unparseable delegate draft triggers capped correction rounds with the real error fed back to the same delegate; one run can no longer produce two differently-named packages.
20. A delegation that minted nothing reports `failed` with the actual reason; no card reads "ok" for a run that produced nothing.
21. The post-cap message tells the parent to fix or abandon the draft — never to rename — and points at the enlist lane when a same-purpose package exists.
22. The parse/validation error is recoverable from the transcript afterwards.

**End to end**
23. The exact prompt from the screenshot yields a proposed plan on the first round, in a live app, with no correction rounds spent on template ids.
24. Each run carries one roster under one heading.
25. dev/91's backend-sandbox behavior is unchanged: its DOD suites pass untouched.
26. Full backend `test_agents` + `test_packages` suites and the frontend jest suite pass.

---

## 9. Recommended Commit Breakdown

**Commit 1 — Shared template-id resolver + degradation reporting, with tests**
`canonical_template_id`, `resolve_template`, the legacy alias table, `installed_templates_not_in_project`, the enum-drift test, `available_templates` logging/report. Pure addition; nothing calls it yet.

**Commit 2 — Atomic, serialized, self-healing package seeding**
Staging + `os.replace` swap, the per-(user, package) dual lock, `_package_is_healthy`, removal of the unconditional built-in force, staging sweep. Ships with the truncated-store and concurrency tests. **Land this first if the series must be split in time** — it is the intermittent outage.

**Commit 3 — Canonicalize plan nodeTypes at the boundary; route every check through the resolver**
`content.py:408` canonicalization; `_mint_dataflow_plan`, both apply paths, and `_available_template` all through `resolve_template` with an explicit `require_authorable`; the legacy-proposal digest-stability guard; the removal-only regression. Ships with the versioned/aliased plan-mint and apply tests.

**Commit 4 — One honest roster**
`_available_templates_block` header/scope/truncation fix, `orchestration_instruction.txt` wording, retire (or repair) the frontend `installedTemplates` producer after resolving edge case 39, frontend test update.

**Commit 5 — Correction rounds for delegated package drafts; honest delegation status**
`_extract_draft_params_verbose`, the capped retry loop, id-pinning across rounds, `make_delegation_part` reporting the outcome, the persisted parse error. Ships with the duplicate-package regression and the dev/91 no-regression guard. Independent of commits 1–4.

**Commit 6 — The reuse ladder: roster sections + the Researcher's enlist lane**
The two-section roster, `package.install` granted to `agent.researcher`, the reuse → enlist → author ladder in the instruction. Ships with the "installed but not enlisted" roster test and the enlist-then-create integration test.

**Commit 7 — Memo amendment + docs**
Amend this memo with root causes, the A14 recurrence, and the §6.12 / §6.14 decisions; note in `docs/` that template-id canonicalization has exactly one home; restate dev/90 A14's standing lesson with its second data point.

Each commit is independently revertable. Commits 2 and 3 fix different defects behind one symptom — keep them apart so the history says so. Commits 5 and 6 address the Researcher's failure and can land before or after the plan work: 5 stops the duplicate-package bleeding, 6 removes the reason it starts.

---

## 10. Engineering Quality Checklist

- [ ] No duplicated business logic: one canonicalizer, one availability resolver; the four ad-hoc comparisons (`:1385`, `:1718`, `:2554`, `:5098`) collapse into it.
- [ ] Template knowledge stays in the packages domain (`ADR-AG-007`); the agents module gains none.
- [ ] Locking and atomic-swap logic reuses the established `spec_write_lock` / installer patterns instead of a third bespoke `flock` block.
- [ ] Types explicit: `canonical_template_id(str) -> str`; `resolve_template(...) -> tuple[dict | None, str]`, matching the existing `_available_template` contract.
- [ ] Conversion happens once, at the parse boundary; canonical ids are what get stored and pinned.
- [ ] Digest stability preserved for proposals minted before the change (edge case 18), verified by test rather than inspection.
- [ ] Failures are loud: no bare `except: continue` left on the manifest-read path; every skip logs the package and the reason.
- [ ] Refusal messages name the accepted spellings and distinguish "unknown id" from "degraded registry" from "installed but not enlisted" — a weak local model must be able to self-correct from the message alone.
- [ ] Every mutation lane that parses model output has capped correction rounds with the real error fed back; the draft path reuses the established loop rather than a third bespoke one.
- [ ] No status field reports success for an operation that produced nothing.
- [ ] Reuse-first has a reachable door at every rung: an agent is never told to reuse something it cannot obtain, and authoring is the last resort.
- [ ] Mutation-surface changes stay behind user review (`REQ-REVIEW-001`): granting `package.install` adds a reviewed proposal type, never a silent install.
- [ ] No silent caps: roster truncation is logged, and both roster sections are bounded together.
- [ ] Request-path cost does not regress — the health check replaces an unconditional `rmtree` + `copytree`.
- [ ] Concurrency is tested, not argued: the seeding race is the defect that took the app down.
- [ ] dev/91's backend contract, probe gate, and provenance are untouched; its DOD suites pass unchanged.
- [ ] The plan path and the `node.create` path behave identically on every spelling, and their one intended difference (`require_authorable`) is explicit at both call sites.
- [ ] Manual live verification of both original prompts recorded in the amendment.

---

## Amendment A1 — commit 2 implemented (atomic, serialized, self-healing seeding)

Approved 2026-08-21 together with option (a) for §3.3 (grant `agent.researcher` the `package.install` tool). Commit 2 landed first, as the memo recommended, because D1 is the intermittent outage.

**What shipped**
- `utk_curio/backend/app/common/file_locks.py` (new) — the two-layer lock (keyed `threading.Lock` + POSIX `flock` / Windows `msvcrt.locking`), extracted from `projects/storage.py` so there is one implementation rather than a second bespoke `flock` block. `spec_write_lock` now delegates to it; its Windows-fallback tests were repointed at the new home.
- `packages/seed.py` — a seeding pass holds an exclusive per-user lock (`<user>/packages/.seed.lock`, namespace `package-seed`); each package is placed by `_swap_in_package` (build in a `.seed-staging-*` sibling inside the package store, move the old tree aside, rename the new one in, restore on failure); `_package_is_healthy` gates a built-in self-heal; `_sweep_seed_staging` clears leftovers from a killed swap.
- The unconditional `if force or is_builtin` force is gone. The decision is now `force` → `builtin-missing` → `builtin-unhealthy` → the ordinary `should_seed` mtime check.

**Deviations from §3.1, recorded**

1. **A missing `integrity.json` is not treated as unhealthy** (§3.1c said it should be). A package that ships without one would then be re-seeded on *every* request — reinstating precisely the per-request destruction this commit removes. Health is therefore: the manifest loads, and *if* `integrity.json` is present and parseable, every file it names exists. The observed corruption is still caught, by the manifest gate. A corrupt or non-dict `integrity.json` is unhealthy.
2. **`builtin-missing` is a separate branch from `builtin-unhealthy`.** Folding "absent" into "unhealthy" logged a first run as corruption. Splitting them keeps the log honest and states the no-opt-out guarantee explicitly: a missing built-in is restored regardless of any tombstone.
3. **No cross-filesystem fallback was needed** (§6.4). Staging lives *inside* the destination directory, so both renames are same-filesystem by construction. The prefix `.seed-staging-` also matches neither `PACKAGE_DIR_RE` (so `list_user_packageages` ignores it) nor the installer's `.staging-*` / `.stage-*` sweep patterns (so a concurrent install cannot delete a half-built tree).
4. **The atomicity claim is narrower than the memo's wording, and the tests say so.** POSIX `rename` cannot replace a non-empty directory, so the swap is two renames and the package is *momentarily absent* between them. What is fully eliminated is the **partial** tree: a reader can never see a package present-but-unreadable, which is the state that persisted forever under the old path. The absence is microseconds long, occurs only on a real refresh, and self-corrects. **Follow-up (new):** readers that must not observe even that gap should take the seed lock, exactly as dev/92's `target_locks` made invocation reads wait out a promote — worth doing when `available_templates` is touched in commit 1/3, since the seed lock is a leaf lock and cannot deadlock.

**Tests** — `test_seed.py` grows 8 cases (16 total in the file): no re-copy of a healthy store; self-heal from the observed truncation (a directory holding only `integrity.json`); self-heal when a file `integrity.json` names is missing; a package with no `integrity.json` is left alone; built-in restored despite a stray tombstone; a failed swap keeps the previous tree; staging leftovers swept and never listed as a package; and 8 seeder threads racing 8 reader threads with `CURIO_RESEED_PACKAGES` forcing real work on every pass.

**Teeth verified, not assumed.** With the old swap reinstated, `test_concurrent_passes_never_expose_a_broken_store` and `test_failed_swap_keeps_the_previous_tree` fail; with the old `force or is_builtin` reinstated, `test_healthy_builtin_is_not_recopied` and `test_builtin_without_integrity_file_is_left_alone` fail. Both were confirmed by temporarily patching the implementation and restoring it.

A note the concurrency test earned: its first two drafts reported false failures because the *checker* was racy — `iterdir` then read, and later an existence re-check that a subsequent swap had already satisfied. It now pins the directory's **inode** across the read, so only a tree that stayed the same inode and still could not be read counts as broken. A concurrency assertion needs the same scrutiny as the code it guards.

**Verification** — `test_packages` + `test_projects`: **594 passed**, 4 skipped. Full backend suite: **1628 passed**, 12 skipped, 141 errors, all in `test_frontend/test_workflows.py`. Those errors are **pre-existing**, confirmed by running the same suite in a throwaway worktree at clean `53b33f37`: 1620 passed, 12 skipped, **the same 141 errors**. The 1628 − 1620 = 8 difference is exactly this commit's new tests, and that file passes when run on its own (30 passed, 1 skipped) — a whole-suite fixture interaction that predates this work.

Also checked, since the change adds files under the package store: `RELOADER_EXCLUDE_PATTERNS` already covers `*/.curio/*` (`backend/server.py:25-27`), so neither `.seed.lock` (truncated on every pass) nor the `.seed-staging-*` trees can trip the dev-server reloader — the failure mode `_purge_stale_staging` was written for.

**Still open for the rest of the series:** the `curio.notes@1` package installed in the live store remains invisible to project `a9a1afc7` (D4), and the plan mint still refuses `curio.builtin/data-loading@1` (D3). Commit 2 fixes neither — it stops the store from silently losing its vocabulary underneath them.

---

## Amendment A2 — commit 6 implemented (the reuse ladder)

Landed after commit 2 (`aa6f5c95`), with §3.3 **option (a)** as approved: `agent.researcher` gains the `package.install` tool rather than a delegation to Package Recommendation.

**The blocker the memo did not see.** §3.3 assumed granting the tool was enough. It was not: `_mint_package_install` validates the proposed dirName against `agent_catalog_overview`, which enumerated **only the committed catalog** (`<repo>/packages/`) — so `curio.notes@1`, an *agent-authored* package that lives only in the user's store, was refused as *"not in the Nodes Catalog"*. The middle rung would have been a door painted on a wall. Two facts made the fix small: `installed` in that overview already means "in the CURRENT project's lockfile" (dev/84), not "in the store"; and `install_to_project` is already documented as *"add to the lockfile; install to user store if missing"* — precisely the enlist operation, and it already no-ops the copy when the store has it. So `agent_catalog_overview` now enumerates the committed catalog **plus** the user's store (a store manifest winning on a dirName collision, since that is the copy an install would enlist), and the rest of the lane worked unchanged.

**What shipped**
- `packages/services.py`: `installed_templates_not_in_project(user_key, project_id)` — the complement of `available_templates`, each row carrying the `dirName` a `package.install` takes; `_template_entry` extracted so both listings emit one row shape from one manifest walk; `agent_catalog_overview` widened as above.
- `agents/services.py`: `_available_templates_block` now states that a **plan** nodeType is also drawn from the list and that the versioned form is accepted (part of commit 4's remit, taken early because the second section needed a coherent header), and logs roster truncation instead of silently dropping entries. New `_enlistable_templates_block` composes the "Installed but NOT enlisted in this project" section, appended **only** when the run holds `package.install` — a section naming a door the model cannot open is how this failure started. A module logger was added (`agents/services.py` had none).
- `agents/builtin.py`: `package.install` granted to `agent.researcher`.
- `researcher_notes_instruction.txt`: the doctrine is now three numbered rungs — **REUSE** an available template → **ENLIST** an installed-but-not-enlisted package via `package.install` → **AUTHOR** by delegation — with "authoring is the LAST resort" and "never author a package whose job an already-installed one does" stated in the prompt.

**Verified against the live project** (guest / `a9a1afc7`), not just in fixtures: `installed_templates_not_in_project` returns `curio.notes/note-surface (curio.notes@1)` plus the seven `curio.weather` templates; the composed block names each with its package; `agent_catalog_overview` now lists `curio.notes@1` with `installed: False`, i.e. proposable. And because dev/60 makes built-in **roster bytes** authoritative over the materialized store copy, the live app picks both up without re-materializing: `_resolve_definition` reports the new six-tool list, `resolve_grants` grants `package.install`, and the resolved instruction carries the ladder.

**Tests** — 6 new in `test_packages/test_available_templates.py` (store-only rows carry their dirName; empty when everything is enlisted; unreadable store package skipped; row shape matches `available_templates` plus `dirName`; a store-only package is proposable; an enlisted one reads as `installed`) and a new `TestReuseLadder` class in `test_agents/test_routes.py` (the roster offers the enlistable package with its dirName and the do-not-duplicate instruction; an enlisted package leaves the not-enlisted section; **enlist-then-create end to end** — the store-only package is proposable, applying enlists it, and the template becomes instantiable; and a run without the grant sees no enlist section). Two existing `TestResearcher` assertions were updated: the exact tool list, and the instruction-content test, which now also pins the ladder.

**A test-authoring note:** the first draft of "an enlisted package leaves the section" asserted the *section title* was absent — and failed, because the **instruction** now names that section by title. Negative assertions about a composed prompt have to key on something only the roster emits; it now asserts the absence of the `(package curio.notes@1)` dirName suffix.

**Verification** — `test_agents` + `test_packages` + `test_projects`: **1347 passed**, 4 skipped. (An earlier run of mine reported 3 errors in `test_agents/test_retention.py`; that was my own `-p no:logging` flag removing the plugin that provides `caplog`, not a regression — they pass with the flag off.)

**Still open:** D3 (the plan mint refuses `curio.builtin/data-loading@1`) and D2's degradation reporting — commits 1, 3, 4, 5, 7.

---

## Amendment A3 — commits 1 and 3 implemented (D3 closed)

`307fd112` (commit 1, pure addition) and commit 3 (the wiring). **The reported loop is fixed.**

**Commit 1 — one canonicaliser, one gate, and a store that admits when it is degraded.**
- `canonical_template_id(node_type) -> str` — shape only, no I/O, so it can run at the parse boundary. Versioned → strips exactly a trailing `@<major>`; legacy enum → `curio.builtin/<lower-kebab>`; anything else unchanged, which deliberately preserves the two refusals that should stay (a bare slug names no package; ids are case-sensitive).
- `resolve_template(...) -> (entry | None, error)` — the one availability gate, returning the canonical row so callers pin the canonical id rather than what the model typed. `require_authorable` is the single *intended* difference between callers and is now explicit at both: `node.create` writes content and needs it; a plan places a typed placeholder and does not.
- `available_templates_report(...) -> {"templates", "skipped"}` — `available_templates` delegates to it and keeps its exact list-return shape; every skipped package is logged at WARNING, and `resolve_template` uses the skip list to say *"the package store is degraded, `<pkg>` could not be read, report this"* instead of blaming the id (D2).

**Deviation from §3.2, recorded:** the legacy aliases are **derived, not tabulated**. Every `NodeType` member is its template id upper-snake-cased, so the rule cannot go stale the way a hand-maintained table would, and it covers built-in templates that never got an enum member (`spatial-join`) for free. A bogus ALL-CAPS token maps to a canonical id that simply is not available and refuses normally. The drift guard the memo asked for is kept but pointed at the real invariant: the test **parses `constants.ts`** and asserts every member round-trips through the derivation to its declared value, so a frontend member that breaks the rule fails in CI.

**Commit 3 — canonicalise at the boundary, then route every check through the gate.**
- `content.py` canonicalises `nodeType` where a plan is first read. This is the load-bearing choice: the stored proposal, its pinned shape digest, and both apply-time re-checks then compare canonical to canonical *by construction*.
- The plan mint calls `resolve_template(require_authorable=False)`; `_available_template` becomes a thin wrapper calling it with `require_authorable=True`, so the A14 tolerance that lived only on the `node.create` path is now shared by definition rather than by duplication.
- Both apply paths canonicalise the **comparison, not the stored value** (edge case 18) — a proposal minted before this change holds a raw versioned string whose digest was computed over exactly that string, so rewriting it would mark in-flight proposals stale on deploy day.

**Verified against the live project.** The screenshot's plan — `curio.builtin/data-loading@1`, `DATA_LOADING`, and `curio.postits/post-it-note@1` (the canvas's own node type) in one plan — now parses with zero errors, canonicalises to `curio.builtin/data-loading` / `curio.postits/post-it-note`, and every node resolves to PROPOSE. Before this it was refused three ways.

**Tests** — 11 new in `test_available_templates.py` (25 in the file) and a new `TestPlanTemplateSpellings` class with 9: versioned proposable and stored canonical; legacy enum likewise; mixed spellings in one plan each canonicalise; a plan may use a **non-authorable** template; unknown types still refuse *and name the accepted spellings*; a bare slug stays ambiguous; a versioned plan applies end to end; a pre-change proposal holding a raw versioned id still applies; and the removal-only plan still applies.

**Teeth verified by A/B, not assumed.** Reverting the parse-boundary canonicalisation fails 4 of the 9; reverting the two apply-path comparisons fails exactly the pre-change-proposal test. The coverage gap the investigation found — *no test had ever fed a versioned `nodeType` into a `dataflowPlan`* — is closed.

**Verification** — full backend suite excluding the pre-existing-broken Playwright file: **1644 passed**, 8 skipped. `test_agents` + `test_packages` + `test_projects`: 1367 passed, 4 skipped.

**Remaining:** commit 4 (retire the duplicate client roster — needs edge case 39 resolved first: Package Recommendation declares `installedTemplates` but holds neither grant that triggers the server block), commit 5 (draft correction rounds, D5), commit 7 (docs).

---

## Amendment A4 — commits 4 and 5 implemented (D5 closed; one roster left standing)

**Commit 4 (`9876ae9d`) — the duplicate roster is retired, and the gate was widened to make that safe.** Edge case 39 is resolved as approved: extend the gate. It needed to go one step further than the memo assumed. The four built-ins declaring `installedTemplates` are dataflow-builder (`dataflow.plan.write` ✓), researcher (`node.create` ✓), package-recommendation (**neither**) and package-builder (**neither**) — so the gate is now the named `_ROSTER_GRANTS = {node.create, dataflow.plan.write, package.install, package.draft.apply}`, read as "any agent that can put a template on the canvas, plan one, enlist a package providing one, or author a new one". `package.draft.apply` earns it on the merits: an *authoring* agent especially needs to see what already exists, since not seeing it is how one question produced two near-identical note packages. The widening is bounded — an agent with none of those grants still gets no roster. `agentRunContext.ts`'s `installedTemplates` producer now returns `null` with the reason recorded; the declared read stays on every manifest, so there is no manifest churn.

Recorded while doing it: a **delegate** run composes only preamble + instruction with `tools=[]` (`delegation.run_delegate`, DEC-046), and the frontend context rides the *parent's* request — so the Package Builder never received either roster as a delegate. Its declared read only ever mattered for a direct attachment, where it holds `package.draft.apply`. The delegate's blindness to what already exists is D5's territory, not this commit's.

Its structural test walks `BUILTIN_AGENTS` and asserts every spec declaring `installedTemplates` holds a `_ROSTER_GRANTS` member, so a future built-in that declares the read without such a grant fails in CI rather than silently running context-blind.

**Commit 5 — D5: the delegated draft finally gets the correction rounds every other mutation lane had.**
- `_extract_draft_params_verbose` returns `(params | None, why_not)` with genuinely actionable errors: no JSON found at all, a decode error *plus* "if the reply was cut off mid-object, re-emit the COMPLETE build request" (the dominant weak-model failure — a long body with an embedded source file, truncated), or "parsed but is not a build request" naming the keys it did see. `_extract_draft_params` becomes a thin wrapper, so there is one extraction path.
- `_mint_package_draft_from_delegate` loops up to `1 + _DRAFT_CORRECTION_ROUNDS` (2, mirroring `_VALIDATE_CORRECTION_ROUNDS`), re-running **the same delegate** via a `_draft_corrector` closure with `previousAttempt` + `validationError` — the exact shape the node-content path has used since dev/67, so a delegate already taught self-correction there needs no new teaching. Every attempt is traced into `delegations`, so the rounds are visible in the transcript rather than being an invisible retry.
- **The package id is pinned** across rounds: a delegate that renames mid-correction is failing the correction, not authoring a new package. That is precisely the move that produced `curio.notes` then `curio.postits`.
- **Terminal refusals are not retried** (`_draft_refusal_is_correctable`): a policy or permission verdict is the build service's answer, not a typo, so retrying would spend the parent's rounds reaching the same refusal. A malformed manifest or a failed probe is retried.
- **The delegation card reports the outcome, not the child's run status.** Fixed at the caller rather than in `content.py`: `make_delegation_part` already takes a status and documents `ok`/`failed`; the defect was passing the child *run* status when nothing had been produced. Both call sites now pass the mint outcome.
- The give-up message names the real error, says to keep the same package id, and — closing the loop with commit 6 — says that if a package doing this job is already listed as installed, use it instead of authoring one.

**Tests** — the existing `test_unparseable_child_reply_is_recoverable_data` is updated (it pinned the old vague wording) to assert the real parse error, the anti-rename guardrail, and `card["status"] == "failed"`. New `TestDraftCorrectionRounds` (4): the duplicate-package regression (first reply cut off mid-object → corrected → **exactly one** proposal, one package, and the delegate demonstrably re-run with the real error); a rename mid-correction is refused and named; terminal-vs-correctable classification; and the verbose extractor's four failure shapes.

**Teeth verified by A/B:** setting `_DRAFT_CORRECTION_ROUNDS = 0` fails both loop tests; removing the honest-status line at a call site fails the delegation-card assertion.

**Verification** — full backend suite excluding the pre-existing-broken Playwright file: **1652 passed**, 8 skipped. Frontend `agentRunContext` suite: 10 passed, touched file tsc-clean.

**All five defects are now closed.** Remaining: commit 7 (docs) — and the two follow-ups this work surfaced: readers taking the seed lock to close the swap's rename gap (A1), and the Package Builder's delegate runs being blind to the existing roster.

---

## Appendix — evidence, re-verified on `feat/agentscatalog` @ `53b33f37`

| Claim | Evidence |
|---|---|
| Plan mint refuses what `node.create` accepts | live read-only run against project `a9a1afc7`: `curio.builtin/data-loading@1` → plan REFUSE / create OK; `curio.postits/post-it-note@1` → plan REFUSE / create OK; `curio.builtin/data-loading` → both OK |
| The refused id is the canvas's own | spec node `bcf229d9` is `curio.postits/post-it-note@1`; the runtime printed that exact string in its 12:08 proposal preview (session `3c7c236d…`) |
| Removal-only plans succeed | session `3c7c236d…` 12:08: `dataflow.plan.write` proposal "0 nodes, 0 edges, removes 2 nodes" → applied; the availability loop at `:1384-1392` never ran |
| Plan path is spelling-intolerant | `agents/services.py:1385` exact-match `available.get(...)`; same at apply `:1718`, `:2554`; the A14 tolerance exists only at `:5100-5107` |
| Helper existed, unused on plans | `_strip_type_version` `:1260-1264`, used for spec node types, never for plan `nodeType` |
| Two rosters, two spellings | server unversioned + authorable-only `:4796-4817` (gated `:4731`); client versioned + palette `agentRunContext.ts:125-130`, versioned per `packagesClient.ts:51,208` and `nodeRegistry.ts:6-13` |
| Third spelling | `frontend/src/constants.ts:13-30` — `NodeType.DATA_LOADING`, client-normalized by `aliasNormalize`, unknown to the backend |
| Store oscillated | `.seed-state.json` `seededAt` 11:19:32 (store = `integrity.json` only, 2 templates) → 11:35:59 (complete, 12) → 13:29:15 (complete, current); `ManifestError: missing manifest.json` reproduced at the truncated moment |
| Every request re-seeds the built-in | `routes.py:246,287,317,1198,1234` → `seed.py:207-209` (`if force or is_builtin`) → `:226-236` (`rmtree` then `copytree`, `OSError` swallowed) |
| Failure is silent | `packages/services.py:257-260` (`except (ManifestError, OSError): continue`); `agents/services.py:4802-4805`; no integrity verification for store packages |
| Researcher chose authoring over reuse | session `a4baf769…` turn 1: "Since there is no installed notes template on your canvas, I will request the creation of a new notes package" |
| Two authoring delegations in one run | same turn's `execution.delegations`: `3ebce8db…` then `6b1f8ad7…`, both `node.kind.author`, both `status: ok`; PB session turns 1/3 author `curio.notes` then `curio.postits` |
| Only the second minted a proposal | turn 1 content parts: `delegation` (summary "…returned no parseable package draft … refine the delegation inputs and try again", **status `ok`**), `proposal` (`package.draft.apply`, `curio.postits@1`), `delegation` ("reviewed package draft proposed") |
| An installed package is invisible to a project | store `curio.builtin@1, curio.notes@1, curio.postits@1, curio.weather@1`; lockfile `{curio.postits@1}`; available = 13, with `curio.notes/note-surface` **absent** |
| The Researcher cannot enlist one | `builtin.py:332-333` (no `package.install`), `:334` (no `agent.package-recommendation` delegate), `tools.py:206-219` + `builtin.py:260-261` (the lane belongs to Package Recommendation) |
| Four generations for one job | `.seed-state.json` tombstones `curio.postit@1` (2026-08-20 17:05) and `curio.weather.notes@1` (2026-08-21 11:35); store has held `curio.notes@1`, `curio.postits@1` too |
| No correction round for drafts | `:5836` returns on the first parse failure (`_extract_draft_params`, `:5701`, returns bare `None`); contrast `:4154` + `:4292-4310` and `:2095` + `:2173` |
| Delegation status ignores the outcome | `content.py:861` — `"status": "ok" if status == "ok" else "failed"`, where `status` is the child *run*'s |
| Transcript can't explain a failed draft | `services.py:5472` caps the persisted child reply at 2000 chars (parsing uses the full text); both stored drafts are exactly 2000 chars |
| dev/91 does not fix any of this | `git diff b5915198..53b33f37` touches `agents/services.py` (+51, in `_mint_package_draft_apply` and `_BUILD_REQUEST_CONTRACT`) and `packages/services.py` (+7, an entry-pin call); `seed.py`, `builtin.py`, `content.py`, `agentRunContext.ts` untouched |
| The A14 lesson was applied elsewhere | dev/91 `backend_policy.py` owns "the ONE grammar (A14: one value, one parser)" for backend declarations — the new subsystem learned it; the plan path still has not |
| Prior occurrence + standing lesson | `dev/90-prompt-driven-custom-node-looks-memo.md:224-233` (A14, commit `6f5360e2`): "every validator must accept both or the system WILL manufacture unfixable-looking refusals" |
