/**
 * Normalize a node execution output into the catalog / project OutputRef shape.
 *
 * Sandbox responses use ``{ path, dataType, dataset? }``.  Prefer the named
 * parquet ``dataset`` file when present; otherwise use DuckDB ``path``.
 */
export interface FlowOutputRef {
  node_id: string;
  filename: string;
  data_type?: string;
}

export function flowOutputRefFromRaw(
  nodeId: string,
  raw: unknown,
): FlowOutputRef | null {
  let filename: string | null = null;
  let dataType: string | undefined;

  if (raw && typeof raw === "object") {
    const r = raw as { dataset?: unknown; path?: unknown; dataType?: unknown };
    if (typeof r.dataType === "string" && r.dataType.trim()) {
      dataType = r.dataType.trim();
    }
    if (typeof r.dataset === "string" && r.dataset.trim()) {
      filename = r.dataset.trim();
    } else if (typeof r.path === "string" && r.path.trim()) {
      filename = r.path.trim();
    }
  } else if (typeof raw === "string") {
    filename = raw.trim();
  }

  if (!filename || !nodeId) return null;

  const ref: FlowOutputRef = { node_id: nodeId, filename };
  if (dataType) ref.data_type = dataType;
  return ref;
}

/**
 * Artifact id for sandbox ``/get`` and ``/get-preview``.
 *
 * Prefer DuckDB ``path`` — the sandbox loads artifacts by id, not by the
 * catalog parquet ``dataset`` filename in the shared data directory.
 */
/** Shape stored on ``node.data.input`` for sandbox-backed nodes (e.g. Data Pool). */
export interface FlowNodeInput {
  path: string;
  dataType?: string;
  dataset?: string;
}

/**
 * Normalize a cached or live node output into ``node.data.input`` form.
 * Always returns a fresh object so reconnects re-trigger input effects.
 */
export function normalizeFlowInput(raw: unknown): FlowNodeInput | Record<string, unknown> | "" {
  if (raw == null || raw === "") return "";

  if (typeof raw === "string") {
    const path = raw.trim();
    return path ? { path } : "";
  }

  if (typeof raw !== "object") return "";

  const r = raw as {
    path?: unknown;
    filename?: unknown;
    dataset?: unknown;
    dataType?: unknown;
    data?: unknown;
  };

  const path = sandboxArtifactId(raw);
  if (!path) {
    // Merge bundles and other in-memory payloads (no DuckDB artifact id).
    if (typeof r.dataType === "string" && r.dataType.trim()) {
      return { ...r };
    }
    return "";
  }

  const normalized: FlowNodeInput = { path };
  if (typeof r.dataType === "string" && r.dataType.trim()) {
    normalized.dataType = r.dataType.trim();
  }
  if (typeof r.dataset === "string" && r.dataset.trim()) {
    normalized.dataset = r.dataset.trim();
  }
  return normalized;
}

export function sandboxArtifactId(raw: unknown): string | null {
  if (typeof raw === "string") {
    const id = raw.trim();
    return id || null;
  }
  if (!raw || typeof raw !== "object") return null;
  const r = raw as { path?: unknown; filename?: unknown; dataset?: unknown };
  if (typeof r.path === "string" && r.path.trim()) return r.path.trim();
  if (typeof r.filename === "string" && r.filename.trim()) return r.filename.trim();
  if (typeof r.dataset === "string" && r.dataset.trim()) return r.dataset.trim();
  return null;
}
