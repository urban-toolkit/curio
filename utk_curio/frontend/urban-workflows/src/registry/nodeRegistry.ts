import { NodeTemplateId, NodeDescriptor } from './types';
import { BUILTIN_PACKAGE_ID, splitCanonicalNodeType } from './packageKeys';
import {
  getCurrentProjectPackages,
  subscribe as subscribeProjectPackages,
} from './projectPackagesStore';

/**
 * The node-kind registry.
 *
 * Keyed by canonical type string. Versioned ids like
 * `"ai.urbanlab.uhvi/uhvi-load@1"` are stored as-is. A secondary
 * **unversioned index** tracks the installed majors per
 * `<packageId>/<templateId>` so a lookup by the unversioned form resolves to
 * the latest installed major — the default referencing convention for
 * trill files.
 */
const registry = new Map<NodeTemplateId, NodeDescriptor>();

/** unversioned `<packageId>/<templateId>` → installed majors, sorted descending. */
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

/** When >0, {@link pulseRegistryListeners} is a no-op (used during package reload bursts). */
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
 * with **zero** package kinds between `clearPackageNodes` + re-registration.
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
 * asynchronously-registered package descriptors appear in the palette
 * without remounting the component.
 */
export function subscribeToRegistry(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function registerNode(descriptor: NodeDescriptor): void {
  const prev = registry.get(descriptor.id);
  // `clearPackageNodes` preserves `curio.builtin@1` descriptors across refreshes
  // (see comment there), so every `refreshPackageRegistry` round re-registers
  // the same builtin templates on top of themselves. That's intentional and
  // not worth warning about — only flag when the descriptor genuinely changes.
  if (prev && prev.package?.version !== descriptor.package?.version) {
    console.warn(`NodeDescriptor for ${descriptor.id} is being overwritten`);
  }
  registry.set(descriptor.id, descriptor);
  rememberMajor(descriptor.id);
  pulseRegistryListeners();
}

/**
 * Drop every descriptor whose {@link NodeDescriptor.source} is `'package'`
 * — EXCEPT the always-installed ``curio.builtin@1`` templates, which stay
 * registered across refreshes.
 *
 * Called before re-registering from `GET /api/packages` so uninstalled
 * third-party packages disappear from the palette. We keep built-ins
 * across the clear→re-register cycle because any node on the canvas with
 * `nodeType: "curio.builtin/..."` calls ``getNodeDescriptor`` on render;
 * if the registry shows a transient empty state for a built-in id (even
 * with ``withSuspendedRegistryNotifications`` suspending listener
 * notifications), an in-flight ``UniversalNodeBody`` render still throws
 * "No descriptor registered" — which is exactly what e2e workflow tests
 * hit when ``ProjectLoader`` runs ``refreshPackageRegistry()`` while the
 * loaded workflow's nodes are mounting.
 */
export function clearPackageNodes(): void {
  let removed = false;
  for (const [id, d] of registry) {
    if (d.source === 'package' && d.package?.packageId !== 'curio.builtin') {
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
 *   1. Exact match (versioned canonical id `<packageId>/<templateId>@<major>`).
 *   2. Unversioned-latest: input matches `<packageId>/<templateId>` → use the
 *      highest installed major for that family.
 */
function lookupDescriptor(nodeType: NodeTemplateId): NodeDescriptor | undefined {
  const exact = registry.get(nodeType);
  if (exact) return exact;
  if (typeof nodeType === 'string' && nodeType.includes('/') && !nodeType.includes('@')) {
    return resolveUnversioned(nodeType);
  }
  return undefined;
}

export function getNodeDescriptor(nodeType: NodeTemplateId): NodeDescriptor {
  const desc = lookupDescriptor(nodeType);
  if (!desc) throw new Error(`No descriptor registered for NodeTemplateId: ${nodeType}`);
  return desc;
}

export function tryGetNodeDescriptor(nodeType: NodeTemplateId): NodeDescriptor | undefined {
  return lookupDescriptor(nodeType);
}

export function getAllNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values());
}

/**
 * Is *d* offered by a dataflow whose lockfile is *scope*?
 *
 * ``null`` scope means no dataflow is open (the project list, the catalog
 * pages), where there is nothing to filter by. The builtin package is always
 * in, because every dataflow has it and it is never in a lockfile the user
 * edits.
 *
 * Takes the scope rather than reading it, so one list is filtered against one
 * snapshot: reading per descriptor would let a mid-iteration store write split
 * the result between two dataflows.
 */
function inDataflowScope(d: NodeDescriptor, scope: ReadonlySet<string> | null): boolean {
  if (scope === null) return true;
  const pkg = d.package;
  if (!pkg) return true;
  if (pkg.packageId === BUILTIN_PACKAGE_ID) return true;
  return scope.has(`${pkg.packageId}@${pkg.major}`);
}

/**
 * The palette's kinds, scoped to the open dataflow.
 *
 * The scope used to be applied at WRITE time: ``loadInstalledPackages`` took a
 * filter and registered only the packages that passed it, so the registry held
 * one project's view and every scope change needed a refetch to correct it. Any
 * path that changed the scope without refetching left the previous dataflow's
 * packages in the palette, which is exactly what #204 reported. Filtering on
 * read makes that unrepresentable: the registry holds everything installed, and
 * the answer follows the scope with no refetch and no ordering to get wrong.
 */
export function getPaletteNodeTypes(): NodeDescriptor[] {
  const scope = getCurrentProjectPackages();
  return Array.from(registry.values())
    .filter(d => d.inPalette && inDataflowScope(d, scope))
    .sort((a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999));
}

// The palette reads through ``useSyncExternalStore(subscribeToRegistry, ...)``,
// so with the filter on the read side a scope change has to pulse the same
// listeners a registration does - otherwise switching dataflow would leave the
// previous palette painted until something else happened to touch the registry.
//
// Only when the scope actually CHANGES, though. The store is written on paths
// that re-apply the same set (a drawer reload, a lockfile refetch that agrees
// with what is already there), and pulsing on those re-rendered the packages
// palette for no visible reason - which unmounted anything anchored inside it,
// including the package metadata modal opened from a palette row.
let lastScopeSignature: string | null = null;
subscribeProjectPackages(() => {
  const scope = getCurrentProjectPackages();
  // Sorted so a set rebuilt in a different order is still the same scope.
  const signature = scope === null ? "*" : Array.from(scope).sort().join(",");
  if (signature === lastScopeSignature) return;
  lastScopeSignature = signature;
  pulseRegistryListeners();
});
