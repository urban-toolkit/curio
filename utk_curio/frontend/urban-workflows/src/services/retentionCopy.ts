/**
 * Truthful-deletion copy.
 *
 * The platform never claims irreversibility it does not control: permanent
 * deletion removes data from THIS deployment's live store, and whether a
 * backup copy outlives that is not something Curio can know.
 *
 * An operator could once declare a backup posture in
 * `.curio/agents-retention.json`, served on `/api/config/public`, and this
 * module would say "no backups" or "up to N days" instead. That declaration is
 * gone, so the copy is always the undeclared line - which is what an
 * undeclared deployment already said, and what most of them were.
 */

/** The operator's backup posture, stated honestly: we do not know it. */
export function backupPostureLine(): string {
  return (
    "This deployment has not declared its backup posture, so operator " +
    "backups may retain copies."
  );
}

/** The sentence every permanent-deletion confirmation carries. */
export function permanentDeletionNotice(): string {
  return (
    "This removes it from this deployment's live store immediately. " +
    backupPostureLine()
  );
}

/** The guest-store reality, stated where guests sign in. */
export const GUEST_COMMINGLING_NOTICE =
  "Guest work is stored in a single shared guest space: it is visible to, and " +
  "deletable by, anyone using this deployment as a guest.";
