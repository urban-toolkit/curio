# dev/124 — A save may not delete what it never saw: revision-aware project writes

**Status: PROPOSED (2026-09-10) on `imp/agentcatalog` — closes dev/123 F7. Proposes no new
`DEC` unless the owner wants one; this is the general form of a rule `DEC-079` already states
for evaluation projects, and it retires that special case rather than adding a second one.**

Date: 2026-09-10
Branch / tree: `imp/agentcatalog` @ `2e9918a6` (dev/123 closed, including its two live-run
fixes). Line numbers pinned to that commit.

---

## 1. Problem Statement

**A client save carries no basis, so a project's spec is last-writer-wins across two
different kinds of writer that do not know about each other.**

The canvas saves by sending the whole spec: `saveCurrentProject`
(`hook/useWorkflowOperations.ts:791`) serialises React Flow's live nodes and edges through
`TrillGenerator.generateTrill` and `PUT`s them. The server takes that graph verbatim —
`update_project` (`app/projects/services.py:588`) carries forward `dataflow.agents`,
`packages` and `datasets` because those are backend-owned, and then writes the client's
`nodes` and `edges` as they arrived.

Meanwhile the backend writes the same file on its own, from paths that have nothing to do with
a canvas: an agent apply (`apply_proposal` → `_apply_dataflow_plan`,
`app/agents/services.py:2860`), every wave of a verified Solve (`DEC-075`), a dataset install,
a package install, the evaluation service. All of them go through
`projects_storage.write_spec` (`app/projects/storage.py:89`), which is a plain `write_text` —
it records nothing about the write having happened.

So a browser that loaded a project at time T and saves at time T+n silently erases every
server-side write in between. This is not hypothetical: it is how the owner's first real
evaluation run finished **with a score of 0.64 and an empty canvas** (dev/123 §11 F-f). The
run applied a plan of six nodes, Solve verified all six, the comparator scored a real graph,
and then a canvas that had been opened before the apply saved its empty graph over all of it.
The spec on disk still carries `nodeProvenance`, a key only the frontend emits, written six
seconds after the run's last turn — that is the fingerprint of the overwrite.

**Why the existing `spec_revision` does not already solve this.** There is a `spec_revision`
column (`app/projects/models.py:23`), bumped in `repositories.upsert_project` (`:74`),
surfaced on `ProjectSummary`/`ProjectDetail` and shown as *"Rev N"* in the Projects list. It
counts **client saves only**: `upsert_project` runs from `save_project` and `update_project`
and from nowhere else, so an agent apply, a Solve wave and a dataset install all leave it
unchanged. A concurrency check built on today's number would compare two numbers that were
equal precisely when the dangerous write had happened. The counter has to move with the write,
not with the request.

**What should happen.** A save that would delete content the client never saw is refused with
an actionable message, and every other save behaves exactly as it does today. A user who
moves, edits, renames or deletes something keeps doing so with no new dialog in the way.

**Why it matters.** Silent loss of a user's or an agent's work is the worst failure a
persistence layer has, because nothing tells anyone it happened. dev/123 closed it for
evaluation projects with a rule that knows what an evaluation is; every other project is still
exposed, and the Solve and apply lifecycle makes background writes an ordinary event rather
than an edge case.

---

## 2. Scope

**In scope**

- `app/projects/storage.py` — the write chokepoint gains the counter.
- `app/projects/services.py` — `update_project` consults the guard; the detail reports the
  counter.
- `app/projects/schemas.py` — `ProjectUpdate.base_revision`; `ProjectDetail.spec_revision`
  keeps its name and gains its new source.
- `app/projects/routes.py` — reads `baseRevision` from the body, maps the refusal to 409.
- A new `app/projects/concurrency.py` — the rule, pure.
- `app/agents/evaluation/authorization.py` — its graph clause is **deleted** and replaced by
  the general rule; the in-flight clause stays (it is evaluation-specific).
- Frontend `api/projectsApi.ts`, `hook/useWorkflowOperations.ts` — carry the basis, adopt what
  the server returns, report a conflict in words a person can act on.
- Tests on both sides, and the docs that describe saving.

**Out of scope, deliberately**

- **Merging.** Two divergent graphs are not merged. The rule refuses loss and says reload.
- **Live sync.** The canvas is not made to follow server-side writes as they happen; that is a
  much larger feature and this memo's rule is designed so it is not needed for correctness —
  see §3.3.
- **The shared/viewer path** (`loadSharedProject`) — read-only already.
- **`spec_revision` in the Projects list.** It keeps reading what it reads today; §6 records
  the cosmetic lag that leaves.
- Node-level history, undo, or per-field provenance.

---

## 3. Recommended Implementation Approach

