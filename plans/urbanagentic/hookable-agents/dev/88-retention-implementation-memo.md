# Dev/88 — DEC-057 implemented: retention declaration, ledger sweep, truthful deletion copy, guest notice, closure procedure

Status: implemented (2026-08-19, commits `1bda6dee` backend / `436487d6` frontend;
build-log entry BL-P5-20260819-32; on the owner's DEC-057 approval — dev/87 §3 is the
authoritative contract). DEC-058 remains the build input for the future governance
surface — no code. No deviations from §3; one grounding note: the Archive /
Delete-forever split already existed in `ProjectsList.tsx`, so §3.4(a) needed only the
confirmation copy, exactly as §1 predicted.

---

## 1. Problem Statement (delta from dev/87)

Four gaps between DEC-057 and today's code: (1) no retention declaration exists — the
operator cannot state backup posture or a ledger archival age, so the production gate
has no mechanical form; (2) permanent-deletion confirmations ("Permanently delete
X?", the dataset drawer's "permanently removes") claim more than the platform controls
— no live-store scoping, no backup-posture line; (3) guests are never told the
`guest_shared` store is commingled; (4) no documented closure procedure. Already
satisfied: the Archive / Delete-forever split in `ProjectsList.tsx:88-104` (§3.4a's
reachable purge exists; only the copy needs fixing).

## 2. Scope

Backend: new `agents/retention.py` (declaration load + public shape + ledger sweep),
startup wiring in `backend/server.py`, `GET /api/config/public` gains a `retention`
block (`users/routes.py`). Frontend: `services/retentionCopy.ts` (module cache + copy
builders), UserProvider bootstrap seeds it, `ProjectsList` + dataset-drawer delete
confirmations adopt it, guest-commingling line in `AltAuthBox`. Docs:
`docs/RETENTION.md` (classes, config schema, closure procedure, guest reality) +
pointers. Out: any automatic purge beyond the declared ledger archival (nothing
declared = nothing swept — DEC-057 §3.2/§3.3); session/journal sweeps (no declared
class; add only when an operator declares one); DEC-058 artifacts.

## 3. Approach

- **`agents/retention.py`** (the `pricing.py` pattern: `.curio/agents-retention.json`,
  env-overridable `CURIO_AGENT_RETENTION`, read-per-call, missing/corrupt ≡ `{}`):
  schema `{"backups": "none"|{"expiryDays": N}, "ledger": {"archiveAfterDays": N},
  "closure": {"graceDays": N}}`; unknown top-level keys log a warning naming them
  (declared-but-unenforced must be loud, never silent). `public_declaration()` returns
  `{backups, ledgerArchiveAfterDays, closureGraceDays}` with `null` for undeclared.
  `run_retention_sweep()`: only when `ledger.archiveAfterDays` is declared, MOVE (never
  rewrite) `users/*/agents/ledger/<YYYY-MM-DD>.jsonl` files older than the age into
  `ledger/archive/`; date from the filename; best-effort, logged, never raises;
  returns a summary. Wired at server startup beside `reconcile_guest_projects`.
- **`/api/config/public`** carries `retention: public_declaration()` — the existing
  bootstrap fetch, no new endpoint.
- **`services/retentionCopy.ts`**: `setRetentionDeclaration(cfg.retention)` (called
  from the UserProvider bootstrap), `backupPostureLine()` — declared-none → "this
  deployment declares no backups…", declared-expiry → "operator backups may retain a
  copy for up to N days after deletion", undeclared → the honest default "this
  deployment has not declared its backup posture — operator backups may retain
  copies"; `permanentDeletionNotice()` prefixes the live-store scope sentence.
  Consumers append it to their existing `window.confirm` text — no new UI surface.
- **Guest notice**: one sentence under AltAuthBox's Continue-as-Guest button — guest
  work is shared/commingled and deletable by any guest session.
- **Docs**: `RETENTION.md` = the DEC-057 tables (artifact classes + lifecycle
  bindings, config schema, the operator closure procedure incl. unpublish-by-default
  and the grace window, the guest reality, the production-gate checklist).

## 4–8. Data/edge cases/tests/acceptance (delta only)

No new state beyond the declaration file (operator-owned) and the module cache (set
once at bootstrap; consumers degrade to the undeclared line if never set). Edge cases:
corrupt/absent config ≡ defaults; archive dir collisions (skip + log, never
overwrite); non-date ledger filenames skipped; `.lock` untouched; sweep with no users
dir = no-op. Tests — backend `test_retention.py`: declaration parsing (absent, corrupt,
unknown-key warning, public shape), sweep (undeclared = no file moves; declared moves
only past-age files into archive byte-identically, never touches `.lock`/recent
files); config route carries the block. Frontend: `retentionCopy` unit tests (three
posture lines + notice composition + unset default); ProjectsList/AltAuthBox render
assertions if suites exist, else covered by the copy unit tests. Acceptance: suites
green; the confirm dialogs carry the notice; `/api/config/public` shows `retention`;
an operator file with `ledger.archiveAfterDays` moves old ledger files on startup.

## 9. Commit order

1. **Commit 1 — backend**: `retention.py` + startup sweep wiring + `/config/public`
   block + `test_retention.py`.
2. **Commit 2 — frontend**: `retentionCopy.ts` + bootstrap seeding + the two confirm
   adoptions + guest notice + tests.
3. **Docs commit**: `docs/RETENTION.md` + AGENTS.md pointer + dev/87 flip (approved,
   asks answered) + this memo flip + BL-P5 entry + dev/03 OQ-008 row closed.

## 10. Checklist

- [ ] No invented durations anywhere: undeclared = no expiry + honest undeclared copy.
- [ ] Ledger files are moved, never rewritten; append-only survives archival.
- [ ] Unknown declaration keys are loud.
- [ ] Deletion copy claims only the live store; posture line always present.
- [ ] Suites green before each commit.
