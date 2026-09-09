# dev/110 — Publications don't record who published them: ownership is inferred from the caller's store, so a same-coordinate importer can republish over another account's entry

**Status: IMPLEMENTED (2026-08-27) — on `feat/agentscatalog`: `ce80668a` (1, store + record + staged swap + `unpublish_all_for`), `de6246ae` (2, record-first authorization + 409 publish-over + `ownedByCaller`), `25fba5a8` (3, backfill tool), `6b78a482`/`ce7cdc63` (4, Global-tab Unpublish + collision note + fixtures), docs in the closing commit. `DEC-069` minted (dev/03), `BL-P3-20260827-15`. Defaults taken: retention stays operator-run (no deletion service path exists in code — `unpublish_all_for` is the documented call); collision note included; DEC minted. Deviation from §3: the staged swap also moves the PREVIOUS entry aside and restores it on a failed rename (stronger than the memo's stated guarantee; test-pinned). Backend agents suite 891 passed; full jest 92/1045. Owner live re-test pending.**

Date: 2026-08-27
Branch / tree: `feat/agentscatalog` @ `e342452a`. Line numbers pinned to that commit.
Origin: the two follow-ups recorded in `BL-P3-20260826-13` / memo `dev/107` — "recorded publisher on publications (closes the republish-over gap)" and "Global-tab Unpublish via `ownedByCaller`" — plus the dev/107 §3 note that materializing published bytes at install is unsafe until ownership is recorded.
Family: `BL-P3-20260720-06` imported-only Publish (`DEC-030`, `REQ-PUBLISH-002`) → dev/36 upload-import (owned definitions) → dev/87/88 retention (`DEC-057`/`DEC-058`: "Publications — owner or operator unpublishes", `docs/RETENTION.md:21,72`) → dev/107 (`_owns_publication` heuristic, Unpublish control).
Design decisions consumed: `DEC-030` (imported-only publish), `DEC-040` (FS-backed stores), `DEC-057`/`DEC-058` (retention posture). **Proposes `DEC-069`**: *a publication carries a publisher record; publish/unpublish/republish authorize against that record, not against the caller's store contents.* Backlog `BL-P3-20260827-15` at closure.

---

## 1. Problem Statement

**Current behavior.** A publication is a bare copy of the definition directory under `.curio/agents-catalog/<agentId>@<version>/` (`publications.py:54-61`). Nothing in that directory says which account published it. Consequently:

1. **Ownership is a heuristic.** `_owns_publication(user_key, coord)` (`services.py:379-390`) returns true when *the caller's own store* holds a `trust=imported` copy of the coordinate that is also in their My Imports. That is a statement about the caller, not about the publication. Two accounts that each uploaded an owned definition under the **same coordinate** (`agent.foo@1.0.0` — coordinates are chosen by the author, not minted) both "own" whichever one is published.
2. **Republish-over is open.** `publish_agent` (`services.py:661-679`) → `publish_from_dir` does an **idempotent overwrite** (`publications.py:57-60`). Account B with its own `agent.foo@1.0.0` can `POST /api/agents/publications` and silently replace account A's published bytes. Every Hub consumer's install of A's agent now runs B's prompt bytes (dev/107 §3 pinned that Hub installs resolve prompt bytes from the shared catalog at run time). This is a **prompt-injection-shaped** gap, not just a tidiness one.
3. **Unpublish is only as strong as the heuristic.** dev/107 fixed the "any store copy" hole, but B in case 1 still passes and can delete A's publication.
4. **The Global tab can't show ownership.** `list_global_catalog` (`services.py:296-313`) has no owner signal, so the Unpublish control lives only on My Imports (dev/107 §2 out-of-scope). A `published: true` Global row for your own agent shows no way to act on it.
5. **Retention can't act automatically.** `docs/RETENTION.md:72` makes "unpublish the account's entries" an operator step because nothing links a publication to an account. With a record, account deletion can sweep its publications.
6. **Materialize-at-install is blocked.** dev/107's follow-up (copy published bytes into the installer's store so Hub installs survive unpublish) would make the installer's copy `trust=imported` → under today's heuristic the installer becomes an "owner". Only a recorded publisher unblocks that.

