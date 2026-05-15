import { NodeKindId, NodeDescriptor } from './types';

/**
 * The node-kind registry.
 *
 * Keyed by {@link NodeKindId}:
 *   - built-ins use `NodeType` enum members (e.g. `NodeType.DATA_LOADING`); and
 *   - pack kinds use canonical string ids `<packId>/<kindId>@<major>`
 *     (e.g. `"ai.urbanlab.uhvi/uhvi-load@1"`).
 *
 * The signature of {@link registerNode} is intentionally identical for both
 * sources — pack-registration in `registry/packsClient.ts` calls the same
 * function the built-in registrations in `registry/descriptors.ts` do.
 */
const registry = new Map<NodeKindId, NodeDescriptor>();

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
      removed = true;
    }
  }
  if (removed) {
    pulseRegistryListeners();
  }
}

export function getNodeDescriptor(nodeType: NodeKindId): NodeDescriptor {
  const desc = registry.get(nodeType);
  if (!desc) throw new Error(`No descriptor registered for NodeKindId: ${nodeType}`);
  return desc;
}

export function tryGetNodeDescriptor(nodeType: NodeKindId): NodeDescriptor | undefined {
  return registry.get(nodeType);
}

export function getAllNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values());
}

export function getPaletteNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values())
    .filter(d => d.inPalette)
    .sort((a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999));
}
