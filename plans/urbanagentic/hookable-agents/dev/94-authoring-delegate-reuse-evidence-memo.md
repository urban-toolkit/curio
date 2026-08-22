# dev/94 — The authoring delegate is told to check for duplicates with a tool it does not have

**Status: IMPLEMENTED (2026-08-22) — commits `21b2db3a` (1), `05bb5236` (2), + docs; DEC-063 minted; BL-P5-20260822-36. Both mechanisms A/B-verified; the deliberate non-goal (enforcement) is stated in §3.3 and in the DEC.**

Date: 2026-08-21
Branch / tree: `feat/agentscatalog` @ `a395f312` (dev/93 complete). Line numbers pinned to that commit.
Origin: dev/93's stated follow-up ("roster-aware delegate runs"), deliberately left out of that memo's scope. Investigation since has made the defect sharper than the follow-up note described, which is why it gets its own memo rather than an amendment.
Family: dev/90 A8 / dev/67-4 — "a DEC-046 child is structurally tool-less, so the runtime supplies the evidence its instruction depends on".

---

## 1. Problem Statement

### The contradiction

`utk_curio/llm-prompts/package_build_instruction.txt:3` opens the Package Builder's doctrine with this:

> "**Reuse first.** Before authoring anything, **read packages.catalog**: when an existing catalog or installed package already satisfies the need, say so — that is your whole answer, never a duplicate package. Author only when no catalog row fits, or the user explicitly asked for a new or extended package."

That is the right doctrine, and on the path it was written for it works: a user attaches a Package Builder directly, and it holds `packages.catalog` (`agents/builtin.py`: `('packages.catalog', 'packages.resolve', 'dataflow.read', 'package.draft.apply')`).

**On the delegate path it is unexecutable.** A depth-1 child runs structurally tool-less by design (DEC-046; `delegation.run_delegate` composes only `preamble + instruction`, pins `"tools": []`, and appends no tail instruction). So when the Researcher delegates `node.kind.author` — *the only path on which packages actually get authored in the reported failure* — the Package Builder is instructed to consult a tool it does not have, cannot request, and will never be offered. Its first instruction is dead on arrival, and it has no way to know that.

What it does instead is exactly what a competent model does when told to check something it cannot check: it proceeds. It authors. dev/93's evidence shows the result — one question about the weather in Paris produced `curio.notes` and then `curio.postits`, near-identical, in a single run, while a perfectly good notes package sat in the user's store.

### Why dev/93 did not close this

dev/93 attacked the duplication from both ends and left the middle untouched, on purpose:

| Layer | dev/93 commit | What it fixed | What it left |
|---|---|---|---|
| The parent's options | 6 (`fb30b658`) | the Researcher can now **enlist** an installed package instead of only reusing or authoring | the parent must *notice* the option; the roster tells it, but only the parent |
| The parent's roster | 4 (`9876ae9d`) | one roster, two buckets, and every roster-granted agent gets it | a **delegate** holds no grants, so no roster |
| The failure recovery | 5 (`f2c5f669`) | an unparseable draft is corrected against the real error, and the package id is pinned across rounds | a draft that parses **first time** and duplicates an existing package is not a failure at all — nothing catches it |

That last row is the gap. The correction loop only engages when something goes *wrong*. A confident, well-formed, entirely duplicative draft sails through: it parses, it builds, it becomes a reviewed proposal, and the only thing standing between it and the user's store is the user noticing. The agent that could have said "you already have this" is the one agent in the chain that cannot see it.

### Current behavior vs expected

**Current.** An authoring delegate receives (`delegation._frame_inputs`) exactly the parent's `inputs`, plus two server-side enrichments (`_enriched_delegate_inputs`, `agents/services.py:6105-6143`): `buildRequestContract` for authoring capabilities (dev/90 A8) and `verification` for `research.verify` (dev/67-4). Nothing about what already exists. Its reuse-first instruction has no evidence to stand on.

**Expected.** The runtime supplies the evidence the instruction depends on, exactly as it already does for the two enrichments above: an authoring delegate receives the same package/template facts `packages.catalog` would have served, so "an existing package already satisfies the need" becomes a statement it can actually evaluate — and "say so, that is your whole answer" becomes a reachable outcome.

### Why it matters

