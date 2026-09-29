/**
 * REST client for `/api/packages` — catalog, factory, resolver, lockfile, defaults and libraries. Every JSON request goes through `apiFetch` (Bearer header + parse + error handling); multipart upload and binary download live in `packagesBlobTransport`. After a mutation that changes the installed set the CALLER refreshes the registry (`registry/packageRegistryBootstrap.refreshPackageRegistry`) — this layer never imports the registry (memo dev/143 §3.4 rule 5), which is what keeps it light.
 *
 * The packages service layer (memo dev/143, F1) — the twin of `services/datasetCatalog`
 * and `services/agents`. Components render; this layer owns transport, the hooks over it
 * (F2–F3) and pure logic.
 */

import { apiFetch } from "../../utils/authApi";
import { downloadArchive, factoryBuild, uploadArchive } from "./packagesBlobTransport";
import type {
  CatalogCollisionPayload,
  CatalogFamilyPayload,
  CatalogPublishResponse,
  DefaultsInstallResponse,
  FactoryCapabilities,
  InstallResponse,
  PackageMetadataUpdate,
  PackagePayload,
  ProjectPackagesResponse,
  ResolveResponse,
  WorkflowDepsCheckResponse,
  WorkflowDepsInstallResponse,
} from "./types";

export const packagesApi = {
  /** Installed packages for the current user. */
  listInstalled(): Promise<{ packages: PackagePayload[] }> {
    return apiFetch("/api/packages");
  },

  /** Fixture-backed catalog: package rows plus family index and collision report. */
  catalog(): Promise<{
    packages: PackagePayload[];
    families: CatalogFamilyPayload[];
    catalogCollisions: CatalogCollisionPayload[];
  }> {
    return apiFetch("/api/packages/catalog");
  },

  /** Sideload a ``.curio.zip`` archive (multipart). */
  uploadArchive(file: Blob, filename: string, opts: { replace?: boolean } = {}): Promise<InstallResponse> {
    return uploadArchive(file, filename, !!opts.replace);
  },

  /**
   * Install a catalog pkg by its ``dirName`` (``<packageId>@<major>``).
   * The backend copies from the committed fixture set into the user's
   * pkg store. Sideload via upload remains the path for arbitrary zips;
   * a remote pkg-registry download service is future work.
   */
  installFromCatalog(dirName: string, opts: { replace?: boolean } = {}): Promise<InstallResponse> {
    return apiFetch("/api/packages/catalog/install", {
      method: "POST",
      body: JSON.stringify({ dirName, replace: !!opts.replace }),
    });
  },

  uninstall(dirName: string): Promise<void> {
    return apiFetch(`/api/packages/${dirName}`, { method: "DELETE" });
  },

  /**
   * Partial-update editable package metadata (name, description, publisher,
   * license, permissions, README, ``compatibility.curioRuntime``). Identity
   * fields and ``dependencies`` are rejected by the backend allowlist —
   * dependencies are source-derived now.
   */
  updatePackageMetadata(
    dirName: string,
    updates: PackageMetadataUpdate,
  ): Promise<{ package: PackagePayload }> {
    return apiFetch(`/api/packages/${encodeURIComponent(dirName)}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },

  download(dirName: string): Promise<void> {
    return downloadArchive(dirName);
  },

  /** Build (and download) an archive from a wizard draft. */
  factoryBuild(draft: unknown): Promise<{ blob: Blob; filename: string }> {
    return factoryBuild(draft);
  },

  /** Build the draft and install it for the current user in one shot. */
  factoryInstall(draft: unknown): Promise<InstallResponse> {
    return apiFetch("/api/packages/factory/install", {
      method: "POST",
      body: JSON.stringify(draft),
    });
  },

  /** Whether ``factoryPublishCatalog`` is allowed (``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``; on by default). */
  factoryCapabilities(): Promise<FactoryCapabilities> {
    return apiFetch("/api/packages/factory/capabilities");
  },

  /**
   * Publish the wizard draft into the backend catalog (``<repo_root>/packages/``).
   * Can be disabled with ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` = ``0`` / ``false`` / ``no`` / ``off``.
   *
   * *draft* is the usual ``toApiPayload`` object; optional ``replace`` overwrites an
   * existing catalog directory for the same coordinate.
   */
  factoryPublishCatalog(
    draft: Record<string, unknown>,
  ): Promise<CatalogPublishResponse> {
    return apiFetch("/api/packages/factory/publish-catalog", {
      method: "POST",
      body: JSON.stringify(draft),
    });
  },

  /**
   * Remove a pkg from the catalog (`<repo_root>/packages/<dirName>/`).
   * Gated by the same env flag as `factoryPublishCatalog`; does not uninstall
   * from the user's package store.
   */
  unpublishFromCatalog(dirName: string): Promise<void> {
    return apiFetch(`/api/packages/catalog/${encodeURIComponent(dirName)}`, {
      method: "DELETE",
    });
  },

  /**
   * Resolve a set of pkg ``dirName``s into a lockfile (200) or
   * conflict report (409). The ``apiFetch`` helper raises on non-2xx;
   * the wizard / install dialog wraps the call so it can render the
   * conflict UI on 409.
   */
  resolve(packages: string[]): Promise<ResolveResponse> {
    return apiFetch("/api/packages/resolve", {
      method: "POST",
      body: JSON.stringify({ packages }),
    });
  },

  /**
   * Load-time dependency probe: given the dataflow's declared package
   * lockfile (`dataflow.packages`), report which packages aren't ready
   * (not installed, or installed but missing a declared python dep).
   */
  checkWorkflowDeps(packages: string[]): Promise<WorkflowDepsCheckResponse> {
    return apiFetch("/api/packages/workflow-deps/check", {
      method: "POST",
      body: JSON.stringify({ packages }),
    });
  },

  /** Install the dataflow's declared dependency packages into the user store
   *  (each brings its nodes + declared python libraries). */
  installWorkflowDeps(packages: string[]): Promise<WorkflowDepsInstallResponse> {
    return apiFetch("/api/packages/workflow-deps/install", {
      method: "POST",
      body: JSON.stringify({ packages }),
    });
  },

  // --------------------------------------------------------------
  // Per-project lockfile + per-user defaults (see docs/NODE-CATALOG.md)
  // --------------------------------------------------------------

  /** Read the project's current lockfile (sorted dirNames). */
  getProjectPackages(projectId: string): Promise<ProjectPackagesResponse> {
    return apiFetch(`/api/packages/projects/${encodeURIComponent(projectId)}`);
  },

  /** Add a package to ONE project's lockfile (drawer install). */
  installToProject(
    projectId: string, dirName: string,
  ): Promise<ProjectPackagesResponse> {
    return apiFetch(
      `/api/packages/projects/${encodeURIComponent(projectId)}/install`,
      { method: "POST", body: JSON.stringify({ dirName }) },
    );
  },

  /** Drop a package from ONE project's lockfile (drawer uninstall). */
  uninstallFromProject(
    projectId: string, dirName: string,
  ): Promise<ProjectPackagesResponse> {
    return apiFetch(
      `/api/packages/projects/${encodeURIComponent(projectId)}/${dirName}`,
      { method: "DELETE" },
    );
  },

  /** Read the per-user default-packages list. */
  getDefaults(): Promise<{ packages: string[] }> {
    return apiFetch("/api/packages/defaults");
  },

  /** Install for every existing project + auto-seed into new ones. */
  installToDefaults(dirName: string): Promise<DefaultsInstallResponse> {
    return apiFetch("/api/packages/defaults", {
      method: "POST",
      body: JSON.stringify({ dirName }),
    });
  },

  // --------------------------------------------------------------
  // Per-user "Installed libraries" (Python + JS)
  // --------------------------------------------------------------

  /** Standalone + package-derived libraries in one payload.
   *  ``installed`` reports whether a package-declared python dep is actually
   *  present in the interpreter (null for js — no runtime check). */
  listLibraries(): Promise<{
    standalone: { python: string[]; js: string[] };
    fromPackages: Array<{
      name: string;
      spec: string;
      kind: "python" | "js";
      source: string;
      installed?: boolean | null;
    }>;
  }> {
    return apiFetch("/api/packages/libraries");
  },

  /** Add a standalone library; backend pip-installs and persists.
   *  ``installed`` lists what pip actually fetched; ``skipped`` lists deps
   *  whose requirement was already satisfied (no work done — the UI uses this
   *  to distinguish "Installed" from "Already installed"). Satisfied is not the
   *  same as working: ``importError`` carries the reason when the library
   *  cannot actually be imported, and the UI must report that as a failure
   *  whatever the other two lists say. */
  addLibrary(kind: "python" | "js", spec: string): Promise<{
    standalone: { python: string[]; js: string[] };
    installed: string[];
    skipped: string[];
    importError?: string | null;
  }> {
    return apiFetch("/api/packages/libraries", {
      method: "POST",
      body: JSON.stringify({ kind, spec }),
    });
  },

  /** Drop a standalone library; backend pip-uninstalls only if no
   *  package still declares it. */
  removeLibrary(kind: "python" | "js", spec: string): Promise<{ standalone: { python: string[]; js: string[] } }> {
    return apiFetch(`/api/packages/libraries/${kind}/${encodeURIComponent(spec)}`, {
      method: "DELETE",
    });
  },
};
