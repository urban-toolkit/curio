# Dev/99 — Package-seed reader locking for zero-gap package-store snapshots

Date: 2026-08-24
Status: **proposed — implementation not started**
Depends on: [`dev/93`](93-dataflow-plan-template-vocabulary-memo.md) (`DEC-062`), especially amendment A1; `app/common/file_locks.py`
Decision posture: closes an already-recorded dev/93 follow-up; no new decision ID is required

## 1. Problem Statement

Dev/93 made each per-user package-seeding pass exclusive and changed replacement from delete-then-copy
to a complete-tree swap. That work prevents a reader from observing a package directory that is present
but only partially copied. It does **not** provide continuous reader availability: POSIX cannot rename a
new directory over an existing non-empty directory, so `_swap_in_package` first moves the old tree aside
and then moves the staged tree into place. During the interval between those two renames, the package
path is absent.

Current package readers do not take the seeder's lock. In particular, `list_user_packageages` returns
`Path` objects and its callers load manifests or assets later. A reader that overlaps the two-renames
interval can therefore treat a healthy seeded package as temporarily missing. For agent-facing paths,
that transient absence can become a false template-resolution refusal, an incomplete package roster, or
missing presentation-template/reuse evidence. For HTTP catalog paths, it can become a brief incorrect
installed state. These outcomes are self-correcting on a later request, but the current request has
already received incorrect data.

The existing concurrency test deliberately permits this state: it rejects present-but-broken package
trees but counts an absent read as acceptable. Accordingly, the current “concurrency-safe” seeder claim
means safe from corruption, not zero-gap availability.

Expected behavior: readers that form a logical snapshot of the seed-managed user package store must use
the same exclusive per-user seed lock as the writer. Such a reader must observe either the complete old
package tree or the complete replacement tree, never the writer's intermediate absence interval.

## 2. Scope

Included:

- introduce one public package-level context manager for the existing per-user lock contract
  (`<user>/packages/.seed.lock`, namespace `package-seed`), preferably in a small
  `app/packages/locks.py` module so readers do not import private constants from `seed.py`;
- refactor `seed_dev_packageages` to use that shared context manager without changing seeding policy,
  health checks, state markers, staging, or swap behavior;
- protect complete read transactions rather than only `list_user_packageages` enumeration: the lock
  must cover enumeration and every manifest or package asset read needed to construct that snapshot;
- migrate the agent- and project-facing snapshot producers in `packages/services.py`, including
  `installed_templates_not_in_project`, `available_templates_report` (and therefore
  `available_templates`), `presentation_templates`, and `agent_catalog_overview`;
- migrate resolver reads in `packages/resolver.py::_load_manifests`, including named installed-package
  reads that resolve directly through `package_dir` as well as the all-installed-package walk;
- migrate the installed-package HTTP snapshots in `packages/routes.py`, especially the installed list
  and catalog installed-coordinate snapshot;
- audit the remaining direct user-store readers in `routes.py`, `starters.py`, `libraries.py`,
  `build_deps.py`, `backend_runtime.py`, and `build_extension.py`; protect any enumeration-plus-read
  operation that can overlap a seeded package replacement, while keeping later expensive work outside
  the lock;
- add deterministic and concurrent regression coverage proving zero-gap behavior for production reader
  paths; and
- update the Stage-3 build evidence and this memo's status only after implementation and verification.

Out of scope:

- replacing the existing two-renames swap algorithm;
- changing catalog selection, seed eligibility, tombstones, integrity validation, or self-healing rules;
- merging the seed lock with installer, uninstall, promote, project-spec, defaults, or backend-runtime
  target locks;
- redesigning install/uninstall transactionality or claiming a snapshot guarantee against writers that
  do not participate in this lock;
- adding caches, changing manifest or API schemas, or changing agent/tool semantics;
- holding a filesystem lock during provider calls, network access, dependency installation, subprocess
  execution, package backend invocation, or project writes;
- introducing a reader/writer lock. The existing exclusive lock is the required first implementation;
  reader-reader serialization is acceptable for short local-filesystem snapshots unless later profiling
  establishes a real need for a broader lock design; and
- frontend or visual changes.

## 3. Recommended Implementation Approach

### 3.1 Centralize the lock contract

Add one public context manager owned by the packages subsystem, for example
`package_seed_lock(user_key)`. It should:

