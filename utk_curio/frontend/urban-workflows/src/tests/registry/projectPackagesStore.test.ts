/**
 * memo dev/101 — the drawer's lockfile sync must tell its caller whether the
 * palette/registry need a pulse.
 */
import {
  applyProjectLockfile,
  beginProjectLoad,
  clearCurrentProject,
  getCurrentProjectPackagesList,
  getPackagesRevision,
  setCurrentProject,
  setCurrentProjectPackages,
  settleProjectLoad,
  setUnsavedDataflow,
  subscribe,
  whenProjectSettled,
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

/**
 * The route-load latch (#340).
 *
 * Its whole job is to tell "this dataflow has never been saved" apart from
 * "this dataflow's load has not landed yet", in the same tick the route
 * resolves. Everything that saves reads it, so the lifecycle has to be exact:
 * a latch left open stalls saves, and one released early is the bug back.
 */
describe("project load latch", () => {
  beforeEach(() => clearCurrentProject());

  /**
   * Did ``p`` resolve once everything already queued has run?
   *
   * A microtask race is too tight to answer that: releasing the latch resolves
   * through two ``then``s of its own, so a one-tick race reports "pending" for
   * a promise that is about to resolve. A zero-delay timer drains all of them
   * while still leaving a real timer (the 15s bound) unfired.
   */
  const settledSoon = async (p: Promise<void>) => {
    let done = false;
    void p.then(() => {
      done = true;
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    return done ? "settled" : "pending";
  };

  it("resolves immediately when nothing is loading", async () => {
    setCurrentProject("p1", []);
    await expect(whenProjectSettled()).resolves.toBeUndefined();
  });

  it("holds until the load settles", async () => {
    setCurrentProject("p1", []);
    beginProjectLoad("p1");
    const waiting = whenProjectSettled();
    expect(await settledSoon(waiting)).toBe("pending");
    settleProjectLoad("p1");
    expect(await settledSoon(waiting)).toBe("settled");
  });

  it("ignores a settle from a load that no longer owns the latch", async () => {
    // A navigation overtook a slow load. Releasing on the old id would hand
    // waiters an answer about a dataflow that is no longer on screen.
    beginProjectLoad("p1");
    beginProjectLoad("p2");
    const waiting = whenProjectSettled();
    settleProjectLoad("p1");
    expect(await settledSoon(waiting)).toBe("pending");
    settleProjectLoad("p2");
    expect(await settledSoon(waiting)).toBe("settled");
  });

  it("releases waiters when the route leaves for an unsaved dataflow", async () => {
    // Otherwise every save on the new canvas waits out the full bound first.
    beginProjectLoad("p1");
    const waiting = whenProjectSettled();
    setUnsavedDataflow([]);
    expect(await settledSoon(waiting)).toBe("settled");
  });

  it("gives up after the bound rather than waiting forever", async () => {
    jest.useFakeTimers();
    try {
      beginProjectLoad("p1");
      const waiting = whenProjectSettled(50);
      jest.advanceTimersByTime(50);
      await expect(waiting).resolves.toBeUndefined();
    } finally {
      jest.useRealTimers();
    }
  });

  it("re-entering the same load does not restart the wait", async () => {
    // StrictMode mounts the effect twice; the second call must not replace a
    // latch the first one's load is about to settle.
    beginProjectLoad("p1");
    const waiting = whenProjectSettled();
    beginProjectLoad("p1");
    settleProjectLoad("p1");
    expect(await settledSoon(waiting)).toBe("settled");
  });
});
