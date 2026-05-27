/**
 * Package-store client.
 *
 * At boot, the app calls {@link loadInstalledPackages} which hits
 * `GET /api/packages`, clears any prior `source === 'package'` descriptors
 * ({@link clearPackageNodes}), then registers each kind from the response.
 * Subscriber notifications are coalesced so the UI never observes an empty package
 * registry between clear and register.
 *
 * Package descriptors use the same registry slot as built-ins:
 *
 *   - their `id` is the canonical string `<packageId>/<templateId>@<major>`,
 *   - `source === 'package'`, and
 *   - `package` carries the package-provenance metadata used by the palette to
 *     section Built-in vs PACKAGES.
 *
 * Each kind manifest's `lifecycle` string is resolved through
 * {@link getLifecycle}; `iconRef` through {@link resolveIconRef}. The
 * pre-installed `curio.builtin@1` package rides these registries so its
 * kinds behave identically to the legacy hard-coded descriptors.
 */

import { faCube } from '@fortawesome/free-solid-svg-icons';

import { SupportedType } from '../constants';
import {
  inputOnly,
  outputOnly,
  standardInOut,
  useCodeNodeLifecycle,
  usePackageNodeLifecycle,
  withBidirectional,
} from '../adapters/node';
import { packagesApi } from 'api/packagesApi';
import { getToken } from '../utils/authApi';

import { getLifecycle } from './lifecycleRegistry';
import { resolveIconRef } from './iconRegistry';
import {
  clearPackageNodes,
  registerNode,
  withSuspendedRegistryNotifications,
} from './nodeRegistry';
import type {
  NodeCategory,
  NodeDescriptor,
  PortDef,
} from './types';

interface RawPackageTemplate {
  id: string; // canonical "<packageId>/<templateId>@<major>"
  templateId: string;
  label: string;
  category: string;
  engine: 'python' | 'javascript';
  description: string;
  icon: string | null;
  iconRef: string | null;
  lifecycle: string | null;
  paletteOrder: number | null;
  editor: 'code' | 'widgets' | 'grammar' | 'none';
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  grammarId: string | null;
  badge: string | null;
  inputPorts: Array<{ types: string[]; cardinality?: string }>;
  outputPorts: Array<{ types: string[]; cardinality?: string }>;
  /** Optional package-relative path to a single starter source file. */
  source: string | null;
  bidirectional: boolean;
  containerStyle: {
    nodeWidth?: number;
    nodeHeight?: number;
    noContent?: boolean;
    disablePlay?: boolean;
  } | null;
  hasProvenance: boolean | null;
  tutorialId: string | null;
}

interface RawPackage {
  packageId: string;
  major: number;
  version: string;
  name: string;
  publisher: string;
  description: string;
  license: string | null;
  permissions: string[];
  templates: RawPackageTemplate[];
  /** Path (relative to package dir) of a pre-built JS bundle to load before
   *  descriptor build. Registers this package's lifecycle hooks via
   *  `window.curio.registerLifecycle`. See docs/EXTENDING.md §5. */
  lifecycleScript?: string;
  /** Server-side dirname (`<packageId>@<major>`). Used for static-asset
   *  URLs like `/api/packages/<dirName>/file/<...>`. */
  dirName?: string;
  lineage: {
    forkedFrom: { packageId: string; major: number };
    root: { packageId: string; major: number };
  } | null;
  readOnly?: boolean;
  createdAt?: string;
  createdAtMs?: number | string;
  /** Epoch ms when the package manifest was last written on disk (API diagnostic). */
  installUpdatedAtMs?: number | string;
}

const KNOWN_CATEGORIES: ReadonlySet<NodeCategory> = new Set([
  'data',
  'computation',
  'vis_grammar',
  'vis_simple',
  'flow',
]);

function asCategory(raw: string): NodeCategory {
  return (KNOWN_CATEGORIES.has(raw as NodeCategory) ? raw : 'computation') as NodeCategory;
}

export const BUILTIN_PACKAGE_ID = 'curio.builtin';

function asSupportedTypes(raw: string[]): SupportedType[] {
  const known = new Set(Object.values(SupportedType));
  return raw.filter((t) => known.has(t as SupportedType)) as SupportedType[];
}

function asPortDef(p: { types: string[]; cardinality?: string }): PortDef {
  return {
    types: asSupportedTypes(p.types),
    cardinality: (p.cardinality ?? '1') as PortDef['cardinality'],
  };
}

/** Coerces API numeric-ish fields where JSON may stringify large ints in edge proxies. */
function normalizedEpochMs(raw: unknown): number {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string') {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return 0;
}

function normalizedInstallUpdatedAtMs(raw: RawPackage['installUpdatedAtMs']): number | undefined {
  if (raw === undefined || raw === null) return undefined;
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw;
  if (typeof raw === 'string') {
    const s = raw.trim();
    if (!s) return undefined;
    const n = Number(s);
    if (Number.isFinite(n)) return n;
  }
  return undefined;
}