- derive the package-store directory and lock-file path in one place;
- use `common.file_locks.exclusive_lock` with the existing `package-seed` namespace and user key;
- ensure the lock file's parent exists before acquisition, while preserving the reader's existing
  logical result for an otherwise empty store;
- document that it is exclusive, per-user, process-and-thread safe, and non-reentrant; and
- remain the only owner of the lock filename and namespace so seeder and reader contracts cannot drift.

Do not describe this as a shared/read lock: the current primitive is an exclusive mutex. “Shared” in
this memo means only that writers and readers call the same public lock contract.

### 3.2 Lock logical snapshots, not path discovery alone

Do not add a lock solely inside `list_user_packageages`. That function returns live filesystem paths;
the package can be swapped after it returns and before a caller loads its manifest. Instead, place the
lock around the smallest top-level operation that can finish the logical snapshot.

Where multiple public helpers share the same walk, extract a private, explicitly unlocked helper and
let one public wrapper acquire the lock. This prevents accidental same-thread nested acquisition of the
non-reentrant lock. For example, `available_templates` should continue delegating to
`available_templates_report`; it must not acquire the lock independently when the report already owns
it.

The minimum lock-owned work for a snapshot is:

1. enumerate the relevant installed package directories;
2. load the manifests and the bounded local assets needed for the return value;
3. copy/transform those values into ordinary Python data detached from the live paths; and
4. release the lock before performing unrelated work or returning control to another subsystem.

### 3.3 Keep the seed lock a leaf lock

Resolve project lockfiles, catalog-only manifests, request parameters, and other non-package-store data
before taking the seed lock where doing so does not weaken correctness. Once the seed lock is held, do
not acquire project/spec, defaults, installer, target, provider, or subprocess locks. Release it before
any project mutation, install/apply action, dependency work, external call, or backend execution.

If a caller currently interleaves store reads with later work, split it into a short snapshot phase and
an unlocked action phase. This both limits contention and makes lock order reviewable. The lock remains
per-user, so one user's forced reseed must not delay another user's reads.

### 3.4 Apply the boundary consistently

Prioritize readers whose return values directly govern user or agent decisions:

- template availability and resolution;
- presentation-template and reuse/enlist evidence;
- agent package-catalog overview;
- dependency resolver manifest sets; and
- installed-package/catalog route payloads.

Then complete the direct-reader audit. A reader that only needs filenames may snapshot those filenames
under the lock and release it immediately. A reader that needs a manifest or asset must read that data
before release. A caller that begins dependency installation or executes package code must snapshot only
the required metadata/bytes under the lock and perform the expensive action afterward.

This change should not broaden exception swallowing. Genuine missing or malformed packages must retain
their current error, warning, skip, or empty-state behavior; only the seeder-created false absence is
removed.

## 4. Data and State Handling

The per-user package directory remains the source of truth. No application record, manifest schema,
project lockfile, seed-state marker, or response shape changes.

The desired concurrency model is:

- the seeder acquires the per-user seed lock, then prepares its complete staging tree and performs its
  current replacement while continuing to hold that lock;
- a reader acquires that same lock before reading a package-store snapshot;
- a reader that arrives first completes against the old tree before seeding begins;
- a reader that arrives during a seed pass waits, then completes against the replacement tree; and
- a failed swap restores the old tree before releasing the lock, so the waiting reader receives that
  restored complete state.

Derived values—template IDs, installed coordinates, roster rows, resolver manifests, and route
payloads—must be built from one lock-scoped snapshot and returned as detached values. Do not cache
`Path` objects as a substitute for the lock and do not introduce duplicated in-memory package state.

Loading remains synchronous local filesystem work. Waiting for the lock is a loading delay, not an
empty or error state; callers must not clear previously rendered data or emit a synthetic “not found”
result while waiting. Exceptions must release both the in-process and interprocess lock through context
manager cleanup.

## 5. UI and UX Requirements

There is no intended UI redesign or response-schema change. Existing labels, controls, loading
indicators, focus behavior, and accessibility semantics remain unchanged.

User-visible correctness requirements are:

- the Packages catalog must not briefly mark a seeded installed package as uninstalled because a
  refresh is between renames;
- canvas and agent flows must not temporarily lose built-in or enlisted node templates;
- `resolve_template` must not refuse a valid template solely because seeding is in progress;
- package recommendation, reuse/enlist guidance, and presentation-template selection must receive a
  complete roster snapshot; and
- waiting for a short seed operation must not cause list flicker, an empty-state flash, layout shift, or
  a misleading error.