**Expected behavior.** Each publication carries a small **publisher record** written at publish time. Publish onto an existing coordinate is allowed only for the recorded publisher (same-owner republish = update); otherwise **409** with a message that names the fix (bump the version). Unpublish authorizes against the record. Cards expose `ownedByCaller`, so the Global tab can carry the same Unpublish control as My Imports. Account-deletion retention sweeps the account's publications. Existing publications without a record are handled explicitly (§6), never by guessing.

**Why it matters.** Integrity of the deployment-shared catalog (case 2 lets one account change what every other account runs), correctness of the ownership promise `docs/AGENTS.md` and `docs/RETENTION.md` already make, and unblocking two tracked follow-ups.

## 2. Scope

**Included**
- `app/agents/publications.py` — a `publication.json` **sidecar** next to `manifest.json` in the published directory: `{"schema": 1, "publisherKey": "<user_key>", "publishedAt": "<iso8601>", "sourceDigest": "<sha256 of manifest.json bytes>"}`. Helpers: `read_publication_record(dir_name) -> PublicationRecord | None`, `publish_from_dir(src_dir, dir_name, *, publisher_key)` writes the sidecar atomically with the copy, `unpublish` unchanged, `list_published()` gains a variant returning `(manifest, record)` pairs. The sidecar is **not** part of the definition artifact: `manifest.json` and prompt files are copied byte-identical, so digests, immutability, and `load_agent_manifest` are unaffected (the loader ignores unknown files; verify — §6).
- `app/agents/services.py` — `_owns_publication` becomes record-based; `publish_agent` refuses a foreign-owned coordinate (409) and stamps the record; `unpublish_agent` uses the record; `_manifest_to_card` gains `owned_by_caller` (record.publisherKey == caller, else False); `list_global_catalog` / `list_my_imports` pass it. `remove_import`'s 409 (dev/107) now keys off the record too.
- **Legacy entries** (published before this memo, no sidecar): a one-time **backfill** path — see §6 for the rule; no silent guessing.
- Retention: `docs/RETENTION.md` step 2 becomes automatic **if** an account-deletion service path exists in code; otherwise the memo adds `unpublish_all_for(user_key)` as the callable the operator procedure invokes and documents it. Commit 1 must locate the dev/87/88 deletion sweep (`grep -rn "agents-retention\|ledger-archive\|def delete_account"`) and choose.
- Frontend: `AgentCard.ownedByCaller: boolean`; `AgentRow` renders the dev/107 Unpublish control (same confirm copy, same hook action) on the **Global** tab when `card.published && card.ownedByCaller`; My Imports keeps `publishable` as its guard but also requires `ownedByCaller` when `published` (so an orphaned same-coord duplicate never shows a dead Unpublish).
- `docs/AGENTS.md` (publish/unpublish rows: ownership = recorded publisher; 409 on foreign coordinate), `docs/RETENTION.md` (step 2), `DEC-069`, `BL-P3-20260827-15`.
- Tests (§7).

