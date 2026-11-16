/**
 * The raw-`fetch` transports of the packages API: the multipart sideload, the two archive downloads, and the browser hand-off of a blob. Everything JSON goes through `packagesApi`; these three cannot (multipart body, binary body).
 *
 * The packages service layer (memo dev/143, F1) — the twin of `services/datasetCatalog`
 * and `services/agents`. Components render; this layer owns transport, the hooks over it
 * (F2–F3) and pure logic.
 */

import { getToken } from "../../utils/authApi";
import { backendUrl } from "../../utils/backendUrl";
import { requestHeaders } from "../../utils/requestHeaders";
import type { InstallResponse } from "./types";

const BACKEND_URL = backendUrl();

/**
 * Hand a blob to the browser as a download. Shared by the two archive paths —
 * `downloadArchive` (an installed package) and `factoryBuild` (an un-installed
 * wizard draft) — and by the export buttons. The blob never lives in JS memory
 * longer than the click handler: it goes straight to `URL.createObjectURL` and
 * is revoked immediately after.
 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objUrl);
}

/**
 * Multipart upload helper — bypasses ``apiFetch`` because the latter
 * always sets ``Content-Type: application/json``. The headers every request
 * sends are still attached (``utils/requestHeaders``), the token among them, so
 * the route's ``@require_auth`` decorator passes.
 */
export async function uploadArchive(
  file: Blob,
  filename: string,
  replace: boolean,
): Promise<InstallResponse> {
  const form = new FormData();
  form.append("file", file, filename);
  const url = `${BACKEND_URL}/api/packages/upload${replace ? "?replace=true" : ""}`;
  const res = await fetch(url, {
    method: "POST",
    body: form,
    headers: requestHeaders(getToken()),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.error || `HTTP ${res.status}`);
    (err as { status?: number }).status = res.status;
    throw err;
  }
  return (await res.json()) as InstallResponse;
}

/** Download an already-installed package as a ``.curio.zip`` archive. */
export async function downloadArchive(dirName: string): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/packages/${dirName}/archive`, {
    headers: requestHeaders(getToken()),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  triggerBlobDownload(await res.blob(), `${dirName}.curio.zip`);
}

/**
 * Build a package archive from a draft and trigger a browser download.
 * Used by the wizard's "Export package" button.
 */
export async function factoryBuild(draft: unknown): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(`${BACKEND_URL}/api/packages/factory/build`, {
    method: "POST",
    headers: requestHeaders(getToken(), { "Content-Type": "application/json" }),
    body: JSON.stringify(draft),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  const dispo = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(dispo);
  const filename = match?.[1] ?? "package.curio.zip";
  return { blob: await res.blob(), filename };
}
