/**
 * The data a dashboard page carries, when it carries any.
 *
 * A dashboard at `/dashboard/<id>` is meant to stand on its own: the page server
 * inlines the spec, the saved rows and the node descriptors into the document,
 * so the browser makes one request and nothing else. This module is the only
 * thing that reads that payload; everything that would otherwise fetch asks here
 * first and falls back to the network when the answer is null.
 *
 * Null is a normal answer, not a failure. A dashboard too large to embed, a
 * backend that was down when the page was served, and the webpack dev server
 * (which cannot inject) all produce an ordinary page that fetches for itself.
 * That is the behaviour this feature replaces, so degrading to it is safe.
 *
 * Read once and frozen: the payload is a document the page was served with, not
 * state. Re-reading it per call would re-parse megabytes of rows.
 */

/** The wire envelope `/get` returns, which is what every tile already consumes. */
export interface EmbeddedEnvelope {
  dataType?: string;
  data?: unknown;
  schema?: Record<string, string>;
  [key: string]: unknown;
}

export interface EmbeddedDashboard {
  meta: { projectId?: string; name?: string | null; generatedAt?: string };
  spec: any;
  /** Keyed by the manifest filename a tile looks up, exactly as `/get` is. */
  outputs: Record<string, EmbeddedEnvelope>;
  /**
   * The same outputs as the project load hands the page, by node, narrowed to
   * what actually travelled. The loader restores a node's output by id; the map
   * above is keyed by filename because that is how a tile looks its rows up.
   */
  outputRefs?: Array<{ node_id: string; filename: string; data_type?: string }>;
  /**
   * What the node registry needs. Curio bundles node implementations but not
   * node descriptors, so without this every tile renders "Loading node...",
   * however much data the page carries.
   */
  registry?: {
    packages?: any[];
    starters?: any[];
    /** `"<packageId>@<major>"` to the script text that registers its behaviour. */
    behaviorScripts?: Record<string, string>;
  };
}

const PAYLOAD_ELEMENT_ID = "curio-dashboard-payload";

let parsed: EmbeddedDashboard | null | undefined;

function read(): EmbeddedDashboard | null {
  if (typeof document === "undefined") return null;
  const el = document.getElementById(PAYLOAD_ELEMENT_ID);
  if (!el || !el.textContent) return null;
  try {
    const value = JSON.parse(el.textContent);
    if (!value || typeof value !== "object") return null;
    // A payload without outputs is still a payload: a dashboard whose tiles
    // have no saved rows yet should render its empty states offline rather than
    // fall back to fetching nothing.
    if (!value.outputs || typeof value.outputs !== "object") value.outputs = {};
    return value as EmbeddedDashboard;
  } catch {
    // Better an ordinary fetching page than a blank one. A truncated or
    // malformed payload is a serving fault, not something to show the viewer.
    return null;
  }
}

/** The payload this page was served with, or null when it was served without one. */
export function getEmbeddedDashboard(): EmbeddedDashboard | null {
  if (parsed === undefined) parsed = read();
  return parsed;
}

/** True when this page can render without reaching the network. */
export function isStandaloneDashboard(): boolean {
  return getEmbeddedDashboard() !== null;
}

/**
 * The embedded envelope for one artifact, or null when the page has no payload
 * or does not carry that artifact.
 *
 * Returning null rather than throwing on a miss is deliberate: a tile whose
 * output was not embedded, because it was unreadable when the page was built,
 * should fetch and fail the way it does today rather than take the page down.
 */
export function embeddedArtifact(fileName: string): EmbeddedEnvelope | null {
  const payload = getEmbeddedDashboard();
  if (!payload) return null;
  const hit = payload.outputs[fileName];
  return hit === undefined ? null : hit;
}

/** Test seam: forget what was read, so a test can install a different payload. */
export function resetEmbeddedDashboardForTests(): void {
  parsed = undefined;
}