Any existing truthful behavior for a genuinely missing, explicitly uninstalled, or malformed package
must remain visible as it is today.

## 6. Edge Cases

The implementation must handle:

- a reader starting immediately before, during, or after the two-renames interval;
- a forced reseed on every pass via `CURIO_RESEED_PACKAGES`;
- first-run creation of a previously absent user package store;
- a missing or unhealthy built-in that the seeder self-heals;
- a swap failure after the old tree has moved aside, including restoration before readers proceed;
- orphaned seed staging directories from a killed process;
- multiple reader threads and multiple seeder threads for the same user;
- separate users reading or seeding concurrently without cross-user blocking;
- separate processes, including the development reloader, contending for the same user lock;
- POSIX and Windows lock implementations, plus guaranteed release when snapshot code raises;
- duplicate package majors and the existing highest-major built-in preference;
- malformed, missing, or unreadable manifests that are unrelated to an active seed swap;
- callers requesting an explicit package name while that package is being replaced;
- avoiding nested acquisition when one public package helper calls another;
- avoiding lock-order cycles with project/spec, defaults, installer, target, and backend-runtime locks;
  and
- concurrent install, uninstall, promote, or invocation behavior remaining no worse, without claiming
  those writers are made atomic by the seed lock.

## 7. Testing Strategy

Required unit and integration coverage:

1. Add lock-contract tests proving writer and reader helpers use the same path, namespace, and per-user
   key, release on exceptions, and keep different users independent.
2. Add a deterministic swap-window regression test. Pause `_swap_in_package` after the old tree is moved
   aside but before the new tree is moved in; start a production reader; prove it blocks rather than
   returning an empty, skipped, or refused result; release the swap and assert the reader returns a
   complete snapshot.
3. Strengthen `test_concurrent_passes_never_expose_a_broken_store`: exercise a production reader path
   with the existing 8-seeder/8-reader forced-reseed stress and require both zero broken reads and zero
   absent reads. Do not rely on a later `exists()` check that can race with another swap.
4. Cover both sides of the snapshot guarantee: a reader that acquires first returns the complete old
   tree, while a waiting reader returns the complete replacement tree.
5. Preserve the failed-swap regression and assert a waiting production reader receives the restored old
   tree after failure.
6. Add focused coverage for `available_templates_report`, `presentation_templates`,
   `installed_templates_not_in_project`, `agent_catalog_overview`, resolver manifest loading, and the
   installed/catalog routes, or prove those surfaces all delegate to one covered lock-owning primitive.
7. Add a regression in the agent/template resolution path proving a valid built-in or enlisted template
   is not rejected during forced reseeding.
8. Add a structural audit test, if practical, that prevents a future reader from treating a locked
   `list_user_packageages` call followed by unlocked manifest reads as one protected transaction.
9. Retain and run the platform fallback coverage in `test_projects/test_storage.py` or move equivalent
   assertions beside the shared package-lock tests; cover the Windows retry/release path through mocks.
10. Exercise same-user blocking and different-user non-blocking behavior without timing-only assertions;
    use events/barriers so the tests are deterministic.

Verification before completion:

- run the focused package seed, services, resolver, and route suites;
- run the relevant agent route/tool/delegation tests whose context depends on package rosters;
- run the full backend suite and record pass/skip counts plus any independently baselined failures in
  the Stage-3 build entry; and
- confirm no frontend test or visual update is required because no frontend contract changed.

## 8. Acceptance Criteria

1. Seeder and protected readers use one public per-user package-seed lock contract; the filename and
   namespace are not duplicated across modules.
2. The public contract uses the existing thread-plus-process exclusive lock and is documented as
   non-reentrant and per-user.
3. No protected production reader can observe the package absence created solely by the seeder's
   two-renames replacement interval.
4. Each protected logical snapshot holds the lock across directory enumeration and all dependent
   manifest/asset reads; returning live `Path` values from a locked enumeration is not treated as
   sufficient protection.
5. `available_templates_report` and `resolve_template` retain valid built-in and enlisted templates
   during forced reseeding, with no false unavailable-template refusal.
6. Agent catalog, reuse/enlist, and presentation-template contexts remain complete during reseeding.
7. Installed-package and catalog HTTP responses do not transiently lose seeded installed coordinates.
8. A reader receives either a complete pre-swap tree or a complete post-swap tree, never a partial tree
   or the writer's intermediate absence state.
