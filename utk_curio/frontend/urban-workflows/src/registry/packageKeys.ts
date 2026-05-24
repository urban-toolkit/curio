/**
 * Package palette / canvas sync helpers for canonical node type strings.
 *
 * Canonical node types come in two flavours:
 *
 *   - **Versioned**:   ``<packageId>/<kindId>@<major>``
 *   - **Unversioned**: ``<packageId>/<kindId>``
 *
 * Unversioned refs (the default form used in trill files and the
 * pre-installed builtin package) resolve to the latest installed major via
 * the registry's unversioned index — see {@link getNodeDescriptor}.
 */

/** `it.vendor.package/foo-kind@3` → `it.vendor.package@3` */
export function packageKeyFromCanonicalNodeType(nodeType: string | undefined | null): string | null {
  if (nodeType == null || typeof nodeType !== 'string') return null;
  const m = nodeType.match(/^(.+)\/([^/@]+)@(\d+)$/);
  if (!m) return null;
  return `${m[1]}@${m[3]}`;
}

/** `it.vendor.package/foo-kind@3` → `{ unversioned: 'it.vendor.package/foo-kind', major: 3 }`. */
export function splitCanonicalNodeType(nodeType: string): { unversioned: string; major: number } | null {
  if (typeof nodeType !== 'string') return null;
  const m = nodeType.match(/^(.+)\/([^/@]+)@(\d+)$/);
  if (!m) return null;
  return { unversioned: `${m[1]}/${m[2]}`, major: Number(m[3]) };
}

/** True if *nodeType* matches the unversioned `<packageId>/<kindId>` shape (no `@major`). */
export function isUnversionedNodeType(nodeType: string): boolean {
  if (typeof nodeType !== 'string') return false;
  // Has a slash, no `@digits` at the end.
  return /^[^/@]+\/[^/@]+$/.test(nodeType);
}
