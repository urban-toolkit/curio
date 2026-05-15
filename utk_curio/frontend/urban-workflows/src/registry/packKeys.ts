/**
 * Pack palette / canvas sync helpers for canonical node type strings
 * `<packId>/<kindId>@<major>`.
 */

/** `it.vendor.pack/foo-kind@3` → `it.vendor.pack@3` */
export function packKeyFromCanonicalNodeType(nodeType: string | undefined | null): string | null {
  if (nodeType == null || typeof nodeType !== 'string') return null;
  const m = nodeType.match(/^(.+)\/([^/@]+)@(\d+)$/);
  if (!m) return null;
  return `${m[1]}@${m[3]}`;
}