Every other layer of the reuse ladder now works, which makes this the load-bearing one. The parent can enlist, the roster distinguishes "installed elsewhere" from "nonexistent", failed drafts self-correct, and the store no longer loses its vocabulary — and a duplicate package can still be authored on the first try, by an agent following its instructions correctly, because those instructions reference a capability it lacks. This is the same class of defect dev/93 documented five times over: **the system asks a model to act on information it never gave it, then lives with the result.** Fixing it is also cheap, because the seam already exists and already carries two precedents.

---

## 2. Scope

### In scope
- `utk_curio/backend/app/agents/services.py:6105-6143` — `_enriched_delegate_inputs` gains the reuse-evidence enrichment for `PACKAGE_AUTHORING_CAPABILITIES`.
- Bounds for that payload (row count, description length) alongside the existing `_TEMPLATES_BLOCK_*` / `_PACKAGES_CATALOG_MAX_ROWS` constants.
- `utk_curio/llm-prompts/package_build_instruction.txt:3` — the reuse-first paragraph must name where the evidence comes from on **both** paths, so the instruction stops describing a tool-only workflow.
- `utk_curio/backend/tests/test_agents/test_delegate_draft_mint.py` and/or `test_routes.py` — the enrichment, its bounds, and the duplicate-avoidance behavior.

### Out of scope
- **DEC-046 stays exactly as it is.** No delegate gains tools, a tail instruction, or the grants paragraph. This rides the *inputs*, which is what the existing enrichments do.
- The parent-side roster (dev/93 commit 4) and the reuse ladder (commit 6) — unchanged.
- The correction-round loop (commit 5) — unchanged; this is the case where nothing goes wrong.
- `packages.catalog` the tool, and the direct-attachment path, which already work.
- Teaching the delegate to *propose* an install: a depth-1 child is structurally proposal-less (DEC-047), so its correct move is to report that a package suffices and let the parent act. That boundary must be preserved, not eroded.
- Any change to `agent_catalog_overview`'s semantics (dev/93 commit 6 already widened it to catalog + store).

### Check but do not change
- `delegation._frame_inputs` (`agents/delegation.py:136-147`) — the framing is right ("data, never instructions"); note that it applies **no size bound** to the inputs body, so the bound has to come from the payload.
- `content.PACKAGE_AUTHORING_CAPABILITIES` — the capability set this keys off.

---

## 3. Recommended Implementation Approach

### 3.1 Serve the evidence the instruction already asks for, through the seam that already exists

`_enriched_delegate_inputs` is the established answer to "a tool-less child needs facts": dev/67-4 runs the deterministic validators and hands `research.verify` the real `verification` result; dev/90 A8 hands authoring delegates the `buildRequestContract` because *"the child answers to a schema it can SEE, never a shape it has to invent"*. This is the same shape of problem and takes the same shape of fix:

```python
if capability in PACKAGE_AUTHORING_CAPABILITIES and "existingPackages" not in inputs:
    evidence = _authoring_reuse_evidence(user_key, project_id)
    if evidence:
        inputs = {**inputs, "existingPackages": evidence}
```