9. If replacement fails, the old tree is restored before waiting readers proceed, and current warning/
   recovery behavior remains intact.
10. Lock scope contains only bounded local snapshot work; provider, network, subprocess, dependency,
    install/apply, backend execution, and project-write work happens after release.
11. Same-user readers wait for a seed pass, different users do not block one another, exceptions release
    the lock, and tests contain no timing-dependent race assertions.
12. Genuine missing/malformed-package handling, response shapes, agent behavior, seed policy, and
    install/promote semantics remain unchanged outside the fixed race.
13. Focused and full backend verification passes, or any unrelated baseline failure is explicitly
    reproduced and documented; the Stage-3 entry records exact evidence.

## 9. Recommended Commit Breakdown

- **Commit 1: centralize the package-seed lock contract.** Add the public packages lock context,
  refactor the seeder to use it, and add contract/platform/exception-release tests.
- **Commit 2: lock complete package-reader snapshots.** Migrate the required service, resolver, route,
  and audited runtime readers; split snapshot and action phases where necessary; add deterministic
  swap-window and 8×8 concurrency regressions.
- **Commit 3: close traceability.** Run focused/full verification, add the Stage-3 evidence entry, mark
  this memo implemented only if all acceptance criteria pass, and update remaining-work summaries.

Each commit should remain independently reviewable and must not include unrelated dirty-worktree files.

## 10. Engineering Quality Checklist

- [ ] One public lock contract owns the seed lock path, namespace, and user key.
- [ ] The seeder and every in-scope reader use that contract.
- [ ] No duplicated package-snapshot business logic was introduced.
- [ ] Lock-owning and explicitly unlocked helpers have names/docstrings that make nesting risk clear.
- [ ] Types are explicit and returned snapshots are detached from mutable filesystem paths where needed.
- [ ] The lock is held across complete reads but not across slow or external work.
- [ ] Lock ordering is documented and no nested same-key acquisition or cross-lock cycle exists.
- [ ] Same-user and cross-user concurrency behavior is deterministic and test-covered.
- [ ] Old-tree, new-tree, failed-swap, empty-store, malformed-data, and platform fallback cases are covered.
- [ ] Existing loading, empty, error, and success behavior remains clean and truthful.
- [ ] Agent, resolver, route, and runtime consumers receive consistent package-store snapshots.
- [ ] No response schema, visual behavior, or accessibility regression was introduced.
- [ ] Focused and full backend suites pass with evidence recorded in Stage 3.
- [ ] Documentation status is updated only after implementation is actually verified.

---

## Amendment R1 — external review against dev/93 as shipped (2026-08-25)

Reviewed by the session that implemented dev/93 and dev/94, at the owner's request. Appended, not edited:
everything above is the original author's. No code changed; this is a read-only review of the design
against the code that actually landed.

### Accuracy check: no drift

Every symbol this memo names still exists on `feat/agentscatalog` — verified individually:
`installed_templates_not_in_project`, `available_templates_report`, `available_templates`,
`presentation_templates`, `agent_catalog_overview` (all `packages/services.py`), `list_user_packageages`
(`packages/storage.py`), `_swap_in_package` (`packages/seed.py`), `resolver._load_manifests`, and
`common.file_locks.exclusive_lock`.

The description of dev/93 as shipped is correct in every particular: the two-rename mechanism and why
POSIX forces it, the `.seed.lock` filename and `package-seed` namespace, the restore-before-release on a
failed swap, and the fact that `test_concurrent_passes_never_expose_a_broken_store` deliberately tolerates
an absent read while rejecting a present-but-broken one. Non-reentrancy is real — `exclusive_lock` sits on
a plain `threading.Lock` — so §3.2's nesting warning is load-bearing, and treating `resolve_template` as
inheriting protection through `available_templates_report` (AC-5) rather than locking it directly is the
right call: locking both would deadlock immediately.

**Verdict: sound, and safe to implement, with three amendments below.** Only the first is substantive.

### R1.1 — §4's one-snapshot guarantee is not reachable from §2's scope

§4 requires derived values to be "built from ONE lock-scoped snapshot" and AC-6 requires the reuse/enlist
context to "remain complete". The readers are in scope; the **composers that build those payloads are not**,
and they live in `agents/services.py`:

- `_authoring_reuse_evidence` (dev/94 commit 1) calls **three** public readers to build one payload —
  `agent_catalog_overview`, `available_templates`, and `installed_templates_not_in_project`;
