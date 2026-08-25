# Dev/87 — Decision memo: resolving OQ-008 (retention, deletion, backup expiry, export/reveal, account closure)

Status: **approved by the owner 2026-08-19** — `DEC-057` and `DEC-058` are minted;
OQ-008 is closed. DEC-057's implementation is memo `dev/88` (retention declaration +
ledger sweep + truthful deletion copy + guest notice + `docs/RETENTION.md`), landed the
same day; DEC-058 is the recorded build input for the v2 governance surface. The
production-release block reduces to its mechanical form: the operator declares the
backup posture in `.curio/agents-retention.json` (§3.4). The asks in §6 are answered:
both decisions approved as proposed.

Before this decision, OQ-008 (`dev/03:162`) was the last open question of the hookable-agents program that a
decision can close (OQ-009/OQ-010 are deployment-topology and remote-egress gates with
their own owners). It asks for *"the approved retention, deletion, backup-expiry,
export/reveal, and account-closure rules"* across every agent artifact class, under a
strict honesty guardrail: **never invent durations, never claim irreversible deletion
while backups/caches/protected copies may exist, keep tombstone state truthful, audit
reveal/export, and block production release until the rules are approved.**

This memo follows the dev/85 decision-memo shape: options, evidence, two proposed
decisions, consequences. It changes no code.

---

## 1. What exists today (the artifact inventory, grounded in code)

| Artifact class | Where it lives (DEC-040 FS) | Deletion today |
| --- | --- | --- |
| Chat transcripts / sessions | `<project dir>/…` via `agents/sessions.py` | Lifecycle-bound: `delete_session` on attachment detach ("a transcript lives exactly as long as its attachment"), `clear_turns` on Clear conversation, whole tree on project purge |
| Attachments, proposals, agent defaults | `spec.trill.json` agent sections | Pruned with their node/edge on save; dropped at uninstall; tree on project purge |
| Runtime journal | `<project dir>/runtime/` | Self-limiting (latest-per-node overwrite); tree on project purge |
| Usage ledger | `.curio/users/<key>/agents/ledger/<date>.jsonl` | **Never** — append-only by design (dev/40/DEC-044); holds self-expire at the day boundary, files accumulate indefinitely |
| Imported/materialized definitions | `.curio/users/<key>/agents/…` | Owner-initiated removal (imports delete); materialized built-ins persist |
| Publications | `.curio/agents-catalog/<id>@<ver>/` | `unpublish` rmtrees the shared dir (owner- or operator-initiated) |
| Prompt drafts, eval suites/results, audit records, crypto-shred tombstones, restored copies | **do not exist yet** — the v2 governance surface | n/a (rules must be decided BEFORE that build) |

Three deployment facts shape everything:

1. **`delete_project` soft-deletes by default** (`projects/services.py:702`): the DB row
   is flagged but **every file remains** — transcripts included. Only `purge=True`
   removes the tree. Today's UI language around project deletion is therefore a
   retention statement, not a deletion one.
2. **There is no account-deletion machinery** (no `delete_user` anywhere) and the
   default identity is the **shared guest key** (`guest_shared` → one commingled
   `users/guest/` store): "account closure" is currently an operator action with no
   documented procedure, and guest data is shared by construction.
3. **The platform manages no backups.** Curio is a self-hosted FS-backed deployment;
   whatever backups exist are the operator's, outside the application's deletion
   authority. Any in-app "permanently deleted" claim beyond the live store would
   violate the OQ-008 guardrail.

## 2. Options considered

- **A — hard-coded SaaS-style durations** ("transcripts 90 days, ledgers 7 years").
  Rejected: for a self-hosted research deployment every such number would be exactly
  the *invented duration* the guardrail forbids, and it would purge data the operating
  lab may need.
- **B — leave OQ-008 open.** Rejected: it blocks production release forever and, worse,
  the v2 governance surface (prompt drafts, audits, crypto-shredding) cannot be built
  without these rules — deferral compounds.
- **C — lifecycle-bound deletion + operator-declared retention (recommended → adopted).** Codify
  the lifecycle deletions that already exist as *the* deletion model, make retention
  durations a **deployment-owned declaration** (the `agents-pricing.json` precedent:
  empty by default, honest absence, operator states what is true for their
  deployment), and fix the two places where today's behavior is quietly untruthful
  (soft-delete wording; any irreversibility claims).

## 3. DEC-057 (minted — owner-approved 2026-08-19) — retention, deletion, export, and closure for the shipped artifact classes

