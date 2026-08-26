import {
  backupPostureLine,
  permanentDeletionNotice,
  GUEST_COMMINGLING_NOTICE,
} from "../../services/retentionCopy";

/**
 * The copy used to have three states, driven by an operator declaration in
 * `.curio/agents-retention.json`: "no backups", "up to N days", or undeclared.
 * That declaration is gone, so only the honest undeclared line remains - which
 * is what an unconfigured deployment already said.
 */
describe("retentionCopy", () => {
  it("states the backup posture as undeclared, never guessed", () => {
    expect(backupPostureLine()).toContain("has not declared its backup posture");
    expect(backupPostureLine()).toContain("may retain copies");
  });

  it("never claims finality it cannot control", () => {
    // The failure mode this guards: a confident "gone forever" on a deployment
    // whose operator backups say otherwise.
    const line = backupPostureLine();
    expect(line).not.toMatch(/gone|permanent|forever|irreversible/i);
  });

  it("scopes permanence to this deployment's live store", () => {
    const notice = permanentDeletionNotice();
    expect(notice).toContain("this deployment's live store immediately");
    expect(notice).toContain(backupPostureLine());
  });

  it("tells guests their space is shared before they sign in", () => {
    expect(GUEST_COMMINGLING_NOTICE).toContain("single shared guest space");
    expect(GUEST_COMMINGLING_NOTICE).toContain("deletable by");
  });

  it("uses no em or en dashes", () => {
    // House rule for user-facing text.
    for (const text of [
      backupPostureLine(),
      permanentDeletionNotice(),
      GUEST_COMMINGLING_NOTICE,
    ]) {
      expect(text).not.toMatch(/[–—]/);
    }
  });
});
