/**
 * Singleton store of the *currently-loaded project's* lockfile.
 *
 * The palette filters by intersection with this set so two projects open
 * in different tabs / sessions see different palettes even though they
 * share one user package store. See ``docs/NODE-CATALOG.md`` § "Per-project
 * lockfile".
 *
 * Three scopes, not two. ``projectId === undefined`` used to mean both "no
 * dataflow is open" and "a dataflow is open but has never been saved", and both
 * resolved to *no filter at all* — which is why a new dataflow inherited the
 * palette of whatever was open before it (#204, #220). An unsaved dataflow is a
 * dataflow: it has a package set (the account defaults the backend will seed on
 * first save), and the palette must honour it.
 *
 * Writers:
 *  - {@link ProjectLoader} on project load → ``setCurrentProject``
 *  - {@link ProjectLoader} on ``/dataflow/new`` → ``setUnsavedDataflow``
 *  - {@link NodeCatalogDrawer} install / uninstall handlers → ``setCurrentProjectPackages``
 *  - On the project-list / catalog pages (no dataflow at all):
 *    ``clearCurrentProject`` (palette shows everything)
 *
 * Readers:
 *  - {@link loadInstalledPackages} reads ``getCurrentProjectPackages`` to filter.
 *  - {@link TrillGenerator} callers read the packages list to persist into the spec.
 */

export type ProjectPackages = {
  /**
   * ``'dataflow'`` - a dataflow is open (saved or not) and ``packages`` is its
   * set. ``'none'`` - no dataflow is open, so there is nothing to filter by and
   * the palette shows everything installed.
   *
   * Carried separately from ``projectId`` because an unsaved dataflow has no id
   * yet and still has a package set.
   */
  kind: 'dataflow' | 'none';
  /** ``undefined`` while the dataflow is unsaved; the backend mints it on first save. */
  projectId: string | undefined;
  /** dirNames in the dataflow's lockfile. Meaningless when ``kind === 'none'``. */
  packages: ReadonlySet<string>;
};

type Listener = () => void;

const _listeners = new Set<Listener>();

let _state: ProjectPackages = {
  kind: 'none',
  projectId: undefined,
  packages: new Set(),
};

/**
 * Bumped by every LOCAL write below, never by a server read that is applied
 * through {@link applyProjectLockfile}. That asymmetry is the whole point: it
 * lets a read tell whether the world moved under it while it was in flight.
 */
let _revision = 0;

export function setCurrentProject(projectId: string, packages: Iterable<string>): void {
  const next = new Set(packages);
  // ``ProjectLoader`` pins the id with an EMPTY set before the spec loads, so
  // the palette knows it is in a dataflow while the lockfile is still in
  // flight. With the filter applied on READ, that empty set is immediately
  // visible as "only the builtin package" -- so re-pinning a dataflow already
  // in the store (a remount, a navigation back onto the same canvas) would
  // blank its palette until the load finished. Keep what is known instead.
  if (next.size === 0 && _state.projectId === projectId && _state.packages.size > 0) {
    _state = { kind: 'dataflow', projectId, packages: _state.packages };
  } else {
    _state = { kind: 'dataflow', projectId, packages: next };
  }
  _revision += 1;
  _notify();
}

/**
 * A dataflow is open but has not been saved, so it has no id yet.
 *
 * Seed it with what the backend will merge into its lockfile on first save (the
 * account defaults), so the palette shows the same thing before and after that
 * save instead of showing everything the account owns until then.
 */
export function setUnsavedDataflow(packages: Iterable<string>): void {
  // Leaving a routed dataflow for an unsaved one: any load still in flight is
  // no longer what the app is on, and waiting for it would stall every save on
  // this canvas until the timeout.
  _abandonLoad();
  _state = { kind: 'dataflow', projectId: undefined, packages: new Set(packages) };
  _revision += 1;
  _notify();
}

export function setCurrentProjectPackages(packages: Iterable<string>): void {
  // Same dataflow, new package set - drawer install / uninstall path, and the
  // defaults arriving for an unsaved dataflow. Keeps the current kind: calling
  // this before a dataflow is open must not silently open one.
  _state = { kind: _state.kind, projectId: _state.projectId, packages: new Set(packages) };
  _revision += 1;
  _notify();
}

export function clearCurrentProject(): void {
  _abandonLoad();
  _state = { kind: 'none', projectId: undefined, packages: new Set() };
  _revision += 1;
  _notify();
}

/**
 * Return the dirName set the palette should intersect with, or ``null``
 * when no project is loaded (palette shows everything).
 */
export function getCurrentProjectPackages(): ReadonlySet<string> | null {
  if (_state.kind === 'none') return null;
  return _state.packages;
}

/** For TrillGenerator on save: the list to persist into ``spec.dataflow.packages``. */
export function getCurrentProjectPackagesList(): string[] {
  return Array.from(_state.packages).sort();
}

