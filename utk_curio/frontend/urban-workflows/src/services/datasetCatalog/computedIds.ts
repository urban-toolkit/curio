/**
 * TS mirror of the backend computed-dataset id grammar
 * (utk_curio/backend/app/datasets/install/installer.py).
 *
 * Computed dataset ids are ``computed.<dataflowSeg>.<nodeSeg>`` — legacy
 * pre-namespacing ids are ``computed.<nodeSeg>`` — and dir names append
 * ``@<major>``. Segments are SANITIZED node/dataflow ids: the sanitization is
 * not invertible (UUID node ids gain an ``n`` prefix, punctuation collapses to
 * dashes), so recovering a real canvas node id requires sanitizing candidate
 * ids and comparing segments — never treating a segment as a node id directly.
 */

/** Mirror of the backend ``sanitize_node_id_segment``. */
export function sanitizeNodeIdSegment(rawId: string): string {
  let seg = rawId.toLowerCase().replace(/[^a-z0-9-]/g, "-");
  seg = seg.replace(/-+/g, "-").replace(/^-+|-+$/g, "").slice(0, 62);
  if (!seg || !/^[a-z]/.test(seg)) {
    seg = ("n" + seg).slice(0, 63);
  }
  return seg || "node";
}

/**
 * The sanitized NODE segment (always the last dotted segment) of a computed
 * id or dirName, tolerating both id forms and an optional ``@<major>``.
 * Mirror of the backend ``node_segment_from_computed_id``.
 */
export function nodeSegmentFromComputedId(source: string | null | undefined): string | null {
  if (!source || !source.startsWith("computed.")) return null;
  const seg = source.slice("computed.".length).replace(/@\d+$/, "");
  if (!seg) return null;
  const parts = seg.split(".");
  return parts[parts.length - 1] || null;
}

/**
 * The sanitized DATAFLOW segment of a namespaced computed id, or null for the
 * legacy un-namespaced form. Mirror of the backend
 * ``dataflow_segment_from_computed_id``.
 */
export function dataflowSegmentFromComputedId(
  source: string | null | undefined,
): string | null {
  if (!source || !source.startsWith("computed.")) return null;
  const seg = source.slice("computed.".length).replace(/@\d+$/, "");
  const parts = seg.split(".");
  return parts.length >= 2 ? parts[0] || null : null;
}