### 3.1 One counter, at the one chokepoint

`storage.write_spec` is the single place a spec reaches disk — 50 call sites across the
projects, agents, packages, datasets and seed domains funnel through it, and nothing writes
`spec.trill.json` directly. So the counter lives in the spec and is bumped there:

```python
SPEC_REVISION_KEY = "specRevision"

def write_spec(user_key, project_id, spec) -> Path:
    payload = dict(spec or {})
    payload[SPEC_REVISION_KEY] = int(payload.get(SPEC_REVISION_KEY) or 0) + 1
    ...
```

Consequences, stated plainly because they are the whole design:

- **Every** writer bumps it, including the ones that have no idea this feature exists. That is
  the property today's column lacks and cannot be given without editing every writer.
- It is monotonic per project and needs no lock of its own: every read-modify-write of a spec
  already happens under `storage.spec_write_lock`.
- A spec written before this change has no counter; it reads as `0`, and the first write makes
  it `1`. No migration.

### 3.2 The rule: refuse loss, not divergence

The naive rule — *"refuse when the basis is stale"* — is wrong here, and it is worth saying
why, because it is the obvious thing to build. A canvas is told about an agent's apply through
a live event (`DEC-071`'s `appliedGraph` dispatch) without reloading, so its basis goes stale
while its content stays current; a dataset install bumps the spec without touching the graph
at all. Refusing on staleness alone would reject ordinary, correct saves several times an hour
and teach people to dismiss the message.

So the rule is about **loss**, and staleness is only its precondition:

> A client save is refused when its basis is older than the spec on disk **and** the spec it
> sends would drop a node or an edge that exists on disk, or blank the content of a node that
> has content on disk.

Both halves are things the client cannot have meant, because it never saw them: a node it
never received cannot be a node it deliberately deleted, and code Solve wrote after the load
cannot be code the user deliberately cleared. Everything else — moving nodes, editing code,
renaming, adding nodes, deleting a node the client *did* load — passes untouched, whatever the
basis says.

This is deliberately the same shape as the rule dev/123 shipped for evaluation projects, and
that special case is removed in favour of this one (§3.5).

### 3.3 Why this needs no live sync and no revision plumbing through every response

Because staleness alone never refuses, the client does not have to learn the new revision from
every endpoint that writes a spec. It only has to remember the revision it last *synced* with:
on load, and on its own successful save. If a server write happened that the client saw live,
its payload carries those ids, nothing is dropped, and the save is allowed even though the
basis is behind. If a server write happened that the client did **not** see, the payload drops
it — which is exactly the case worth refusing.

That is what keeps this change small: two touch points in the frontend rather than one per
writing endpoint.

### 3.4 What a refusal says

409, with a sentence naming what would be lost and what to do:

> This dataflow changed on the server since you opened it — saving now would delete 6 nodes
> that are not on your canvas. Reload the project to see them, then make your change again.

The count comes from the rule, so the message is specific rather than a generic conflict
banner. The client keeps the user's unsaved work in memory and stays dirty; nothing is
discarded on their behalf.

### 3.5 The evaluation special case is retired, not duplicated

`authorization.assert_client_may_replace_graph` currently holds two clauses. The second — *a
save may not leave a run-built graph with no nodes* — becomes a special case of §3.2 and is
deleted; the first — *no client save while the run is still writing* — is genuinely about
evaluations (the run owns the project until it finishes) and stays where it is. One rule for
loss, in `projects/concurrency.py`, called by `update_project` for every project.

### 3.6 Where the guard runs

Inside `update_project`'s existing `storage.spec_write_lock`, after `existing_spec` is re-read
under the lock and **before** the preserve steps, so the check sees exactly the bytes the
write would replace. Server-side callers of `update_project` (the dataset uninstall path,
`datasets/repositories/installed.py:217`) pass no basis and are unaffected by construction.

---

## 4. Data and State Handling

- **Source of truth:** `spec["specRevision"]` on disk. `ProjectDetail.spec_revision` reports it
  when present and falls back to the database column for a spec written before this change, so
  the field keeps its name while its meaning ("how many times this has been written") becomes
  true.
- **The client's basis:** one ref in `useWorkflowOperations`, set from the detail on
  `loadProject` and re-set from the detail every save returns. A brand-new dataflow has none
  and sends none; a create cannot conflict.
- **Loading:** unchanged, plus capturing the number.
- **Saving:** `UpdateBody.baseRevision` when the client has one. Absent means "no opinion" and
  the server does not check, which keeps every non-canvas caller — scripts, tests, the dataset
  uninstall path — working exactly as before.
- **After a conflict:** the client stays dirty, keeps the user's graph, and offers a reload.
  Nothing is auto-merged and nothing is auto-discarded.
- **Races:** the counter is read and compared under the same lock that performs the write, so
  two saves cannot both pass the check.

---

## 5. UI and UX Requirements

- A conflict raises a toast carrying the sentence from §3.4 and a **Reload** action; the canvas
  is left as the user has it.
- An auto-save that conflicts (a dataset install chaining a save) shows the same toast rather
  than failing quietly — it is the same loss.
- No new control, no new setting, nothing on the happy path: a save that is fine looks exactly
  as it does today.
- The message never says "conflict" alone; it names how much is at stake and the action that
  resolves it.

---

## 6. Edge Cases

- **A spec with no counter** (everything written before this change): reads `0`, and the first
  write makes it `1`. Stated rather than migrated — a migration would rewrite every spec on
  disk to close a window that closes on its own at the first write.
- **A client that sends no basis:** unchecked, as today. Scripts, the e2e stubs and the
  internal caller rely on this.
- **A deliberate "delete everything"** on a stale basis is refused. Reload and delete again;
  the alternative is being unable to tell it from the loss case, which is the point.
- **Outputs-only and name-only updates** carry no spec and are never checked.
- **An evaluation project mid-run:** still refused by its own clause, with its own sentence.
- **Two tabs on one project:** the second save is refused if it would drop what the first
  added; otherwise both land, last-writer-wins on positions, as today.
- **A node whose content the user legitimately clears** on a *current* basis: allowed — the
  check needs staleness too.
- **`spec_revision` in the Projects list** now lags what the detail reports, because the list
  reads the manifest and a background write does not rewrite the manifest. Cosmetic; recorded
  so the next reader does not treat it as a bug.

---

## 7. Testing Strategy

**Unit (the pure rule).** Missing node id → refused; missing edge id → refused; blanked
content → refused; each of those on a *current* basis → allowed; added nodes, moved nodes,
edited content, a deleted-but-loaded node → allowed; no basis → allowed; equal basis →
allowed.

**Storage.** `write_spec` bumps the counter on every call from any domain; a spec with no
counter starts at 1; the counter survives the preserve steps.

**Integration through the routes.** The reproduction of the actual defect: create a project,
write a graph server-side the way an apply does, then `PUT` the empty graph a stale canvas
would send → 409, and the nodes are still there. The same `PUT` with a fresh basis → 200. A
save that adds a node on a stale basis → 200.

**Evaluation.** dev/123's tests keep passing with its graph clause deleted — the general rule
must catch what its special case caught, which is the proof the retirement is safe.

**Frontend.** The basis is captured on load and re-captured after a save; the update body
carries it; a 409 surfaces the sentence and leaves the canvas dirty and unchanged.

Required before this is complete: `tests/test_projects`, `tests/test_agents`,
`tests/test_datasets` and the full jest suite green, plus the reproduction test failing
without the guard.

---

## 8. Acceptance Criteria

1. Every write of a project spec, from any domain, increases a counter in that spec.
2. `GET /api/projects/<id>` reports that counter as `spec_revision`.
3. `PUT /api/projects/<id>` accepts `baseRevision` and, when it is older than the spec on disk
   **and** the incoming graph would drop a node or edge that exists on disk or blank a node's
   content, answers 409 and writes nothing.
4. Every other save behaves exactly as before, including from callers that send no basis.
5. The canvas sends the basis it loaded, adopts the one each save returns, and shows an
   actionable message with a reload on 409, keeping the user's work.
6. The reproduction — load, server-side write, stale save — no longer loses the server's
   write, and there is a test that fails without the guard.
7. `authorization.assert_client_may_replace_graph` no longer holds a graph-loss clause of its
   own, and dev/123's tests still pass.
8. No new agent permission, no change to any review gate, and nothing here lets a model write a
   spec.

---

## 9. Recommended Commit Breakdown

1. The counter in `write_spec`, reported through the project detail, with storage tests.
2. `projects/concurrency.py` — the pure rule and its unit tests.
3. `update_project` + the route + `ProjectUpdate.base_revision`, with the evaluation clause
   retired in the same commit, since it is the same rule moving.
4. The frontend basis and the conflict message, with jest.
5. Docs and the ledgers.

---

## 10. Engineering Quality Checklist

- One rule for graph loss, in one module, called from one place — the evaluation special case
  is removed rather than left beside it.
- The counter lives at the single chokepoint, so a future writer inherits it without knowing.
- The check runs under the lock that performs the write.
- No new frontend state beyond one ref, set at the two points that already sync.
- Refusals name what would be lost and what to do about it.
- Additive on the wire: a caller that sends no basis is unaffected, which is what keeps this
  from breaking scripts and tests.