**3.1 Lifecycle-bound deletion is the deletion model.** The existing bindings become
policy: transcript ≙ its attachment; attachment ≙ its node/edge/uninstall; journal,
sessions, and agent spec sections ≙ their project; imported definitions ≙ owner
removal; publications ≙ unpublish. Deletion is synchronous removal from the live FS
store within the deleting request — that is the deletion SLA, stated as such.

**3.2 Default retention: until lifecycle or user deletion — no automatic expiry.**
Nothing auto-purges by default, and the platform says so plainly. One deliberate
exception: the **usage ledger stays append-only indefinitely by default** — it is the
billing/audit truth and is never rewritten (corrections append; DEC-044 unchanged).

**3.3 Operator-declared retention config** (implementation: one small unit, §6):
`.curio/agents-retention.json`, absent/empty ≡ the §3.2 defaults. The operator may
declare per-class `maxAgeDays` (e.g. ledger archival age, closed-session sweep age); a
daily/startup sweep enforces only declared values. Ledger files past a declared age are
**archived (moved), never rewritten**. No key invented, no key required.

**3.4 Truthful deletion language (two fixes).** (a) Soft-deleted projects are
**retention**, not deletion: UI copy says "archived — files retained; delete permanently
to remove" and the purge path must be user-reachable wherever soft-delete is offered.
(b) Every permanent-deletion confirmation says "removed from this deployment's live
store" plus the operator's **declared backup posture** — a mandatory field of the
retention config: `backups: "none"` or `backups: {expiryDays: N}`, surfaced verbatim.
The platform never claims irreversibility it doesn't control; an undeclared backup
posture blocks production release (that is OQ-008's gate, made mechanical).

**3.5 Export/reveal scope.** No export endpoints exist today; the standing share rule
becomes policy: **agent-private state never leaves the account** — `strip_agent_state`
on every share (existing, now normative, with its regression suite as the guard). Any
future export is own-account scope only and audit-logged (the DEC-058 audit contract).
Reveal of protected governance content is DEC-058's concern.

**3.6 Account closure and ownership transitions.** Closure is an **operator-executed,
documented procedure** (no self-serve machinery is promised): purge
`.curio/users/<key>/` and the account's DB rows; grace window is operator-declared in
the retention config (default: none). **Publications default to unpublish on closure**
(privacy-first), with an explicit operator override to retain — retained publications
keep their provenance and pass to deployment ownership, never silently to another
user. **Guest reality stated honestly:** the shared `guest_shared` store is commingled
and deletable by any guest session; guest-facing copy must say so, and closure is
inapplicable to it.

## 4. DEC-058 (minted — owner-approved 2026-08-19) — the governance-artifact contract (decided now, built with the v2 surface)

Rules the prompt-editor/quality/audit build must implement; nothing ships before it:

- **Prompt drafts** are owner-private, deleted with their definition; optional
  snapshots/diffs are encrypted per-artifact so **crypto-shredding = key destruction**.
- **Crypto-shred tombstones** are append-only, retained indefinitely as integrity
  anchors, and truthful: they record *that* and *when* content became unrecoverable,
  never the content.
- **Prompt-audit history** is mandatory, append-only, and **survives definition
  deletion as minimized tombstoned metadata** (digests, actors, timestamps — no
  content), preserving DEC-028's integrity chain.
- **Evaluation suites/fixtures/results** are pinned by digest (DEC-028) and deleted
  with their definition, except digests referenced by audit records, which persist as
  metadata.
- **Restored copies** always get a new identity plus a provenance link — a restore
  never silently replaces or resurrects the deleted original.
- **Protected-content reveal and every export** append an audit record (who, what,
  when) before the content is served.

## 5. Consequences if approved

- OQ-008 closes; the production-release block reduces to one mechanical precondition:
  the operator fills the retention declaration (§3.4's backup posture at minimum).
  OQ-009/OQ-010 remain the only open questions, both deployment-gated.
- The v2 governance surface gains its data-lifecycle contract up front — DEC-058 is a
  build input, not a retrofit.
- Implementation of DEC-057 is one small unit (own memo per the standard): the
  retention config + sweep, the soft-delete copy + reachable purge, the
  deletion-confirmation copy, the guest commingling notice, and the documented closure
  procedure in `docs/`. Nothing in this memo changes code.

## 6. The asks — answered

1. **DEC-057 approved** (2026-08-19) as proposed — no per-class default changes
   requested. Implemented in `dev/88` (commits `1bda6dee`/`436487d6`); the closure
   procedure and class tables live in `docs/RETENTION.md`.
2. **DEC-058 approved** (2026-08-19) — recorded as the v2 governance surface's
   data-lifecycle build input (`docs/RETENTION.md` §5 points to §4 here).