function portCardinalityIconType(ports: PortDef[]): '1' | '2' | 'N' | undefined {
  if (ports.length === 0) return undefined;
  // 'N' wins if any port has unbounded-upper cardinality — range form ("[1,n]", "[0,n]") or bare "n".
  if (ports.some((p) => typeof p.cardinality === 'string' && /^\s*n\s*$|,\s*n\s*]/i.test(p.cardinality))) {
    return 'N';
  }
  return ports.length > 1 ? '2' : '1';
}

function buildDescriptor(pkg: RawPackage, template: RawPackageTemplate, order: number): NodeDescriptor {
  const inputPorts = template.inputPorts.map(asPortDef);
  const outputPorts = template.outputPorts.map(asPortDef);

  const installMsMaybe = normalizedInstallUpdatedAtMs(pkg.installUpdatedAtMs);

  let handles;
  if (inputPorts.length === 0) handles = outputOnly();
  else if (outputPorts.length === 0) handles = inputOnly();
  else handles = standardInOut();
  if (template.bidirectional) handles = withBidirectional(handles);

  const isBuiltin = pkg.packageId === BUILTIN_PACKAGE_ID;
  const lookedUpLifecycle = template.lifecycle ? getLifecycle(template.lifecycle) : undefined;
  const lifecycle = lookedUpLifecycle
    ?? (isBuiltin ? useCodeNodeLifecycle : usePackageNodeLifecycle);
  const icon = resolveIconRef(template.iconRef) ?? faCube;
  const paletteOrder = typeof template.paletteOrder === 'number'
    ? template.paletteOrder
    : 1000 + order; // third-party packages without explicit order sort after built-ins

  // F4: editor === 'none' means no editor surface at all; keeping a truthy
  // config object would cause UniversalNode to mount NodeEditor anyway.
  const adapterEditor = template.editor === 'none'
    ? null
    : { code: template.hasCode, grammar: template.hasGrammar, widgets: template.hasWidgets };

  const container: NodeDescriptor['adapter']['container'] = {
    handleType:
      inputPorts.length === 0
        ? 'out'
        : outputPorts.length === 0
          ? 'in'
          : 'in/out',
    ...(template.containerStyle?.nodeWidth !== undefined ? { nodeWidth: template.containerStyle.nodeWidth } : {}),
    ...(template.containerStyle?.nodeHeight !== undefined ? { nodeHeight: template.containerStyle.nodeHeight } : {}),
    ...(template.containerStyle?.noContent !== undefined ? { noContent: template.containerStyle.noContent } : {}),
    ...(template.containerStyle?.disablePlay !== undefined ? { disablePlay: template.containerStyle.disablePlay } : {}),
  };

  return {
    id: template.id,
    source: 'package',
    package: {
      packageId: pkg.packageId,
      major: pkg.major,
      version: pkg.version,
      name: pkg.name,
      publisher: pkg.publisher,
      source: template.source ?? undefined,
      ...(pkg.lineage
        ? {
            lineage: {
              forkedFrom: { ...pkg.lineage.forkedFrom },
              root: { ...pkg.lineage.root },
            },
          }
        : {}),
      ...(pkg.readOnly === true ? { readOnly: true } : {}),
      ...(typeof pkg.createdAt === 'string' && pkg.createdAt.trim()
        ? { createdAt: pkg.createdAt.trim() }
        : {}),
      createdAtMs: normalizedEpochMs(pkg.createdAtMs),
      ...(installMsMaybe !== undefined ? { installUpdatedAtMs: installMsMaybe } : {}),
    },
    category: asCategory(template.category),
    label: template.label,
    icon,
    inputPorts,
    outputPorts,
    editor: template.editor,
    inPalette: true,
    paletteOrder,
    description: template.description,
    hasCode: template.hasCode,
    hasWidgets: template.hasWidgets,
    hasGrammar: template.hasGrammar,
    ...(template.hasProvenance !== null ? { hasProvenance: template.hasProvenance } : {}),
    ...(template.tutorialId ? { tutorialId: template.tutorialId } : {}),
    ...(template.grammarId ? { grammarId: template.grammarId } : {}),
    ...(template.badge ? { badge: template.badge } : isBuiltin ? {} : { badge: 'PACKAGE' as const }),
    adapter: {
      handles,
      editor: adapterEditor,
      container,
      inputIconType: portCardinalityIconType(inputPorts),
      outputIconType: portCardinalityIconType(outputPorts),
      useLifecycle: lifecycle,
    },
  };
}

/** Internal helper exposed for unit tests. */
export function registerPackageTemplates(packages: RawPackage[]): NodeDescriptor[] {
  const registered: NodeDescriptor[] = [];
  let order = 0;
  for (const pkg of packages) {
    for (const template of pkg.templates) {
      const descriptor = buildDescriptor(pkg, template, order++);
      registerNode(descriptor);
      registered.push(descriptor);
    }
  }
  return registered;
}