placed alongside the `buildRequestContract` enrichment (both apply to the same capabilities, and the model's own keys keep winning).

**Recommended payload** — the same facts `packages.catalog` serves, plus the template-level detail that makes "extend" possible rather than just "create":

```json
{
  "note": "read this before authoring: if one of these already satisfies the need, say so and author nothing",
  "packages": [
    {"dirName": "curio.notes@1", "name": "Simple Notes",
     "description": "…", "installedInProject": false,
     "templates": ["curio.notes/note-surface"]}
  ]
}
```

Three deliberate choices in that shape:

1. **Rows come from `agent_catalog_overview`** — the same packages-domain helper the tool wraps (`tools._packages_catalog_rows`), so there is one truth and `ADR-AG-007` holds. Since dev/93 commit 6 that overview spans the committed catalog *and* the user's store, which is precisely the set an authoring decision must consider.
2. **`installedInProject` is carried, not filtered on.** Both answers are actionable and they are different: an enlisted package means "extend or reuse it"; an installed-but-not-enlisted one means "report it — the parent can enlist it" (dev/93's middle rung). Collapsing them would recreate the one-bucket mistake dev/93 D4 was about.
3. **Template ids ride along**, canonical and unversioned via the packages domain, so a delegate choosing `mode: "extend"` can name what it is extending instead of guessing. Without them "extend" is advice the model cannot follow.

**Bounds.** `_frame_inputs` does not bound the inputs body, so the payload must bound itself: cap the row count (reuse `_PACKAGES_CATALOG_MAX_ROWS`, or a local constant in the same spirit), truncate descriptions as the tool does, and cap templates per package. Log when truncation drops rows — the no-silent-caps rule dev/93 applied to the roster applies here for the same reason.

**Degradation.** A broken registry yields no enrichment and the delegation proceeds — matching how `nodeContext` and `verification` degrade ("honest absence beats a fabricated neighborhood"). It must never raise into the delegation path.

### 3.2 Make the instruction true on both paths

Line 3 currently names one mechanism (`read packages.catalog`). It should name the evidence rather than the transport, so it is executable whether the facts arrive by tool or by input — something to the effect of: *check the existing packages you can see — the `packages.catalog` tool when you have it, the `existingPackages` input when you are working from a delegated task* — and keep the consequence unchanged: if one satisfies the need, say so and author nothing. The `mode: "extend"` option deserves an explicit mention here too, since with template ids available it becomes a real choice instead of a footnote.

**Rejected alternative:** giving delegates the `packages.catalog` tool. It would need a tail instruction and a grants paragraph in the child run, which is exactly what DEC-046 forbids and what makes cycles structurally impossible. The input path gets the same facts with none of that.

### 3.3 What this deliberately does not do

It does not *enforce* non-duplication. A model handed the facts can still author a duplicate, and the runtime cannot adjudicate "satisfies the need" — that judgment is why an agent is there. Enforcement, if it is ever wanted, belongs in a later review-surface change (surfacing "this looks like `curio.notes@1`" on the proposal card) and should be argued on its own evidence. This memo's claim is narrower and verifiable: **the delegate stops being asked to check something it cannot see.**

---

## 4. Data and State Handling

- **Source of truth:** `packages_services.agent_catalog_overview(user_key, project_id)` for package rows and `available_templates` / `installed_templates_not_in_project` for template ids — all packages-domain helpers, per `ADR-AG-007`. The agents module composes, never enumerates manifests itself.
- **Freshness:** composed per delegation at dispatch time, like every other enrichment. Nothing is cached, so nothing goes stale; a package enlisted moments earlier is visible to the next delegation.
- **Precedence:** the model's own input keys always win (`"existingPackages" not in inputs`), matching both existing enrichments — a parent that wants to supply its own view is not overridden.
- **Direction of travel:** input-only. The delegate returns a draft or a finding; it never mutates, never proposes, and this adds no new return path.
- **Failure:** any exception composing the evidence → no enrichment, delegation proceeds. The child then behaves exactly as it does today.

---

## 5. UI and UX Requirements

No visible surface changes. Two indirect effects worth stating:

- The delegation card's summary should read naturally when the delegate's whole answer is "you already have this" — that reply is a *success* for the doctrine, but it mints no proposal, so under dev/93 commit 5's honest-status rule it reports `failed`. **That is now wrong for this case** and is the one interaction this memo must get right: "an existing package satisfies the need" is a legitimate terminal outcome, not a failed authoring. It needs its own outcome wording rather than being lumped with "produced no usable draft".
- The parent's chat reply must be able to say "a package you already have does this" and point at the enlist path — the Researcher's ladder (dev/93 commit 6) already has the vocabulary for it.

---

## 6. Edge Cases

1. Empty store and empty catalog → no enrichment (nothing to report); authoring proceeds as today.
2. More packages than the row cap → truncate deterministically (sorted), and log what was dropped.
3. A very long description or a package with many templates → truncate both; the payload must stay bounded regardless of store size, because `_frame_inputs` will not bound it.
4. A package present in both catalog and store → one row (the overview already dedupes, store manifest winning).
5. An unreadable installed package → skipped by the overview, and dev/93 commit 1's `available_templates_report` already logs it; the enrichment must not silently imply the store is complete when it is not.
6. The parent already passed `existingPackages` → left untouched.
7. `mode: "extend"` naming a package the project has not enlisted → the build service's existing validation decides; this memo adds no new authority, and the refusal must stay comprehensible.
8. A delegate that replies "curio.notes@1 already does this" and authors nothing → must be reported as a legitimate outcome (see §5), not as a failed draft, and must not be retried by dev/93 commit 5's correction loop (nothing failed).
9. Two capabilities in `PACKAGE_AUTHORING_CAPABILITIES` → both enriched identically; no capability-specific branching.
10. A non-authoring delegate (`research.verify`, `node.content.generate`) → untouched.
11. The evidence payload must not smuggle instructions: it rides `_frame_inputs`' "context data" framing, and its `note` field must read as guidance to the model, never as an override of its own instruction.

---

## 7. Testing Strategy

**Unit — the enrichment**
- Authoring capability + a store containing a package → `existingPackages` present, rows carrying `dirName`, `installedInProject`, and canonical template ids.
- `installedInProject` true for an enlisted package and false for a store-only one (the distinction dev/93 D4 was about).
- A parent-supplied `existingPackages` is not overwritten.
- Non-authoring capabilities are unaffected; the existing `buildRequestContract` and `verification` enrichments still apply.
- Bounds: a store with more packages than the cap truncates and logs; long descriptions truncate.
- A registry failure yields no enrichment and does not raise.

**Integration — the behavior that matters**
- **The regression for the reported failure:** a Researcher delegating `node.kind.author` while `curio.notes@1` sits in the store → the framed child inputs contain `curio.notes@1`. Today they cannot, because nothing composes it. This is the test that would have caught the duplication at its source.
- A delegate whose reply says an existing package suffices → no proposal minted, and the delegation reports the "already exists" outcome rather than a draft failure (§5, edge case 8), with the parent's context carrying it.
- A delegate that still authors (the store has nothing relevant) → unchanged behavior end to end; dev/93's draft tests keep passing.
- Prompt-marker test: the instruction names both evidence paths and the `extend` option (the repo's established pattern for pinning prompt contracts, e.g. dev/91's marker tests).

**Verification**
- `test_agents` + `test_packages` green; the dev/93 commit-5 correction-round tests unaffected.
- Teeth checked by A/B, as in dev/93: removing the enrichment must fail the integration regression.

---

## 8. Acceptance Criteria

1. An authoring delegate's framed inputs carry the packages the user already has, with `installedInProject` distinguishing enlisted from store-only, and canonical template ids for each.
2. The Package Builder's instruction is executable on both paths: it names the tool for attachment runs and the input for delegated runs, and it names `mode: "extend"` as a real option.
3. The payload is bounded independently of store size, and truncation is logged, never silent.
4. A delegate replying "an existing package satisfies this" mints nothing, is reported as a legitimate outcome — not a failed draft — and is not retried by the correction loop.
5. DEC-046 is untouched: no delegate gains tools, a tail instruction, or a grants paragraph; the enrichment rides inputs only.
6. A degraded registry produces no enrichment, no exception, and no implication that the store is complete.
7. The dev/93 series' behavior is unchanged: its draft-mint, correction-round, roster, and ladder tests all still pass.
8. The regression test fails with the enrichment removed.

---

## 9. Recommended Commit Breakdown

**Commit 1 — The reuse evidence, with tests.** `_authoring_reuse_evidence` + the `_enriched_delegate_inputs` branch + bounds/logging + unit tests. Behavior-visible only inside the delegation inputs.

**Commit 2 — The instruction, and the honest "already exists" outcome.** The `package_build_instruction.txt` reuse-first rewrite with its marker test, plus the §5 outcome wording so a correct "you already have this" reply stops being reported as a failure. These belong together: the instruction is what produces that reply, and reporting it as a failure would punish the behavior the instruction now asks for.

**Commit 3 — Memo amendment + docs.** Amend this memo with what shipped and any deviations; extend `docs/AGENTS.md`'s "template vocabulary" section with the delegate half; record whether this warrants a DEC (it is arguably an amendment to DEC-046's *evidence* posture rather than a new decision — worth stating either way).

---

## 10. Engineering Quality Checklist

- [ ] The packages domain stays the only enumerator of packages/templates (`ADR-AG-007`); the agents module composes.
- [ ] The enrichment follows the two existing precedents' shape exactly — same function, same "model's keys win" rule, same degrade-to-absent posture.
- [ ] DEC-046 is preserved in letter and spirit: tool-less, tail-less, cycle-free.
- [ ] The payload is bounded and its truncation logged (`_frame_inputs` bounds nothing).
- [ ] The "already exists" reply is a first-class outcome in the delegation status vocabulary, not a failure.
- [ ] No new authority: the delegate still cannot propose or install (DEC-047 boundary intact).
- [ ] The evidence is data, never instructions — it rides the existing untrusted-context framing.
- [ ] The claim in the commit message matches what the tests prove: the delegate can *see* what exists; it is not *forced* to reuse it.
- [ ] Teeth verified by A/B rather than asserted.

---

## Amendment A1 — implemented (commits 1–2), with deviations

**Commit 1 (`21b2db3a`) — the evidence.** `_authoring_reuse_evidence` composes rows from `agent_catalog_overview` (catalog + store, since dev/93 commit 6) carrying `dirName`, `name`, a truncated `description`, `installedInProject`, and canonical template ids keyed by packageId from `available_templates` + `installed_templates_not_in_project`. `_enriched_delegate_inputs` attaches it as `existingPackages` for `PACKAGE_AUTHORING_CAPABILITIES`, beside the existing `buildRequestContract` — adding, never replacing, with the model's own keys still winning. Bounds are `_REUSE_EVIDENCE_MAX_PACKAGES` 40 / `_REUSE_EVIDENCE_MAX_TEMPLATES` 8 / `_REUSE_EVIDENCE_DESC_CHARS` 200, with truncation logged; a broken registry logs a warning, returns `None`, and the delegation proceeds with its contract intact.

**Commit 2 (`05bb5236`) — the reachable outcome, and an instruction true on both paths.** `_BUILD_REQUEST_CONTRACT` gains `insteadOfAuthoring` teaching `{"reuseExisting": {dirName, reason}}`; `_extract_reuse_finding` recognises exactly that shape, bare or fenced; `_mint_package_draft_from_delegate` checks it **before** the draft parse and returns immediately with outcome `"ok"`; `_reuse_finding_text` names the package, states that authoring nothing was correct, and tells the parent whether it must enlist first. `package_build_instruction.txt` now names both evidence paths, the reply shape, and `mode: "extend"`.

### Deviations and decisions taken during implementation

1. **A DEC was minted after all** (§9 left this open). DEC-063 records the generalizable rule rather than the fix: *an instruction must be executable on every path its agent runs on*, and *a doctrine with no reachable outcome is not a doctrine*. It **amends DEC-046's evidence posture without touching its structure** — tool-less, tail-less, cycle-free all stand. Worth a DEC because it is now the third instance of the same pattern (dev/67-4, dev/90 A8, dev/94) and it is checkable at design time.
2. **§5's "already exists" outcome resolved as `"ok"` with no new status vocabulary.** The memo asked for "its own outcome wording". Investigation closed that off: `AgentDelegationEntry.tsx` renders `part.status === "failed" ? "failed" : "ok"` and `content.make_delegation_part` coerces to exactly those two, so a third value would have been silently normalised to `failed` — the worst outcome. The honest signal therefore rides the outcome plus the **summary**. This satisfies DEC-062's rule rather than bending it: that rule is that a run producing *nothing* must not claim success, and this run produced the answer.
3. **Reuse is checked before the draft parse, not after a failed one.** A reply naming a reuse target is *declining* to author; treating it as a fallback for a failed parse would have made the doctrine reachable only by accident.
4. **Detection is schema-keyed, never prose.** A test pins that "curio.notes@1 already does this, so I authored nothing" as free text is **not** a finding. Reading intent out of prose would put model wording in charge of control flow.
5. **Catalog-only packages appear without template ids.** The two template listings cover the store and the project; a never-installed catalog package therefore carries name + description only. Honest and sufficient — `mode: "extend"` against a package that is not installed is the build service's question anyway (edge case 7) — and it avoided adding a catalog-manifest walk for no behavioural gain.

### What the A/B proved

Removing the enrichment branch fails exactly the two tests asserting the delegate receives it. Removing the reuse-finding branch fails exactly the three behaviour tests, and the failure output reproduces the pre-fix hand-back verbatim: *"the authoring delegate produced no usable package draft … fix THAT and keep the same package id"*. That is the concrete proof of why commit 2 had to accompany commit 1 — without it we would have shipped facts the delegate could see, an instruction telling it to act on them, and a runtime that punished it for complying.

**Verification:** full backend suite excluding the pre-existing-broken Playwright file — **1667 passed**, 8 skipped. Also verified against the live project (guest / `a9a1afc7`): the composed evidence lists `curio.notes@1` with `installedInProject: false` and its `note-surface` template — the exact fact that was missing when the duplicate was authored.

**Non-goal, restated because it must not be mistaken for a guarantee:** this makes reuse sayable and its consequence correct. It does not enforce non-duplication. A model handed the facts can still author a duplicate, and the runtime cannot adjudicate "satisfies the need" — that judgment is why an agent is making it. Advisory duplicate detection on the review surface remains available as a later, separately-argued change.
