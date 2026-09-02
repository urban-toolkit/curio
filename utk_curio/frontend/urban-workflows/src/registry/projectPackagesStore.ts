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
  _state = { kind: 'dataflow', projectId: undefined, packages: new Set(packages) };
  _notify();
}

export function setCurrentProjectPackages(packages: Iterable<string>): void {
  // Same dataflow, new package set - drawer install / uninstall path, and the
  // defaults arriving for an unsaved dataflow. Keeps the current kind: calling
  // this before a dataflow is open must not silently open one.
  _state = { kind: _state.kind, projectId: _state.projectId, packages: new Set(packages) };
  _notify();
}

export function clearCurrentProject(): void {
  _state = { kind: 'none', projectId: undefined, packages: new Set() };
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
 * Apply the backend's lockfile for the current project (memo dev/101).
 *
 * The drawer re-reads ``GET /api/packages/projects/<id>`` on every reload
 * and pushes it here; the palette and the descriptor registry filter by this
 * set. Returns whether the set actually changed so the caller knows to pulse
 * ``refreshPackageRegistry`` — a package that arrived server-side (a Package
 * Builder Apply in another tab, a clobbered-then-healed lockfile) must reach
 * the palette AND resolve its nodes, not only flip the drawer's pill.
 */
export function applyProjectLockfile(packages: Iterable<string>): boolean {
  const next = new Set(packages);
  const current = _state.packages;
  const changed =
    next.size !== current.size || Array.from(next).some((p) => !current.has(p));
  if (changed) setCurrentProjectPackages(next);
  return changed;
}
