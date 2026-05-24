import { NodeKindId, NodeDescriptor } from './types';
import { splitCanonicalNodeType } from './packKeys';

/**
 * The node-kind registry.
 *
 * Keyed by canonical type string. Versioned ids like
 * `"ai.urbanlab.uhvi/uhvi-load@1"` are stored as-is. A secondary
 * **unversioned index** tracks the installed majors per
 * `<packId>/<kindId>` so a lookup by the unversioned form resolves to
 * the latest installed major — the default referencing convention for
 * trill files.
 */
const registry = new Map<NodeKindId, NodeDescriptor>();

/** unversioned `<packId>/<kindId>` → installed majors, sorted descending. */
const unversionedMajors = new Map<string, number[]>();

function rememberMajor(canonicalId: string): void {
  const split = splitCanonicalNodeType(canonicalId);
  if (!split) return;
  const list = unversionedMajors.get(split.unversioned) ?? [];
  if (!list.includes(split.major)) {
    list.push(split.major);
    list.sort((a, b) => b - a);
    unversionedMajors.set(split.unversioned, list);
  }
}

function forgetMajor(canonicalId: string): void {
  const split = splitCanonicalNodeType(canonicalId);
  if (!split) return;
  const list = unversionedMajors.get(split.unversioned);
  if (!list) return;
  const filtered = list.filter((m) => m !== split.major);
  if (filtered.length === 0) {
    unversionedMajors.delete(split.unversioned);
  } else {
    unversionedMajors.set(split.unversioned, filtered);
  }
}

function resolveUnversioned(unversioned: string): NodeDescriptor | undefined {
  const majors = unversionedMajors.get(unversioned);
  if (!majors || majors.length === 0) return undefined;
  return registry.get(`${unversioned}@${majors[0]}`);
}

const listeners = new Set<() => void>();

/** When >0, {@link pulseRegistryListeners} is a no-op (used during pack reload bursts). */
let registryNotifyDepth = 0;

function flushRegistryListeners(): void {
  for (const listener of listeners) {
    try {
      listener();
    } catch (err) {
      console.error("nodeRegistry listener threw:", err);
    }
  }
}

function pulseRegistryListeners(): void {
  if (registryNotifyDepth > 0) return;
  flushRegistryListeners();
}

/**
 * Run `fn` while suppressing incremental registry subscriber notifications,
 * then emit **once** after `fn` completes (if not nested inside another suspend).
 *
 * Keeps listeners (e.g. React Flow `nodeTypes`) from seeing a transient registry
 * with **zero** pack kinds between `clearPackNodes` + re-registration.
 */
export function withSuspendedRegistryNotifications<T>(fn: () => T): T {
  registryNotifyDepth += 1;
  try {
    return fn();
  } finally {
    registryNotifyDepth -= 1;
    if (registryNotifyDepth < 0) {
      registryNotifyDepth = 0;
    }
    if (registryNotifyDepth === 0) {
      flushRegistryListeners();
    }
  }
}

/**
 * Subscribe to registry mutations. Returns an unsubscribe function.
 *
 * Used by `ToolsMenu` (via `useSyncExternalStore`) so that
 * asynchronously-registered pack descriptors appear in the palette
 * without remounting the component.
 */
export function subscribeToRegistry(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function registerNode(descriptor: NodeDescriptor): void {
  if (registry.has(descriptor.id)) {
    console.warn(`NodeDescriptor for ${descriptor.id} is being overwritten`);
  }
  registry.set(descriptor.id, descriptor);
  rememberMajor(descriptor.id);
  pulseRegistryListeners();
}

/**
 * Drop every descriptor whose {@link NodeDescriptor.source} is `'pack'`.
 *
 * Called before re-registering from `GET /api/packs` so uninstalled packs
 * disappear from the palette; built-ins omit `source` (or use `'core'`) and
 * are kept.
 */
export function clearPackNodes(): void {
  let removed = false;
  for (const [id, d] of registry) {
    if (d.source === 'pack') {
      registry.delete(id);
      forgetMajor(id);
      removed = true;
    }
  }
  if (removed) {
    pulseRegistryListeners();
  }
}

/**
 * Resolve a node type to its descriptor.
 *
 * Resolution order:
 *   1. Exact match (versioned canonical id `<packId>/<kindId>@<major>`).
 *   2. Unversioned-latest: input matches `<packId>/<kindId>` → use the
 *      highest installed major for that family.
 */
function lookupDescriptor(nodeType: NodeKindId): NodeDescriptor | undefined {
  const exact = registry.get(nodeType);
  if (exact) return exact;
  if (typeof nodeType === 'string' && nodeType.includes('/') && !nodeType.includes('@')) {
    return resolveUnversioned(nodeType);
  }
  return undefined;
}

export function getNodeDescriptor(nodeType: NodeKindId): NodeDescriptor {
  const desc = lookupDescriptor(nodeType);
  if (!desc) throw new Error(`No descriptor registered for NodeKindId: ${nodeType}`);
  return desc;
}

export function tryGetNodeDescriptor(nodeType: NodeKindId): NodeDescriptor | undefined {
  return lookupDescriptor(nodeType);
}

export function getAllNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values());
}

export function getPaletteNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values())
    .filter(d => d.inPalette)
    .sort((a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999));
}
