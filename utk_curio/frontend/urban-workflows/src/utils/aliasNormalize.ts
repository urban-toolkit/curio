/**
 * Normalize legacy node-type strings in a trill spec, in place.
 *
 * Trill files written before the manifest-pack refactor used the legacy
 * ``NodeType`` enum strings (e.g. `"DATA_LOADING"`). After Phase B, the
 * runtime expects unversioned canonical refs (`"curio.builtin/data-loading"`).
 *
 * Called once at trill-load time (see `useCode.loadTrill`) so every
 * downstream consumer sees canonical strings. Versioned and already-canonical
 * type strings pass through unchanged.
 */

import { legacyToCanonical } from "../registry/legacyAliases";

export function aliasNormalize(trill: { dataflow?: { nodes?: any[] } } | null | undefined): void {
  const nodes = trill?.dataflow?.nodes;
  if (!Array.isArray(nodes)) return;
  for (const node of nodes) {
    const t = node?.type;
    if (typeof t === "string") {
      const canonical = legacyToCanonical(t);
      if (canonical) node.type = canonical;
    }
  }
}
