import { apiFetch, getToken } from "../utils/authApi";

/**
 * REST client for ``/api/packages`` — warehouse catalog, factory, and resolver APIs.
 *
 * Two design rules:
 *
 *  1. Every JSON request goes through ``apiFetch`` (authoritative Bearer
 *     header + parse + error handling). Multipart upload / binary download
 *     have to bypass it — we call ``fetch`` directly with the same
 *     auth header.
 *  2. After any mutation that changes the installed-package set
 *     (`upload`, `uninstall`, `factoryInstall`), call
 *     ``refreshPackageRegistry()`` so the palette re-renders without a page
 *     reload. Implemented in ``registry/packageRegistryBootstrap.ts`` (also
 *     mounted on ``window.curio`` from ``index.tsx`` for legacy callers).
 */
const BACKEND_URL = process.env.BACKEND_URL || "";

export interface PortPayload {
  types: string[];
  cardinality?: string;
}

export interface PackageKindPayload {
  id: string; // canonical "<packageId>/<kindId>@<major>"
  kindId: string;
  label: string;
  category: string;
  engine: "python" | "javascript";
  description: string;
  icon: string | null;
  /** "<source>:<icon-id>" key resolved through iconRegistry. */
  iconRef: string | null;
  /** String key into the lifecycleRegistry. */
  lifecycle: string | null;
  /** Sort order in the palette; null means built-in default ordering. */
  paletteOrder: number | null;
  editor: "code" | "widgets" | "grammar" | "none";
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  /** Grammar adapter key (e.g. "vega-lite") when editor === "grammar". */
  grammarId: string | null;
  /** Palette card badge label (e.g. "VEGA", "AUTK"). */
  badge: string | null;
  inputPorts: PortPayload[];
  outputPorts: PortPayload[];
  /** Package-relative path to the optional starter source file. */
  source: string | null;
  /** Adds a third `'in/out'` handle on top of the standard in/out pair (interaction-loop kinds). */
  bidirectional: boolean;
  /** Overrides for the canvas container layout (size, no-content, play-button gate). */
  containerStyle: {
    nodeWidth?: number;
    nodeHeight?: number;
    noContent?: boolean;
    disablePlay?: boolean;
  } | null;
  /** When false, suppresses the provenance editor tab; null = client default (true). */
  hasProvenance: boolean | null;
  /** Anchor id for the in-app tutorial system. */
  tutorialId: string | null;
}

/** Package-relative coordinate (`packageId` + compatibility major). */
export interface PackageLineageCoordPayload {
  packageId: string;
  major: number;
}

/** Fork provenance from manifest `lineage`; surfaced by `/api/packages`. */
export interface PackageLineagePayload {
  forkedFrom: PackageLineageCoordPayload;
  root: PackageLineageCoordPayload;
}

export interface PackageDependencies {
  packages: Record<string, string>;
  python: Record<string, string>;
  js: Record<string, string>;
}

export interface PackagePayload {
  packageId: string;
  major: number;
  version: string;
  name: string;
  publisher: string;
  description: string;
  license: string | null;
  permissions: string[];
  dependencies: PackageDependencies;
  kinds: PackageKindPayload[];
  dirName: string;
  /** Fork provenance when declared in manifest; otherwise null from API. */
  lineage: PackageLineagePayload | null;
  /** Canonical catalog family key (`lineage.root` coordinate or `dirName`). */
  familyKey: string;
  /** Normalised from manifest `distribution.channel` (default stable). */
  channel: string;
  /** Catalog endpoint only — true when the user already has this coord installed. */
  installed?: boolean;
  /**
   * Optional vendor extension surfaced from on-disk manifest `curio.paletteDock`.
   * Omitted unless `hiddenFromForkPaletteDock` is true.
   */
  paletteDock?: { hiddenFromForkPaletteDock?: boolean };
  /**
   * ISO 8601 instant from manifest ``createdAt``. Omitted only for malformed legacy rows.
   */
  createdAt?: string;
  /**
   * Epoch milliseconds for ``manifest.createdAt`` (canonical package creation / authoring time).
   * Zero when absent; API lists sort newest-first primarily by this field.
   */
  createdAtMs?: number;
  /**
   * Epoch ms of ``manifest.json`` filesystem mtime (diagnostic — not used for canonical ordering).
   */
  installUpdatedAtMs?: number;
}