- the run-time roster calls **two** — `_available_templates_block` → `available_templates`, and
  `_enlistable_templates_block` → `installed_templates_not_in_project`.

Lock each public reader independently and every read is internally consistent, but the *composed* payload
can still straddle a seed pass: three lock acquisitions are three snapshots. That satisfies AC-3 and AC-8
(no reader observes the absence interval) while quietly failing §4, and the non-reentrant lock blocks the
obvious remedy of wrapping the composer.

Recommended fix, which is §3.2's own pattern applied one level up: add a packages-domain **composite**
entry point that acquires the lock once and calls the already-extracted *unlocked* cores, and have the
agents-side composers call that. It must live in the packages domain — `ADR-AG-007` keeps template
knowledge there, and the agents module must not own the lock. The alternative is equally acceptable but
must be explicit: state in §4 that composed payloads are per-read consistent rather than snapshot-atomic,
and soften AC-6 to match. What should not ship is §4 as written with §2 as scoped.

### R1.2 — per-node lock churn on the plan mint path

`_mint_dataflow_plan` calls `available_templates` once (for `_validate_plan_fanin` — still genuinely used)
and then `resolve_template` **once per plan node**, each of which walks the store and parses manifests via
`available_templates_report`. A 12-node plan performs 13 store walks today; after this change it performs
13 walks **plus 13 lock acquisitions**, each an `open()` + `flock()` on `.seed.lock`.

The walk cost is pre-existing and not this memo's fault; the locking multiplies it on the hot path that
mints every plan. §3.3 asks readers to keep the critical section small but says nothing about a caller
that invokes a locked reader in a loop. Either resolve plan nodes against the snapshot already fetched at
the top of the mint, or record the per-node cost as consciously accepted. Worth deciding before
implementation, because it is much cheaper to fix in the mint than to unpick afterwards.

### R1.3 — the writer holds the lock across non-package-store work (minor, verified small)

`_seed_locked` runs `_max_mtime` — an `rglob` over the **fixture catalog**, not the user store — and
`example_dep_package_ids()`, which reads `docs/examples/*.json`, both inside the lock. §3.3 imposes
"resolve non-store data before acquiring" on readers; the same discipline is free for the writer and
directly shortens the interval every reader will now wait on.

Magnitude was measured before raising it: the builtin fixture is 3 files across 4 fixture packages, so
today this is negligible and is a design note rather than a blocker. It grows under `CURIO_SEED_EXAMPLES`
and with heavier fixture packages, and hoisting it costs nothing.

### R1.4 — small note on §7.3

The warning against "a later `exists()` check that can race with another swap" lands against an earlier
draft of that test. The shipped version compares the package directory's **inode** across the read, which
stays valid under this change; it needs only its tolerance inverted — `reads["absent"]` becomes a failure
rather than a counted outcome. The inode comparison should be kept, since it is what distinguishes a lost
race from genuine corruption.

### Status of this amendment

Advisory only. This memo remains its author's to implement, amend, or reject; the file is untracked and has
been left untracked and unstaged. R1.1 is the one item recommended for resolution before implementation
starts, since it changes what the acceptance criteria can honestly claim.

---

## Amendment R2 — resolution of R1.1 (the one item flagged as blocking)

R1.1 said §4's "ONE lock-scoped snapshot" guarantee is not reachable from §2's scope, and offered two ways
out without choosing. This amendment chooses, and specifies the work, so implementation can start from
commit 1 without re-litigating it. **Recommendation: build the composite — do not downgrade §4.**

### Why not the downgrade

Weakening §4 to "per-read consistency" would leave the memo's most user-visible acceptance criterion
(AC-6, "agent catalog, reuse/enlist, and presentation-template contexts remain complete during reseeding")
technically satisfiable while the composed payload could still straddle a seed pass. The reuse/enlist
evidence is precisely where a torn snapshot causes the failure dev/93 and dev/94 were written to stop: an
agent seeing `curio.notes@1` in one half of the payload and not the other is back to authoring a duplicate.
The composite is also cheaper than the status quo, so the downgrade buys nothing.

### The measurement that decides it

The three public readers are not merely three lock acquisitions — they are three redundant traversals.
Each independently calls `get_project_lockfile` (project-spec I/O, not package-store) and each independently
calls `list_user_packageages` plus manifest loads; `agent_catalog_overview` additionally reads the committed
catalog via `_catalog_manifests`. So `_authoring_reuse_evidence` (dev/94) currently performs **3 spec reads
and 3 store walks** to build one payload, and the run-time roster performs 2 of each. Locking them
individually would preserve that redundancy and add a lock acquisition to every repetition.

