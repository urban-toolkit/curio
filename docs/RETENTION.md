# Retention, deletion, and account closure (DEC-057)

The rules approved by decision memo
[`dev/87`](../plans/urbanagentic/hookable-agents/dev/87-retention-deletion-decision-memo.md)
(owner-approved 2026-08-18; implementation memo `dev/88`). One honesty rule governs
everything here: **the platform never invents retention durations and never claims
irreversible deletion beyond its own live store.** Durations exist exactly when the
deployment operator declares them; backups belong to the operator, not the app.

## 1. Deletion model: lifecycle-bound

Deletion happens synchronously in the deleting request, from this deployment's live
file-system store (`DEC-040`). The bindings:

| Artifact | Deleted when |
| --- | --- |
| Chat transcript / session | its attachment is detached; Clear conversation clears turns; project purge removes the tree |
| Attachments, proposals, agent defaults (spec sections) | their node/edge is deleted (pruned on save); agent uninstall; project purge |
| Runtime journal | self-limiting (latest-per-node); project purge |
| Imported / materialized agent definitions | owner removes the import |
| Publications (`.curio/agents-catalog/`) | owner or operator unpublishes |
| Usage ledger | **never rewritten** — append-only (`DEC-044`); optionally *archived* by age (§2) |

**Projects:** "Archive" is a soft delete — the DB row is flagged, **every file is
retained**. "Delete forever" (purge) removes the project tree. Only the purge is a
deletion; the UI language reflects that.

## 2. The retention declaration

Default retention for everything: **until lifecycle or user deletion — no automatic
expiry.** An operator may declare more via `.curio/agents-retention.json` (path
overridable with `CURIO_AGENT_RETENTION`):

```json
{
  "backups": "none",                       // or {"expiryDays": 30}; REQUIRED for production
  "ledger":  {"archiveAfterDays": 365},    // optional: archive (move) old day files
  "closure": {"graceDays": 14},            // optional: account-closure grace window
  "packageBackend": {"ledgerArchiveAfterDays": 365}  // optional: dev/91 invocation-audit day files
}
```

- Absent/empty file ≡ the defaults above, with the backup posture *undeclared*.
- A startup sweep enforces **only declared values**: ledger day files older than
  `archiveAfterDays` are moved to `ledger/archive/` byte-identically — archived,
  never rewritten. Nothing else is ever auto-purged.
- `packageBackend.ledgerArchiveAfterDays` (memo dev/91) applies the same
  move-never-rewrite archiving to the package backend sandbox's per-package
  invocation-audit day files under `users/<key>/package-backend-ledger/<pkg>/`
  (rows carry handler names, sizes, outcomes, and applied limits — never payloads).
- Unknown keys are logged loudly and NOT applied — a rule nothing enforces is never
  silently accepted.
- The declaration is served on `GET /api/config/public` (`retention`) and drives the
  deletion-confirmation copy: declared-none → "the data is gone"; declared expiry →
  "operator backups may retain a copy for up to N days"; undeclared → said plainly.

**Production-release gate (OQ-008):** production requires at minimum a declared
`backups` posture. Everything else may stay at defaults.

## 3. Export / reveal scope

Agent-private state (attachments, sessions, proposals, defaults) **never leaves the
account**: every flow share passes `strip_agent_state`, guarded by the share
regression suite. No export endpoints exist today; any future export is own-account
scope and audit-logged per the `DEC-058` contract.

## 4. Account closure (operator procedure)

There is no self-serve account deletion. Closure is operator-executed:

1. Wait out the declared `closure.graceDays` (default: none).
2. **Publications**: unpublish the account's entries from `.curio/agents-catalog/`
   (the default). To retain one, record the override — it passes to deployment
   ownership with provenance intact, never silently to another user.
3. Purge the account's store: remove `.curio/users/<key>/` (projects, agents,
   sessions, ledger — the ledger may be archived elsewhere first per the operator's
   own bookkeeping needs).
4. Remove the account's DB rows (user, sessions, project rows).
5. Deletion claims to the departing user follow §2's backup posture.

**Guests:** the shared guest identity (`guest_shared`) is one commingled store —
visible to and deletable by any guest session (the sign-in screen says so). Closure
does not apply to it; the operator may reset it wholesale as a deployment action.

## 5. Governance artifacts (DEC-058 — decided, not yet built)

The v2 governance surface (prompt drafts, evaluation suites, prompt audits,
crypto-shredding) must implement: per-artifact encryption so shredding = key
destruction; append-only tombstones retained indefinitely; audit history surviving
definition deletion as minimized metadata; restored copies minted as new identities
with provenance links; audited reveal/export. See dev/87 §4.
