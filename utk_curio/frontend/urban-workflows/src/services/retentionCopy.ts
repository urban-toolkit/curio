/**
 * DEC-057 truthful-deletion copy (memos dev/87/88).
 *
 * The platform never claims irreversibility it doesn't control: permanent
 * deletion removes data from THIS deployment's live store, and whether a
 * backup copy outlives that is the operator's declaration
 * (`.curio/agents-retention.json`, served on `/api/config/public` as
 * `retention`). Undeclared is stated as undeclared — never guessed.
 *
 * The declaration is seeded once from the UserProvider bootstrap; before (or
 * without) seeding, the copy degrades to the honest undeclared line.
 */

export type BackupPosture = "none" | { expiryDays: number } | null;

let declaredBackups: BackupPosture = null;

/** Parse + cache the bootstrap config's `retention` block. */
export function setRetentionDeclaration(retention: unknown): void {
  declaredBackups = null;
  if (!retention || typeof retention !== "object") return;
  const backups = (retention as { backups?: unknown }).backups;
  if (backups === "none") {
    declaredBackups = "none";
    return;
  }
  if (backups && typeof backups === "object") {
    const days = (backups as { expiryDays?: unknown }).expiryDays;
    if (typeof days === "number" && Number.isInteger(days) && days > 0) {
      declaredBackups = { expiryDays: days };
    }
  }
}

/** The operator's backup posture, stated honestly. */
export function backupPostureLine(): string {
  if (declaredBackups === "none") {
    return "This deployment declares no backups: once deleted here, the data is gone.";
  }
  if (declaredBackups !== null) {
    return (
      `Operator backups may retain a copy for up to ${declaredBackups.expiryDays} ` +
      "days after deletion."
    );
  }
  return (
    "This deployment has not declared its backup posture — operator backups " +
    "may retain copies."
  );
}

/** The sentence every permanent-deletion confirmation carries (DEC-057 §3.4b). */
export function permanentDeletionNotice(): string {
  return (
    "This removes it from this deployment's live store immediately. " +
    backupPostureLine()
  );
}

/** The guest-store reality (DEC-057 §3.6), stated where guests sign in. */
export const GUEST_COMMINGLING_NOTICE =
  "Guest work is stored in a single shared guest space: it is visible to, and " +
  "deletable by, anyone using this deployment as a guest.";
