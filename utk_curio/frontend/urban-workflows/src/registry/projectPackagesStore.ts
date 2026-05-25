/**
 * Singleton store of the *currently-loaded project's* lockfile.
 *
 * The palette filters by intersection with this set so two projects open
 * in different tabs / sessions see different palettes even though they
 * share one user package store. See ``docs/CATALOG.md`` § "Per-project
 * lockfile".
 *
 * Writers:
 *  - {@link ProjectLoader} on project load → ``setCurrentProject``
 *  - {@link NodeCatalogDrawer} install / uninstall handlers → ``setCurrentProjectPackages``
 *  - On project-list page (no project): ``clearCurrentProject`` (palette shows everything)
 *
 * Readers:
 *  - {@link loadInstalledPackages} reads ``getCurrentProjectPackages`` to filter.
 *  - {@link TrillGenerator} callers read the packages list to persist into the spec.
 */

export type ProjectPackages = {
  /** ``undefined`` means "no project loaded — show everything in the palette". */
  projectId: string | undefined;
  /**
   * Sorted dirNames in the project's lockfile. Empty when no project is
   * loaded — but {@link getCurrentProjectPackages} returns ``null`` in that
   * case so the palette filter knows to skip the intersection.
   */
  packages: ReadonlySet<string>;
};

type Listener = () => void;

const _listeners = new Set<Listener>();

let _state: ProjectPackages = {
  projectId: undefined,
  packages: new Set(),
};

export function setCurrentProject(projectId: string, packages: Iterable<string>): void {
  _state = { projectId, packages: new Set(packages) };
  _notify();
}

export function setCurrentProjectPackages(packages: Iterable<string>): void {
  // Same project, new package set — drawer install / uninstall path.
  _state = { projectId: _state.projectId, packages: new Set(packages) };
  _notify();
}

export function clearCurrentProject(): void {
  _state = { projectId: undefined, packages: new Set() };
  _notify();
}

/**
 * Return the dirName set the palette should intersect with, or ``null``
 * when no project is loaded (palette shows everything).
 */
export function getCurrentProjectPackages(): ReadonlySet<string> | null {
  if (_state.projectId === undefined) return null;
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
