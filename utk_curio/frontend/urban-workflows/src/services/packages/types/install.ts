/**
 * Install and resolution responses: the store install, the catalog publish, the lockfile and its conflicts, a dataflow's declared dependencies, a project's package set.
 *
 * The packages service layer (memo dev/143, F1) — the twin of `services/datasetCatalog`
 * and `services/agents`. Components render; this layer owns transport, the hooks over it
 * (F2–F3) and pure logic.
 */

import type { PackageLineageCoordPayload, PackagePayload } from "./package";

export interface InstallResponse {
  package: PackagePayload;
  integrity: Record<string, string>;
  replacedExisting: boolean;
  /**
   * ``{library: reason}`` for declared python deps that installed but cannot
   * be imported. These three routes (sideload, "Save and install", "Reload
   * from catalog") wrote the package files and never ran pip at all, so the
   * answer used to be neither yes nor no.
   */
  importErrors?: Record<string, string>;
  /**
   * pip itself failed. Reported rather than raised: the package files are
   * installed either way on these paths, so an error status would describe
   * neither outcome.
   */
  dependencyError?: string;
  /** Present exactly when pip changed a shared library under the server. */
  restartRecommended?: { libs: string[] };
}

/** Response from ``factory/publish-catalog`` (fixture write). */
export interface CatalogPublishResponse extends InstallResponse {
  catalogDir: string;
}

export interface ResolveConflict {
  package: string;
  ranges: { packageDir: string; range: string }[];
}

export interface Lockfile {
  installedPackages: Array<{
    id: string;
    major: number;
    version: string;
    dirName: string;
    familyKey: string;
    lineageRoot?: PackageLineageCoordPayload;
  }>;
  pythonDeps: Record<string, string>;
  jsDeps: Record<string, string>;
}

export interface ResolveResponse {
  lockfile: Lockfile;
  conflicts: ResolveConflict[];
}

/** A declared python dep that is installed at a satisfying version but will
 *  not import — typically a wheel whose native extension fails to load. */
export interface WorkflowDepImportFailure {
  /** Package dirName that declares the dep. */
  package: string;
  /** Distribution name of the library. */
  dep: string;
  /** Last line of the import error, e.g. a DLL load failure. */
  error: string;
}

/** Response from `POST /api/packages/workflow-deps/check`. */
export interface WorkflowDepsCheckResponse {
  /** Declared dependency packages (dirNames) that aren't installed yet, or
   *  are installed but missing one of their declared python deps. */
  packages: string[];
  /** Deps that are present and version-satisfying but unimportable. Reinstalling
   *  does NOT fix these — pip reports "already satisfied" and does nothing — so
   *  they are reported for the user to repair, never auto-installed. Optional:
   *  an older backend omits it. */
  broken?: WorkflowDepImportFailure[];
  /** The subset of `packages` that must NOT be installed without being asked
   *  - too expensive to pull in as a side effect of opening a dataflow. They
   *  are still reported as missing, because the canvas has to be able to name
   *  them; installing them is the user's call, from the catalog (#233).
   *  Absent on an older backend, which is why every read defaults it. */
  deferred?: string[];
}

/** Response from `POST /api/packages/workflow-deps/install`. */
export interface WorkflowDepsInstallResponse {
  /** Catalog package dirNames installed into the user store. */
  installedPackages: string[];
  /**
   * ``{library: reason}`` for declared python deps that installed but cannot
   * be imported. pip is satisfied by metadata alone, so a wheel whose native
   * extension is broken installs without complaint; report this rather than
   * letting the user meet it later as a node's ImportError.
   */
  importErrors?: Record<string, string>;
}

/** Response from project-scoped install / uninstall and `GET /projects/<id>`. */
export interface ProjectPackagesResponse {
  /** Sorted dirNames in the project's lockfile (`spec.dataflow.packages`). */
  packages: string[];
  /** Set on install responses: did this install also copy into the user store? */
  addedToUserStore?: boolean;
  /** Set on uninstall responses: user-store copies the prune sweep removed. */
  pruned?: string[];
  /** Set on uninstall responses: defaults entries the prune sweep removed. */
  removedFromDefaults?: string[];
  /** dev/92 B-2: present exactly when this install's pip step actually
   * installed/changed shared libraries under the running server. */
  restartRecommended?: { libs: string[] };
  /**
   * ``{library: reason}`` for declared python deps that installed but cannot
   * be imported. pip counts matching metadata as satisfaction, so a wheel
   * whose native extension is broken installs without complaint; report this
   * rather than letting the user meet it later as a node's ImportError.
   */
  importErrors?: Record<string, string>;
}