export interface CatalogFamilyPayload {
  familyKey: string;
  dirNames: string[];
}

export interface CatalogCollisionPayload {
  familyKey: string;
  channel: string;
  version: string;
  dirNames: string[];
}

export interface InstallResponse {
  package: PackagePayload;
  integrity: Record<string, string>;
  replacedExisting: boolean;
}

/** Response from ``factory/publish-catalog`` (fixture write). */
export interface CatalogPublishResponse extends InstallResponse {
  filename: string;
  catalogDir: string;
}

export interface FactoryCapabilities {
  catalogPublish: boolean;
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

export interface InstallDepsResponse {
  lockfile: Lockfile;
  conflicts: ResolveConflict[];
  sandboxStatus: number | null;
  sandboxBody?: Record<string, unknown>;
  pipRequirements?: string[];
}

/**
 * Multipart upload helper — bypasses ``apiFetch`` because the latter
 * always sets ``Content-Type: application/json``. The Bearer header is
 * still attached so the route's ``@require_auth`` decorator passes.
 */
async function uploadArchive(
  file: Blob,
  filename: string,
  replace: boolean,
): Promise<InstallResponse> {
  const token = getToken();
  const form = new FormData();
  form.append("file", file, filename);
  const url = `${BACKEND_URL}/api/packages/upload${replace ? "?replace=true" : ""}`;
  const res = await fetch(url, {
    method: "POST",
    body: form,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.error || `HTTP ${res.status}`);
    (err as { status?: number }).status = res.status;
    throw err;
  }
  return (await res.json()) as InstallResponse;
}

/**
 * Trigger a browser download of an installed package as a ``.curio-package``
 * archive. The blob never lives in JS memory longer than the click
 * handler — we hand it straight to ``URL.createObjectURL``.
 */
async function downloadArchive(dirName: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BACKEND_URL}/api/packages/${dirName}/archive`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = `${dirName}.curio-package`;
  a.click();
  URL.revokeObjectURL(objUrl);
}

/**
 * Build a package archive from a draft and trigger a browser download.
 * Used by the wizard's "Export package" button.
 */
async function factoryBuild(draft: unknown): Promise<{ blob: Blob; filename: string }> {
  const token = getToken();
  const res = await fetch(`${BACKEND_URL}/api/packages/factory/build`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(draft),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  const dispo = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(dispo);
  const filename = match?.[1] ?? "package.curio-package";
  return { blob: await res.blob(), filename };
}

export const packagesApi = {
  /** Installed packages for the current user. */
  listInstalled(): Promise<{ packages: PackagePayload[] }> {
    return apiFetch("/api/packages");
  },

  /** Batch reveal/suppress fork-source coordinates in the Packages dock (manifest-backed). */
  forkParentsPaletteDockVisibility(visible: boolean): Promise<void> {
    return apiFetch("/api/packages/palette-dock/fork-parents", {
      method: "POST",
      body: JSON.stringify({ visible }),
    });
  },

  /**
   * Show or hide one installed pkg's section in the Nodes palette dock
   * (manifest ``curio.paletteDock.hiddenFromForkPaletteDock``).
   */
  packagePaletteDockVisible(dirName: string, visible: boolean): Promise<void> {
    return apiFetch(`/api/packages/${dirName}/palette-dock-visible`, {
      method: "POST",
      body: JSON.stringify({ visible }),
    });
  },

  /** Fixture-backed catalog: package rows plus family index and collision report. */
  catalog(): Promise<{
    packages: PackagePayload[];
    families: CatalogFamilyPayload[];
    catalogCollisions: CatalogCollisionPayload[];
  }> {
    return apiFetch("/api/packages/catalog");
  },

  /** Sideload a ``.curio-package`` archive (multipart). */
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
   * Resolve, then forward the merged python deps to the shared sandbox
   * via ``/installPackages``. Returns the lockfile the caller should
   * persist in ``spec.trill.json`` (epic invariant: project lockfile
   * lives inside the project).
   */
  installDeps(packages: string[]): Promise<InstallDepsResponse> {
    return apiFetch("/api/packages/install-deps", {
      method: "POST",
      body: JSON.stringify({ packages }),
    });
  },
};

export { refreshPackageRegistry } from "../registry/packageRegistryBootstrap";
