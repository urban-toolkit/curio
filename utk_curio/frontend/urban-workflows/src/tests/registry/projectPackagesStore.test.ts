/**
 * memo dev/101 — the drawer's lockfile sync must tell its caller whether the
 * palette/registry need a pulse.
 */
import {
  applyProjectLockfile,
  clearCurrentProject,
  getCurrentProjectPackagesList,
  getPackagesRevision,
  setCurrentProject,
  setCurrentProjectPackages,
  subscribe,
} from "../../registry/projectPackagesStore";

/** A read that started now, i.e. one nothing has raced. */
const fresh = () => getPackagesRevision();

describe("applyProjectLockfile", () => {
  beforeEach(() => clearCurrentProject());

  it("returns false and does not notify when the set is unchanged", () => {
    setCurrentProject("p1", ["a.pkg@1", "b.pkg@1"]);
    const listener = jest.fn();
    const off = subscribe(listener);
    expect(applyProjectLockfile(["b.pkg@1", "a.pkg@1"], fresh())).toBe(false);
    expect(listener).not.toHaveBeenCalled();
    off();
  });

  it("returns true and replaces the set when the backend has more", () => {
    setCurrentProject("p1", []);
    const listener = jest.fn();
    const off = subscribe(listener);
    expect(applyProjectLockfile(["curio.postits@1"], fresh())).toBe(true);
    expect(getCurrentProjectPackagesList()).toEqual(["curio.postits@1"]);
    expect(listener).toHaveBeenCalledTimes(1);
    off();
  });

  it("returns true when the backend has fewer (an uninstall elsewhere)", () => {
    setCurrentProject("p1", ["a.pkg@1", "b.pkg@1"]);
    expect(applyProjectLockfile(["a.pkg@1"], fresh())).toBe(true);
    expect(getCurrentProjectPackagesList()).toEqual(["a.pkg@1"]);
  });

  it("keeps the project id", () => {
    setCurrentProject("p1", []);
    applyProjectLockfile(["x.y@1"], fresh());
    expect(getCurrentProjectPackagesList()).toEqual(["x.y@1"]);
  });
});

describe("applyProjectLockfile — a read that lost a race", () => {
  beforeEach(() => clearCurrentProject());

  it("is refused when a local write landed while it was in flight", () => {
    // The reported shape: install a package (the store gains it), and the
    // reload that follows refetches a lockfile that was read BEFORE the
    // install committed. Applying it would remove a package that is installed,
    // dropping it from the palette and unmounting anything anchored to its row
    // — which is how the package metadata modal died mid-open.
    setCurrentProject("p1", ["a.pkg@1"]);
    const readStartedAt = getPackagesRevision();

    // ... the install response lands first.
    setCurrentProjectPackages(["a.pkg@1", "just.installed@1"]);

    // ... then the stale read arrives, without it.
    expect(applyProjectLockfile(["a.pkg@1"], readStartedAt)).toBe(false);
    expect(getCurrentProjectPackagesList()).toEqual(["a.pkg@1", "just.installed@1"]);
  });

  it("still applies a read that nothing raced", () => {
    // The guard must not stop the drawer following the server in the ordinary
    // case — an uninstall in another tab still has to reach this one.
    setCurrentProject("p1", ["a.pkg@1", "b.pkg@1"]);
    const readStartedAt = getPackagesRevision();
    expect(applyProjectLockfile(["a.pkg@1"], readStartedAt)).toBe(true);
    expect(getCurrentProjectPackagesList()).toEqual(["a.pkg@1"]);
  });

  it("counts every kind of local write, not just package edits", () => {
    // Switching dataflow mid-read is the same hazard: the reply describes the
    // dataflow that is no longer open.
    setCurrentProject("p1", ["a.pkg@1"]);
    const readStartedAt = getPackagesRevision();
    setCurrentProject("p2", ["c.pkg@1"]);
    expect(applyProjectLockfile(["a.pkg@1"], readStartedAt)).toBe(false);
    expect(getCurrentProjectPackagesList()).toEqual(["c.pkg@1"]);
  });

  it("lets the second of two concurrent reads lose", () => {
    setCurrentProject("p1", []);
    const bothReadAt = getPackagesRevision();
    expect(applyProjectLockfile(["first@1"], bothReadAt)).toBe(true);
    // The second read is no newer than the first, and the first has moved the
    // store on, so it does not get to overwrite it.
    expect(applyProjectLockfile(["second@1"], bothReadAt)).toBe(false);
    expect(getCurrentProjectPackagesList()).toEqual(["first@1"]);
  });
});