### The shape

Extend §3.2's unlocked-core pattern by exactly one level:

1. **Unlocked cores**, private, each taking the already-resolved lockfile rather than reading it:
   `_available_templates_report_unlocked(user_key, wanted)`,
   `_installed_templates_not_in_project_unlocked(user_key, wanted)`,
   `_agent_catalog_overview_unlocked(user_key, wanted, catalog)`.
2. **Existing public readers keep their signatures and behaviour**: resolve the lockfile (and catalog) first,
   outside the lock per §3.3, then `with package_seed_lock(user_key):` call the core. No caller changes.
3. **One new public composite in the packages domain**, e.g. `template_landscape(user_key, project_id)`:
   resolve the lockfile ONCE and the committed catalog ONCE outside the lock, take the lock ONCE, run all
   three cores against that single store snapshot, and return detached data —
   `{"available": [...], "notEnlisted": [...], "catalog": [...], "skipped": [...]}`, preserving
   `available_templates_report`'s degradation signal rather than dropping it.
4. **Agents-domain callers migrate to the composite** (they consume it; they never own the lock, per
   `ADR-AG-007`): `_authoring_reuse_evidence` and the run-time roster
   (`_available_templates_block` + `_enlistable_templates_block`) each take one landscape instead of two or
   three public readers.

Nesting is impossible by construction: the composite calls cores, never public readers, so the
non-reentrant lock is acquired exactly once on every path.

### R1.2 folded into the same mechanism

The plan mint's per-node churn has the same fix. `_mint_dataflow_plan` currently calls
`available_templates` once (for `_validate_plan_fanin`) and then `resolve_template` once **per plan node**,
each re-walking the store; a 12-node plan becomes 13 walks plus 13 lock acquisitions. Add a batch gate —
`resolve_templates(user_key, project_id, node_types, *, require_authorable=False)` — that takes the lock
once, resolves every node type against one snapshot, and returns per-id `(entry | None, error)`. The mint
then holds one snapshot for both fan-in validation and node resolution. Single-node callers
(`_available_template` → `node.create`) keep the existing `resolve_template`, which becomes a one-element
convenience wrapper over the batch gate.

### Scope and acceptance changes this implies

- **§2 gains** the agents-domain callers as *migration targets that consume the composite* — explicitly not
  as lock owners: `agents/services.py::_authoring_reuse_evidence`, `_available_templates_block`,
  `_enlistable_templates_block`, and `_mint_dataflow_plan`.
- **§2 gains** `resolve_template`/`resolve_templates` as the batch gate, alongside the readers already listed.
- **§3.3 sharpens**: the lockfile read and the committed-catalog read are non-package-store I/O and must be
  resolved *before* acquiring the lock — this applies to the writer too, whose current critical section
  includes `_max_mtime` (an rglob of the fixture catalog) and `example_dep_package_ids()` (which reads
  `docs/examples/*.json`). See R1.3; small today, free to fix, and it shortens the interval every reader waits on.
- **AC-6 becomes honestly satisfiable** and should say so: composed agent payloads are built from ONE
  lock-scoped snapshot, not from several consistent-but-independent reads.
- **New AC**: no public packages reader is called from inside the lock; composites call unlocked cores only.
- **New AC**: a plan mint of N nodes acquires the seed lock a bounded number of times independent of N.
- **§7 gains** a test that the composed reuse/roster payload is internally consistent across a concurrent
  seed pass — the specific tear R1.1 identified — and a test asserting the acquisition count does not scale
  with plan size.

### Sequencing

This changes the commit plan in §9 only by insertion: the cores-plus-composite refactor is a
behaviour-preserving step that should land **before** any reader takes the lock, so that migrating a caller
is a one-line change and the lock is introduced once, in one place. Suggested order: extract cores and add
the composite with the existing behaviour and no locking (pure refactor, existing tests must pass
unchanged) → introduce `package_seed_lock` and wrap the public readers and the composite → migrate the
agents-domain callers and the plan mint → then the route/resolver audit in §2 as already written.

*Appended by the session that implemented dev/93 and dev/94, at the owner's request. Advisory, like R1: the
memo remains its author's to accept or reject.*
