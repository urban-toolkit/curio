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

  // Tuple / multi-output bundles are workflow intermediates, not catalog datasets.
  if (dataType?.toLowerCase() === "outputs") return null;

  const ref: FlowOutputRef = { node_id: nodeId, filename };
  if (dataType) ref.data_type = dataType;
  return ref;
}

/** DuckDB / sandbox artifact id used by ``/get`` and the data pool fetcher. */
export function sandboxArtifactId(raw: unknown): string | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as { dataset?: unknown; path?: unknown };
  if (typeof r.dataset === "string" && r.dataset.trim()) return r.dataset.trim();
  if (typeof r.path === "string" && r.path.trim()) return r.path.trim();
  return null;
}
