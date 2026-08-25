/**
 * memo dev/101 — the drawer's lockfile sync must tell its caller whether the
 * palette/registry need a pulse.
 */
import {
  applyProjectLockfile,
  clearCurrentProject,
  getCurrentProjectPackagesList,
  setCurrentProject,
  subscribe,
} from "../../registry/projectPackagesStore";

describe("applyProjectLockfile", () => {
  beforeEach(() => clearCurrentProject());

  it("returns false and does not notify when the set is unchanged", () => {
    setCurrentProject("p1", ["a.pkg@1", "b.pkg@1"]);
    const listener = jest.fn();
    const off = subscribe(listener);
    expect(applyProjectLockfile(["b.pkg@1", "a.pkg@1"])).toBe(false);
    expect(listener).not.toHaveBeenCalled();
    off();
  });

  it("returns true and replaces the set when the backend has more", () => {
    setCurrentProject("p1", []);
    const listener = jest.fn();
    const off = subscribe(listener);
    expect(applyProjectLockfile(["curio.postits@1"])).toBe(true);
    expect(getCurrentProjectPackagesList()).toEqual(["curio.postits@1"]);
    expect(listener).toHaveBeenCalledTimes(1);
    off();
  });

  it("returns true when the backend has fewer (an uninstall elsewhere)", () => {
    setCurrentProject("p1", ["a.pkg@1", "b.pkg@1"]);
    expect(applyProjectLockfile(["a.pkg@1"])).toBe(true);
    expect(getCurrentProjectPackagesList()).toEqual(["a.pkg@1"]);
  });

  it("keeps the project id", () => {
    setCurrentProject("p1", []);
    applyProjectLockfile(["x.y@1"]);
    expect(getCurrentProjectPackagesList()).toEqual(["x.y@1"]);
  });
});
