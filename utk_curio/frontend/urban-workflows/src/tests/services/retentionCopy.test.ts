import {
  setRetentionDeclaration,
  backupPostureLine,
  permanentDeletionNotice,
  GUEST_COMMINGLING_NOTICE,
} from "../../services/retentionCopy";

describe("retentionCopy (DEC-057, dev/88)", () => {
  afterEach(() => setRetentionDeclaration(null));

  it("undeclared posture is stated as undeclared — never guessed", () => {
    expect(backupPostureLine()).toContain("has not declared its backup posture");
    expect(backupPostureLine()).toContain("may retain copies");
  });

  it("a declared no-backups posture states finality", () => {
    setRetentionDeclaration({ backups: "none" });
    expect(backupPostureLine()).toBe(
      "This deployment declares no backups: once deleted here, the data is gone.",
    );
  });

  it("a declared expiry window states the number verbatim", () => {
    setRetentionDeclaration({ backups: { expiryDays: 30 } });
    expect(backupPostureLine()).toContain("up to 30 days after deletion");
  });

  it("invalid declarations degrade to undeclared", () => {
    setRetentionDeclaration({ backups: { expiryDays: -3 } });
    expect(backupPostureLine()).toContain("has not declared");
    setRetentionDeclaration({ backups: "always" });
    expect(backupPostureLine()).toContain("has not declared");
    setRetentionDeclaration("garbage");
    expect(backupPostureLine()).toContain("has not declared");
  });

  it("the permanent-deletion notice scopes the claim to the live store", () => {
    setRetentionDeclaration({ backups: "none" });
    const notice = permanentDeletionNotice();
    expect(notice).toContain("this deployment's live store immediately");
    expect(notice).toContain("the data is gone");
  });

  it("re-seeding replaces the prior declaration", () => {
    setRetentionDeclaration({ backups: "none" });
    setRetentionDeclaration({ backups: { expiryDays: 7 } });
    expect(backupPostureLine()).toContain("up to 7 days");
  });

  it("the guest notice states the shared-store reality plainly", () => {
    expect(GUEST_COMMINGLING_NOTICE).toContain("shared guest space");
    expect(GUEST_COMMINGLING_NOTICE).toContain("deletable by");
  });
});