/**
 * Fetch installed packages from the backend and register a descriptor per kind.
 *
 * When ``projectFilter`` is provided (a set of dirNames from the current
 * project's lockfile), only packages whose dirName is in the filter — plus
 * the always-on ``curio.builtin`` — are registered. This is how the palette
 * stays project-scoped despite the user-store being shared across projects.
 *
 * When the filter is ``null`` (no project loaded, /catalog page, bootstrap),
 * every installed package is registered.
 *
 * Returns the list of registered descriptors (empty if the user has no
 * packages installed, or if the request fails). Failure is logged and
 * swallowed so app boot never blocks on package discovery.
 */
/**
 * Loads a package's pre-built `lifecycleScript` bundle by injecting a
 * <script> tag pointed at `/api/packages/<dirName>/file/<script>`. The
 * bundle's top-level side-effect calls `window.curio.registerLifecycle`
 * for each lifecycle hook it ships, so by the time the returned Promise
 * resolves the lifecycle keys declared in the package's templates are
 * registered and `buildDescriptor`'s lookup will succeed.
 *
 * Errors are swallowed (and logged) — one broken package's bundle
 * shouldn't take the whole canvas down. The descriptors for its
 * templates will fall back to `usePackageNodeLifecycle` (generic code
 * editor) so the palette still renders.
 */
async function loadPackageLifecycleScripts(packages: RawPackage[]): Promise<void> {
  const base = process.env.BACKEND_URL ?? '';
  const targets = packages.filter((p) => p.lifecycleScript && p.dirName);
  if (targets.length === 0) return;
  const token = getToken();
  // Sequential, not Promise.all, so each bundle's top-level
  // `registerLifecycle` side-effect runs before the next bundle's does —
  // matches the deterministic order the old `<script async={false}>` chain
  // guaranteed.
  for (const p of targets) {
    // De-dupe across re-renders: the same bundle should only load once
    // even if refreshPackageRegistry runs again.
    const existing = document.querySelector(`script[data-curio-package="${p.packageId}@${p.major}"]`);
    if (existing) continue;
    const url = `${base}/api/packages/${encodeURIComponent(p.dirName!)}/file/${p.lifecycleScript}`;
    try {
      // ``<script src>`` cannot carry an Authorization header, and the
      // file-serving endpoint is under ``@require_auth``. Firefox's ORB
      // then blocks the resulting 401 response and the bundle never
      // evaluates. Fetch via ``fetch`` (with the Bearer token) and
      // inject the body as inline script text instead.
      const headers: Record<string, string> = {};
      if (token) headers.Authorization = `Bearer ${token}`;
      // ``cache: 'no-store'`` bypasses the HTTP cache entirely. Without it,
      // a stale bundle (e.g. an earlier broken build still in the disk
      // cache) gets re-evaluated forever — the file-serving endpoint
      // doesn't set strong cache headers, so the browser uses its
      // heuristic freshness window. Package bundles are small + fetched
      // once per boot, so the cost of bypassing the cache is negligible
      // next to the correctness win.
      const res = await fetch(url, { headers, cache: 'no-store' });
      if (!res.ok) {
        console.warn(
          `[curio] failed to load lifecycle script for ${p.packageId}@${p.major}: HTTP ${res.status}`,
        );
        continue;
      }
      const code = await res.text();
      const s = document.createElement('script');
      s.dataset.curioPackage = `${p.packageId}@${p.major}`;
      s.textContent = code;
      document.head.appendChild(s);
    } catch (err) {
      console.warn(`[curio] failed to load lifecycle script for ${p.packageId}@${p.major}:`, err);
      // never throw — descriptor build still proceeds (with code-editor fallback)
    }
  }
}

export async function loadInstalledPackages(
  projectFilter: ReadonlySet<string> | null = null,
): Promise<NodeDescriptor[]> {
  try {
    const { packages } = await packagesApi.listInstalled();
    const filtered = projectFilter
      ? (packages ?? []).filter(
          (p) =>
            p.packageId === BUILTIN_PACKAGE_ID ||
            projectFilter.has(`${p.packageId}@${p.major}`),
        )
      : (packages ?? []);
    // Inject and await any `lifecycleScript` bundles BEFORE descriptor
    // build so the lifecycle keys referenced in the templates are
    // actually registered against the global lifecycle registry. Without
    // this step, `getLifecycle()` returns undefined and packages with
    // custom lifecycles soft-fail to the package code editor.
    await loadPackageLifecycleScripts(filtered);
    // Replace package-derived kinds wholesale — `registerNode` only adds/overwrites,
    // so without this pass, uninstalled packages would leave stale palette entries.
    // Notify subscribers only after clear + register so React Flow keeps package node types wired.
    return withSuspendedRegistryNotifications(() => {
      clearPackageNodes();
      return registerPackageTemplates(filtered);
    });
  } catch (error) {
    const status = (error as { status?: number }).status;
    if (status !== 401) {
      console.warn('Failed to load installed packages:', error);
    }
    return [];
  }
}