export function getCurrentProjectId(): string | undefined {
  return _state.projectId;
}

/**
 * How long a caller will wait for an in-flight route load before giving up on
 * it. Only a bound on the wait: a load that overruns it is reported, never
 * treated as "this dataflow was never saved".
 */
export const PROJECT_LOAD_WAIT_MS = 15000;

type LoadLatch = { id: string; settled: Promise<void>; settle: () => void };

let _load: LoadLatch | null = null;

function _abandonLoad(): void {
  _load?.settle();
  _load = null;
}

/**
 * A route load for ``id`` has started.
 *
 * ``projectId`` above is pinned the moment the route resolves, but the flow
 * state's id only arrives when ``loadProject`` answers, and the canvas only
 * when the spec is applied after that. In between, the app is on a saved
 * dataflow that looks unsaved to anything reading the flow state - and the
 * writers that read it (import, install, uninstall) then took their "this
 * dataflow has never been saved" branch and created a SECOND dataflow,
 * installing into it while the URL still named the first (#340).
 *
 * The latch is what those writers wait on. It lives here rather than in React
 * state because it has to be readable in the same tick the route resolves,
 * which is a render too early for a state update.
 */
export function beginProjectLoad(id: string): void {
  if (_load?.id === id) return;
  _abandonLoad();
  let settle!: () => void;
  const settled = new Promise<void>((resolve) => {
    settle = resolve;
  });
  _load = { id, settled, settle };
}

/**
 * That load has finished, successfully or not.
 *
 * Called once the spec is on the canvas, not when the fetch answers: a save
 * that ran in between would persist the half-loaded canvas over the stored
 * dataflow, which is a worse outcome than the duplicate this fixes.
 *
 * Ignored when a newer load owns the latch, so a navigation that overtakes a
 * slow load does not release the wait for the dataflow now on screen.
 */
export function settleProjectLoad(id: string): void {
  if (_load?.id !== id) return;
  _abandonLoad();
}

/**
 * Resolves once no route load is in flight, or after ``timeoutMs``.
 *
 * Resolving on timeout rather than rejecting keeps one rule at the call sites:
 * after the wait, an id that is still missing while {@link getCurrentProjectId}
 * names a dataflow means the load did not deliver one, whether it failed, is a
 * shared dataflow, or simply overran. That is reported; it never falls through
 * to creating a dataflow.
 */
export function whenProjectSettled(timeoutMs: number = PROJECT_LOAD_WAIT_MS): Promise<void> {
  const latch = _load;
  if (!latch) return Promise.resolve();
  if (timeoutMs <= 0) return latch.settled;
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    void latch.settled.then(() => {
      clearTimeout(timer);
      resolve();
    });
  });
}

export function subscribe(listener: Listener): () => void {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
}

function _notify(): void {
  for (const l of _listeners) {
    try {
      l();
    } catch {
      // Subscribers must be resilient; one bad listener can't block others.
    }
  }
}

/**
 * A counter of LOCAL writes to this store.
 *
 * Capture it before starting a server read, hand it back to
 * {@link applyProjectLockfile}, and a read that lost a race to a newer local
 * write is refused instead of undoing it. See that function for why.
 */
export function getPackagesRevision(): number {
  return _revision;
}

/**
 * Apply the backend's lockfile for the current project (memo dev/101).
 *
 * The drawer re-reads ``GET /api/packages/projects/<id>`` on every reload
 * and pushes it here; the palette and the descriptor registry filter by this
 * set. Returns whether the set actually changed so the caller knows to pulse
 * ``refreshPackageRegistry`` — a package that arrived server-side (a Package
 * Builder Apply in another tab, a clobbered-then-healed lockfile) must reach
 * the palette AND resolve its nodes, not only flip the drawer's pill.
 *
 * *seenRevision* is {@link getPackagesRevision} as read BEFORE the fetch that
 * produced *packages*. If a local write landed while that request was in
 * flight, this read is older than what the store already knows and is dropped.
 *
 * Without that guard a server read could silently undo a local write: install
 * a package (the store gains it) and the reload that follows refetches the
 * lockfile, which — if the read raced the write — comes back without it and
 * removes it again. The palette then drops a package that IS installed, and
 * anything anchored to its row in the palette (the package metadata modal is
 * rendered inside its accordion) unmounts underneath the user. The write's own
 * response is always newer than a read that overlapped it, so it wins.
 */
export function applyProjectLockfile(
  packages: Iterable<string>,
  seenRevision: number,
): boolean {
  if (seenRevision !== _revision) return false;
  const next = new Set(packages);
  const current = _state.packages;
  const changed =
    next.size !== current.size || Array.from(next).some((p) => !current.has(p));
  if (changed) setCurrentProjectPackages(next);
  return changed;
}
