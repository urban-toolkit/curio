import { apiFetch, getToken } from "../utils/authApi";

/**
 * REST client for ``/api/packs`` — warehouse catalog, factory, and resolver APIs.
 *
 * Two design rules:
 *
 *  1. Every JSON request goes through ``apiFetch`` (authoritative Bearer
 *     header + parse + error handling). Multipart upload / binary download
 *     have to bypass it — we call ``fetch`` directly with the same
 *     auth header.
 *  2. After any mutation that changes the installed-pack set
 *     (`upload`, `uninstall`, `factoryInstall`), call
 *     ``refreshPackRegistry()`` so the palette re-renders without a page
 *     reload. Implemented in ``registry/packRegistryBootstrap.ts`` (also
 *     mounted on ``window.curio`` from ``index.tsx`` for legacy callers).
 */
const BACKEND_URL = process.env.BACKEND_URL || "";

export interface PortPayload {
  types: string[];
  cardinality?: string;
}

export interface PackKindPayload {
  id: string; // canonical "<packId>/<kindId>@<major>"
  kindId: string;
  label: string;
  category: string;
  engine: "python" | "javascript";
  description: string;
  icon: string | null;
  editor: "code" | "widgets" | "grammar" | "none";
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  inputPorts: PortPayload[];
  outputPorts: PortPayload[];
  templateDir: string | null;
  defaultTemplate: string | null;
}

/** Pack-relative coordinate (`packId` + compatibility major). */
export interface PackLineageCoordPayload {
  packId: string;
  major: number;
}

/** Fork provenance from manifest `lineage`; surfaced by `/api/packs`. */
export interface PackLineagePayload {
  forkedFrom: PackLineageCoordPayload;
  root: PackLineageCoordPayload;
}

export interface PackDependencies {
  packs: Record<string, string>;
  python: Record<string, string>;
  js: Record<string, string>;
}

export interface PackPayload {
  packId: string;
  major: number;
  version: string;
  name: string;
  publisher: string;
  description: string;
  license: string | null;
  permissions: string[];
  dependencies: PackDependencies;
  kinds: PackKindPayload[];
  dirName: string;
  /** Fork provenance when declared in manifest; otherwise null from API. */
  lineage: PackLineagePayload | null;
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
  pack: PackPayload;
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
  ranges: { packDir: string; range: string }[];
}

export interface Lockfile {
  installedPacks: Array<{
    id: string;
    major: number;
    version: string;
    dirName: string;
    familyKey: string;
    lineageRoot?: PackLineageCoordPayload;
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
  const url = `${BACKEND_URL}/api/packs/upload${replace ? "?replace=true" : ""}`;
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
 * Trigger a browser download of an installed pack as a ``.curio-nodepack``
 * archive. The blob never lives in JS memory longer than the click
 * handler — we hand it straight to ``URL.createObjectURL``.
 */
async function downloadArchive(dirName: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${BACKEND_URL}/api/packs/${dirName}/archive`, {
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
  a.download = `${dirName}.curio-nodepack`;
  a.click();
  URL.revokeObjectURL(objUrl);
}

/**
 * Build a pack archive from a draft and trigger a browser download.
 * Used by the wizard's "Export pack" button.
 */
async function factoryBuild(draft: unknown): Promise<{ blob: Blob; filename: string }> {
  const token = getToken();
  const res = await fetch(`${BACKEND_URL}/api/packs/factory/build`, {
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
  const filename = match?.[1] ?? "pack.curio-nodepack";
  return { blob: await res.blob(), filename };
}

export const packsApi = {
  /** Installed packs for the current user. */
  listInstalled(): Promise<{ packs: PackPayload[] }> {
    return apiFetch("/api/packs");
  },

  /** Batch reveal/suppress fork-source coordinates in the Packs dock (manifest-backed). */
  forkParentsPaletteDockVisibility(visible: boolean): Promise<void> {
    return apiFetch("/api/packs/palette-dock/fork-parents", {
      method: "POST",
      body: JSON.stringify({ visible }),
    });
  },

  /**
   * Show or hide one installed pack's section in the Nodes palette dock
   * (manifest ``curio.paletteDock.hiddenFromForkPaletteDock``).
   */
  packPaletteDockVisible(dirName: string, visible: boolean): Promise<void> {
    return apiFetch(`/api/packs/${dirName}/palette-dock-visible`, {
      method: "POST",
      body: JSON.stringify({ visible }),
    });
  },

  /** Fixture-backed catalog: pack rows plus family index and collision report. */
  catalog(): Promise<{
    packs: PackPayload[];
    families: CatalogFamilyPayload[];
    catalogCollisions: CatalogCollisionPayload[];
  }> {
    return apiFetch("/api/packs/catalog");
  },

  /** Sideload a ``.curio-nodepack`` archive (multipart). */
  uploadArchive(file: Blob, filename: string, opts: { replace?: boolean } = {}): Promise<InstallResponse> {
    return uploadArchive(file, filename, !!opts.replace);
  },

  /**
   * Install a catalog pack by its ``dirName`` (``<packId>@<major>``).
   * The backend copies from the committed fixture set into the user's
   * pack store. Sideload via upload remains the path for arbitrary zips;
   * a remote pack-registry download service is future work.
   */
  installFromCatalog(dirName: string, opts: { replace?: boolean } = {}): Promise<InstallResponse> {
    return apiFetch("/api/packs/catalog/install", {
      method: "POST",
      body: JSON.stringify({ dirName, replace: !!opts.replace }),
    });
  },

  uninstall(dirName: string): Promise<void> {
    return apiFetch(`/api/packs/${dirName}`, { method: "DELETE" });
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
    return apiFetch("/api/packs/factory/install", {
      method: "POST",
      body: JSON.stringify(draft),
    });
  },

  /** Whether ``factoryPublishCatalog`` is allowed (``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH``; on by default). */
  factoryCapabilities(): Promise<FactoryCapabilities> {
    return apiFetch("/api/packs/factory/capabilities");
  },

  /**
   * Publish the wizard draft into the backend fixture catalog (``fixtures/packs``).
   * Can be disabled with ``CURIO_ALLOW_FACTORY_CATALOG_PUBLISH`` = ``0`` / ``false`` / ``no`` / ``off``.
   *
   * *draft* is the usual ``toApiPayload`` object; optional ``replace`` overwrites an
   * existing fixture directory for the same coordinate.
   */
  factoryPublishCatalog(
    draft: Record<string, unknown>,
  ): Promise<CatalogPublishResponse> {
    return apiFetch("/api/packs/factory/publish-catalog", {
      method: "POST",
      body: JSON.stringify(draft),
    });
  },

  /**
   * Resolve a set of pack ``dirName``s into a lockfile (200) or
   * conflict report (409). The ``apiFetch`` helper raises on non-2xx;
   * the wizard / install dialog wraps the call so it can render the
   * conflict UI on 409.
   */
  resolve(packs: string[]): Promise<ResolveResponse> {
    return apiFetch("/api/packs/resolve", {
      method: "POST",
      body: JSON.stringify({ packs }),
    });
  },

  /**
   * Resolve, then forward the merged python deps to the shared sandbox
   * via ``/installPackages``. Returns the lockfile the caller should
   * persist in ``spec.trill.json`` (epic invariant: project lockfile
   * lives inside the project).
   */
  installDeps(packs: string[]): Promise<InstallDepsResponse> {
    return apiFetch("/api/packs/install-deps", {
      method: "POST",
      body: JSON.stringify({ packs }),
    });
  },
};

export { refreshPackRegistry } from "../registry/packRegistryBootstrap";