**Out of scope**
- Materializing published bytes into installers' stores (dev/107 follow-up #3) — **unblocked** by this memo but a separate change with its own storage/retention questions.
- Publication versioning/history, an audit log, moderation, or a "transfer ownership" flow.
- Changing coordinate grammar or minting server-side coordinates (would break `DEC-030`'s immutable-definition story and every existing coordinate).
- Exposing `publisherKey` (an account id) to other users' UIs — `ownedByCaller` is a boolean computed server-side; the key never leaves the backend.
- Node-package catalog (`packages/`) — a different store with its own author model.

## 3. Recommended Implementation Approach

**Record shape** (`publications.py`):
```
@dataclass(frozen=True)
class PublicationRecord:
    schema: int            # 1
    publisher_key: str     # the on-disk user key (str(user.id) or the shared-guest key)
    published_at: str      # ISO-8601 UTC
    source_digest: str     # sha256 of the published manifest.json bytes
```
Written by `publish_from_dir(..., publisher_key=...)`: copy the tree to a temp sibling, write `publication.json`, then atomic rename into place (the current code `rmtree`s the target first — keep that, but stage the new tree fully before the swap so a crash can't leave a copy without a record). `read_publication_record` tolerates a missing/invalid sidecar by returning `None` (legacy). `source_digest` lets a later "is the Hub copy still what I published?" check exist without another migration; it is **not** used for authorization.

**Authorization** (`services.py`):
```
def _publication_owner(coord) -> str | None:   # record.publisher_key, or None for legacy
def _owns_publication(user_key, coord) -> bool:
    owner = _publication_owner(coord)
    if owner is not None:
        return owner == user_key
    return _legacy_owns_publication(user_key, coord)   # today's heuristic, used ONLY for record-less entries
```
- `publish_agent`: existing checks (imported-only, in My Imports) unchanged; then if `is_published(coord)` and `_publication_owner(coord) not in (None, user_key)` → **409** `"<coord> is already published by another account — publish under a new version"`. A same-owner republish overwrites and re-stamps. A **legacy** (record-less) entry being republished by a caller who passes the legacy heuristic gets **claimed**: the record is written with that caller — this is the backfill path (§6).
- `unpublish_agent`: 404 when not published (dev/107), then `_owns_publication` (record-first).
- `remove_import`: unchanged call to `_owns_publication`.

**Cards**: `_manifest_to_card(..., owned_by_caller=bool)` → `ownedByCaller`. Global: `publications`-sourced rows get `_publication_owner(coord) == user_key`; built-in rows `False`. My Imports: same computation when `published`, else `False`.

**Frontend**: `AgentRow` — factor the dev/107 Unpublish button + confirm into a tiny local `UnpublishButton` (still inside `AgentsCatalogDrawer.tsx`; not a shared component — one file, two call sites) and render it for `scope === "global" && card.published && card.ownedByCaller` as well as the existing My Imports branch (guard tightened to `card.published && card.publishable && card.ownedByCaller`). `CatalogPublishPill` untouched.

**Shared guest**: all shared-guest users map to one `user_key` (`_user_dir_key`, `projects/services.py:100-101`). A publication by any shared guest is therefore owned by *all* shared guests. This is the existing, documented guest-commingling reality (`GUEST_COMMINGLING_NOTICE`, DEC-057 §3.6) — the record makes it explicit rather than worse. Note it in `docs/AGENTS.md`; no special-casing.

**No new abstraction beyond the record**: no DB table (publications are FS-backed by `DEC-040`; the sidecar stays with the artifact and is swept with it), no ACL system.

## 4. Data and State Handling

- **Source of truth for ownership**: `publication.json` in the published directory. The caller's store contents are no longer consulted when a record exists.
- **Derived**: `published` (unchanged — directory presence), `ownedByCaller` (record vs caller), `publishable` (unchanged — caller's store trust).
- **Publish**: stage → swap → record present. Response unchanged (`{coord, published: true}`); add `ownedByCaller: true` for symmetry (optional).
- **Republish by owner**: overwrite + re-stamp `publishedAt`/`sourceDigest`. Consumers' next list refresh sees the new bytes (as today).
- **Republish by non-owner**: 409, nothing written.
- **Unpublish**: `rmtree` removes the record with the artifact — no orphaned records possible.
- **Frontend**: `useAgentsCatalogDrawer.run()` already refreshes all scopes after unpublish; the Global row disappears and the My Imports badge flips, as in dev/107. A 409 from a foreign-coordinate publish surfaces in the banner verbatim (existing error path).
- **Race**: two accounts publishing the same new coordinate simultaneously — the staged-swap makes the last rename win *with its own record*, so exactly one owner is recorded and the other's later actions get 409. Acceptable for an FS store; note in §6.

## 5. UI and UX Requirements

- Global tab: an owned published row shows `Published` badge + `Unpublish` (identical control, copy, and confirm to My Imports). Non-owned published rows show the badge only.
- My Imports: unchanged appearance; `Unpublish` additionally requires `ownedByCaller`.
- Publish onto a coordinate another account already published: the pill click yields the banner `"… is already published by another account — publish under a new version"`; the row is unchanged.
- No new pills, icons, or tooltips beyond the existing ones; no per-row publisher name (the key is not user-facing).
- Accessibility: unchanged (same button, same confirm).

## 6. Edge Cases

- **Legacy publications (no sidecar)** — the important one. Rule: `_owns_publication` falls back to the dev/107 heuristic **only** for record-less entries; the first owner-passing publish **or unpublish** stamps/claims the record (unpublish removes it anyway). Operator tooling: a `python -m utk_curio.tools.backfill_publications` script that, for each record-less entry, searches `.curio/users/*/agents/<coord>/manifest.json` for a byte-identical `trust=imported` copy and writes the record when **exactly one** account matches; logs and leaves alone (no record) when zero or several match. Never guesses.
- **Same-coordinate collision between two owned uploads** (the case that motivates this memo): A publishes first → record A. B publishes → 409 with "bump the version". B's own My Imports row shows `published: true` (directory exists) but `ownedByCaller: false` → **no Unpublish, and the Publish pill is hidden by `published`** — B sees a `Published` badge for something they don't own. Add `title` copy on the badge for that case? `CatalogPublishPill` is shared; instead render a small muted note under the tags on My Imports when `published && !ownedByCaller`: "Published by another account under this coordinate — bump your version to publish." One line, agents drawer only.
- **Manifest loader and unknown files**: `load_agent_manifest(dir)` must ignore `publication.json`; and the prompt-asset loader must not treat it as a prompt. Verify in commit 1 with a test that a published dir with the sidecar still loads and resolves prompt bytes.
- **Record present but publisher account deleted**: the publication persists (`RETENTION.md` step 2 is the sweep). If the sweep is automated by this memo, this state can't arise for new deletions; legacy orphans are handled by the operator procedure.
- **Corrupt sidecar**: treated as absent (legacy path) and logged at WARNING; the artifact still lists. A corrupt sidecar must never block unpublish by the true owner — the legacy heuristic still lets the owner through and the unpublish removes the corrupt file.
- **Shared guest**: one key for all guests — publication by a guest is owned by every guest. Documented; not a regression.
- **Path traversal / grammar**: unchanged — the sidecar lives inside `published_agent_dir(dir_name)` which already enforces containment.
- **Digest mismatch** (Hub copy differs from `sourceDigest`): not enforced; informational for a future integrity check.
- **Concurrent publish of a new coord by two accounts**: last rename wins with its record; loser gets 409 on later actions. Acceptable; documented.

## 7. Testing Strategy

**Backend — `tests/test_agents/test_publications.py`** (unit, FS):
1. `publish_from_dir(..., publisher_key="7")` writes `publication.json` with schema 1, key, ISO timestamp, digest of the copied manifest.
2. `read_publication_record` → record; on a record-less dir → `None`; on corrupt JSON → `None` + warning.
3. `load_agent_manifest` on a published dir with the sidecar succeeds; prompt-asset resolution ignores it.
4. `unpublish` removes the record with the directory.
5. Staged swap: after publish over an existing entry, the directory never exists without a record (assert no intermediate state by checking the final tree; a crash-injection test via monkeypatched `os.replace` raising → old entry intact).

**Backend — `tests/test_agents/test_routes.py` `TestPublish`** (with the `bob_and_token` fixture from dev/107):
6. Alice publishes `agent.my-custom@1.0.0`; Bob uploads his own `agent.my-custom@1.0.0` (trust=imported, in his imports) and `POST /publications` → **409** naming "another account"; catalog still serves Alice's bytes (assert a distinguishing field, e.g. `purpose`).
7. Bob `DELETE /publications/<coord>` → 403; Alice → 200.
8. Alice republishes (changed purpose) → 201; catalog reflects the change; record re-stamped (`publishedAt` advances).
9. Global catalog cards: `ownedByCaller` true for Alice's row when Alice lists, false when Bob lists; built-ins false.
10. My Imports: Bob's colliding row → `published: true, ownedByCaller: false`; Alice's → `true, true`.
11. Legacy: create a published dir **without** a sidecar for Alice's coord; Alice `DELETE` → 200 (heuristic path); Bob (with a built-in-materialized copy of the same coord, the dev/107 scenario) → 403; a legacy republish by Alice stamps the record.
12. `remove_import` 409 still keys off ownership (record present, owner) and lets a non-owner drop their import.
13. If the retention sweep is wired: deleting Alice's account removes her publications and nobody else's.

**Backfill tool — `tests/test_agents/test_backfill_publications.py`**:
14. Exactly-one-match → record written; zero or two matches → untouched + logged.

**Frontend — `src/tests/catalog/AgentsCatalogDrawer.test.tsx`**:
15. Global tab: `published && ownedByCaller` row shows one `Unpublish`; `published && !ownedByCaller` shows none; click → confirm → `api.unpublish` → all-scope refresh (reuse dev/107 helpers).
16. My Imports: `published && publishable && !ownedByCaller` → no Unpublish, the "published by another account" note renders; with `ownedByCaller` → Unpublish, no note.
17. `api.publish` rejecting with the 409 message → banner shows it verbatim.

**Regression**: full `pytest tests/test_agents`, full `npx jest`; `tsc` clean in touched files.

## 8. Acceptance Criteria

- Every new publication directory contains `publication.json` with the publisher's key; unpublish removes it with the artifact.
- `POST /api/agents/publications` for a coordinate published by another account returns 409 with the "publish under a new version" message and writes nothing; the same owner may republish.
- `DELETE /api/agents/publications/<coord>` authorizes against the record; legacy record-less entries fall back to the dev/107 heuristic and get stamped on the owner's next publish.
- `AgentCard.ownedByCaller` is present on Global and My Imports cards; the Global tab shows Unpublish only for owned published rows; My Imports shows the collision note for `published && !ownedByCaller`.
- The publisher key never appears in any API response or UI; only the boolean does.
- Legacy backfill tool writes records only on an exact single match.
- `docs/AGENTS.md` and `docs/RETENTION.md` describe the record and (if wired) the automatic sweep; `DEC-069` minted; tests 1–17 pass; full suites green.

## 9. Recommended Commit Breakdown

1. **Record + store** — `PublicationRecord`, sidecar write/read, staged swap, loader-ignores-sidecar; tests 1–5. `publish_from_dir` gains the required `publisher_key` (callers updated in the same commit).
2. **Authorization + cards** — record-first `_owns_publication`, 409 on foreign coordinate, `ownedByCaller` on cards; tests 6–12.
3. **Legacy backfill tool** — `utk_curio/tools/backfill_publications.py` + test 14; retention sweep wiring **or** the documented callable (+ test 13 if wired).
4. **Frontend** — `ownedByCaller` type, Global-tab Unpublish via the factored button, collision note; tests 15–17.
5. **Docs** — `DEC-069`, `docs/AGENTS.md`, `docs/RETENTION.md`, `BL-P3-20260827-15`, memo → IMPLEMENTED.

## 10. Engineering Quality Checklist

- No duplicated logic: one `_owns_publication`, one Unpublish button factored for two call sites, the heuristic retained only as the legacy fallback with a clear name.
- Types: `PublicationRecord` dataclass; `ownedByCaller: boolean` on `AgentCard`.
- Separation: store (sidecar I/O) / service (authorization) / card mapping / UI.
- State predictable: record written atomically with the artifact; never an artifact without a record after this ships.
- UI consistent: reuses dev/107's control and copy verbatim.
- Error states: 409/403/404 messages name the fix; banner path already exists.
- Privacy: account ids stay server-side.
- Tests: FS unit, route integration incl. two-account scenarios, legacy path, backfill, frontend.
- Conventions: memo → pathspec commits, no trailer, no push; `plans/` tracked on this branch; `DEC` numbering — verify `DEC-069` is the next free id in the decisions register before minting.
- Performance: one small JSON read per published row on list — negligible against `load_agent_manifest` already done per row.

## Open questions for the owner (non-blocking — defaults stated)

- **Retention sweep**: automate account-deletion unpublish now (default **yes, if** a deletion service path exists in code — commit 1 checks) or keep it an operator step with a documented callable.
- **Collision note on My Imports** (§6, one muted line) — default **include**; say "skip" to leave the bare badge.
- **`DEC-069`** — default mint it; this changes what "owner" means for a shared resource and future memos will cite it.
