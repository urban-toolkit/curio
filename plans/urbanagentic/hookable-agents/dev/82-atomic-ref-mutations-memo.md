# Dev/82 — Atomic dataset-ref mutations (mutate-callback section writer)

Status: implemented (2026-08-18, commit `bfca63d5`; build-log entry BL-P5-20260818-28;
implemented on explicit owner request — the follow-up recorded in BL-P5-20260818-27 /
memo dev/81's implementation notes). Implementation notes: `uninstall_dataset`'s
response (`{"datasets": …}`) now reads the post-mutation list from the writer's returned
spec; the no-op timestamp test observes the project row directly because the project GET
route itself bumps `updated_at` via `touch_last_opened`.

---

## 1. Problem Statement

Every dataset-ref mutation in `datasets/application/mutations.py` is a
read-modify-write split across two lock acquisitions: `installed.list_refs()` reads the
spec (no lock), the caller transforms the list, and `installed.replace_refs()` writes it
back under `spec_write_lock`. Two concurrent mutations of **different** datasets in the
same dataflow can therefore interleave read–read–write–write and lose the first write.

Five sites share the window (line numbers at HEAD `18bcc09f`):

1. `install_dataset` — `mutations.py:564-575` (filter + append; dev/81 Fix 3 semantics).
2. `uninstall_dataset` — `:613-627` (find removed ref, filter, 404 when absent).
3. `publish_dataset`'s ref rewrite — `:327-358` (stamp `publishedToHub`/id-remap, write
   only when changed).
4. `unpublish_dataset`'s ref revert — `:712-731` (clear the flag, write when changed).
5. `delete_dataset`'s cross-dataflow cleanup — `:770-777` (per-dataflow filter, write
   when changed).

This window predates dev/81 (the old `update_project` round-trip had it identically);
dev/81 documented it as a follow-up with the fix shape: move the transform *inside* the
section writer's lock via a mutate callback. Losing an install/uninstall silently
contradicts a user action — the same trust defect class dev/65/81 exist to close.

## 2. Scope

In scope: `projects/storage.py` (mutate-callback primitive; `replace_dataflow_datasets`
reimplemented on top of it), `projects/services.py` (service-level
`mutate_dataflow_datasets`; `replace_dataflow_datasets` delegates),
`datasets/repositories/installed.py` (`mutate_refs`; `replace_refs` delegates),
`datasets/application/mutations.py` (the five call sites), plus tests.

Out of scope: any behavior change at the five sites beyond atomicity (identical results
for serial callers); the frontend; `preserve_dataset_refs` and the save path (already
atomic — they run inside `update_project`'s lock); `migrations._rewrite_spec_ref`
(already locks its own read-modify-write).

## 3. Recommended Implementation Approach

- **Storage primitive** `mutate_dataflow_datasets(user_key, project_id, mutate)`:
  under `spec_write_lock`, read the spec, call `mutate(refs)` with the dict-filtered
  current list, and either persist the returned list or — when the callback returns
  `None` — write nothing. Returns `(spec, changed)`; `None` when the project has no
  spec. `replace_dataflow_datasets` becomes `mutate=lambda _: refs`, keeping one
  lock/read/write path. Callbacks run under the spec lock and must be pure list
  transforms (no re-entrant project I/O) — documented on the primitive.
- **Service** `mutate_dataflow_datasets(user, project_id, mutate)`: resolves the
  project, calls the primitive, bumps the project-row timestamp + commits **only when
  the callback changed something** (a no-op mutation no longer touches "Recent"
  ordering), returns the spec or `None`. `replace_dataflow_datasets` delegates.
- **Repository** `InstalledDatasetRepository.mutate_refs(dataflow_id, mutate)`: 401
  guard, 404 on `None`, returns the spec. `replace_refs` delegates with a constant
  callback (kept — the whole-list API tests and seeding use).
- **Call sites**: each moves its transform into a callback; `uninstall` captures the
  removed ref via closure and returns `None` (no write, no timestamp) when nothing
  matched before raising its 404; publish/unpublish/delete return `None` when
  unchanged, replacing their `if changed:` write guards.

## 4. Data and State Handling

Single writer unchanged (dev/81); this narrows the atomicity unit from "the write" to
"the read-modify-write". No new state; `changed` propagates so no-op mutations skip the
timestamp bump and spec rewrite. The callback contract (list in → list-or-None out) is
the only new interface.

## 5. UI and UX Requirements

None visible. Concurrent installs/uninstalls from two tabs now both land; everything
else renders as before.

## 6. Edge Cases

Concurrent installs of distinct datasets (the named race — both survive); concurrent
install + uninstall of different datasets; uninstall of a never-installed dataset (404,
no write, no timestamp bump); publish/unpublish with no matching ref (no write);
delete cleaning several dataflows while one of them saves; callback raising (lock is
released by the context manager; the exception propagates as before); missing spec file
(`None` → repo 404, unchanged from dev/81).

## 7. Testing Strategy

- `test_projects/test_storage.py`: mutate primitive — callback sees the dict-filtered
  current refs and its result persists; `None` → nothing written, `changed=False`;
  missing project → `None`; **the race regression**: N barrier-synchronized threads
  each appending a distinct ref via `mutate_dataflow_datasets` → all N survive (direct
  port of the deleted `merge_dataflow_dataset_ref` concurrency test).
- `test_dataset_ref_ownership.py`: `mutate_refs` 404s on a missing spec; a no-change
  mutation does not advance the project's `updated_at`.
- Existing suites (`test_install_replace_semantics.py`, ownership, publish, uninstall
  lifecycles) re-run unchanged — they now exercise the new path end-to-end.

## 8. Acceptance Criteria

1. Barrier-synchronized concurrent ref mutations of distinct datasets all persist.
2. All five sites transform inside the lock; no `list_refs` → `replace_refs` pair
   remains in `mutations.py`.
3. Serial behavior is byte-identical (full backend suite green, no test intent changes).
4. A no-op mutation writes nothing and does not bump the project timestamp.

## 9. Recommended Commit Breakdown

1. **Commit 1**: storage + service + repository mutate-callback plumbing, call-site
   conversion, tests (one commit — the primitive and its only consumers land together).
2. **Docs commit**: memo flip + BL-P5 entry.

## 10. Engineering Quality Checklist

- [ ] One lock/read/write path (replace delegates to mutate at every layer).
- [ ] Callback purity documented; no re-entrant lock acquisition.
- [ ] Race covered by a deterministic barrier test, not by inspection.
- [ ] No-op mutations proven side-effect-free.
- [ ] Full backend pytest + datasets suites green.
