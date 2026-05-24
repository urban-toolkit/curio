/**
 * Pack-store client.
 *
 * At boot, the app calls {@link loadInstalledPacks} which hits
 * `GET /api/packs`, clears any prior `source === 'pack'` descriptors
 * ({@link clearPackNodes}), then registers each kind from the response.
 * Subscriber notifications are coalesced so the UI never observes an empty pack
 * registry between clear and register.
 *
 * Pack descriptors use the same registry slot as built-ins:
 *
 *   - their `id` is the canonical string `<packId>/<kindId>@<major>`,
 *   - `source === 'pack'`, and
 *   - `pack` carries the pack-provenance metadata used by the palette to
 *     section Built-in vs PACKS.
 *
 * Each kind manifest's `lifecycle` string is resolved through
 * {@link getLifecycle}; `iconRef` through {@link resolveIconRef}. The
 * pre-installed `curio.builtin@1` pack rides these registries so its
 * kinds behave identically to the legacy hard-coded descriptors.
 */

import { faCube } from '@fortawesome/free-solid-svg-icons';

import { SupportedType } from '../constants';
import {
  inputOnly,
  outputOnly,
  standardInOut,
  useCodeNodeLifecycle,
  usePackNodeLifecycle,
  withBidirectional,
} from '../adapters/node';
import { packsApi } from 'api/packsApi';

import { getLifecycle } from './lifecycleRegistry';
import { resolveIconRef } from './iconRegistry';
import {
  clearPackNodes,
  registerNode,
  withSuspendedRegistryNotifications,
} from './nodeRegistry';
import type {
  NodeCategory,
  NodeDescriptor,
  PortDef,
} from './types';

interface RawPackKind {
  id: string; // canonical "<packId>/<kindId>@<major>"
  kindId: string;
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
  /** Optional pack-relative path to a single starter source file. */
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

interface RawPack {
  packId: string;
  major: number;
  version: string;
  name: string;
  publisher: string;
  description: string;
  license: string | null;
  permissions: string[];
  kinds: RawPackKind[];
  lineage: {
    forkedFrom: { packId: string; major: number };
    root: { packId: string; major: number };
  } | null;
  paletteDock?: { hiddenFromForkPaletteDock?: boolean };
  createdAt?: string;
  createdAtMs?: number | string;
  /** Epoch ms when the pack manifest was last written on disk (API diagnostic). */
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

export const BUILTIN_PACK_ID = 'curio.builtin';

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

function normalizedInstallUpdatedAtMs(raw: RawPack['installUpdatedAtMs']): number | undefined {
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

function buildDescriptor(pack: RawPack, kind: RawPackKind, order: number): NodeDescriptor {
  const inputPorts = kind.inputPorts.map(asPortDef);
  const outputPorts = kind.outputPorts.map(asPortDef);

  const installMsMaybe = normalizedInstallUpdatedAtMs(pack.installUpdatedAtMs);

  let handles;
  if (inputPorts.length === 0) handles = outputOnly();
  else if (outputPorts.length === 0) handles = inputOnly();
  else handles = standardInOut();
  if (kind.bidirectional) handles = withBidirectional(handles);

  const isBuiltin = pack.packId === BUILTIN_PACK_ID;
  const lookedUpLifecycle = kind.lifecycle ? getLifecycle(kind.lifecycle) : undefined;
  const lifecycle = lookedUpLifecycle
    ?? (isBuiltin ? useCodeNodeLifecycle : usePackNodeLifecycle);
  const icon = resolveIconRef(kind.iconRef) ?? faCube;
  const paletteOrder = typeof kind.paletteOrder === 'number'
    ? kind.paletteOrder
    : 1000 + order; // third-party packs without explicit order sort after built-ins

  // F4: editor === 'none' means no editor surface at all; keeping a truthy
  // config object would cause UniversalNode to mount NodeEditor anyway.
  const adapterEditor = kind.editor === 'none'
    ? null
    : { code: kind.hasCode, grammar: kind.hasGrammar, widgets: kind.hasWidgets };

  const container: NodeDescriptor['adapter']['container'] = {
    handleType:
      inputPorts.length === 0
        ? 'out'
        : outputPorts.length === 0
          ? 'in'
          : 'in/out',
    ...(kind.containerStyle?.nodeWidth !== undefined ? { nodeWidth: kind.containerStyle.nodeWidth } : {}),
    ...(kind.containerStyle?.nodeHeight !== undefined ? { nodeHeight: kind.containerStyle.nodeHeight } : {}),
    ...(kind.containerStyle?.noContent !== undefined ? { noContent: kind.containerStyle.noContent } : {}),
    ...(kind.containerStyle?.disablePlay !== undefined ? { disablePlay: kind.containerStyle.disablePlay } : {}),
  };

  return {
    id: kind.id,
    source: 'pack',
    pack: {
      packId: pack.packId,
      major: pack.major,
      version: pack.version,
      name: pack.name,
      publisher: pack.publisher,
      source: kind.source ?? undefined,
      ...(pack.lineage
        ? {
            lineage: {
              forkedFrom: { ...pack.lineage.forkedFrom },
              root: { ...pack.lineage.root },
            },
          }
        : {}),
      ...(pack.paletteDock?.hiddenFromForkPaletteDock === true
        ? { hiddenFromForkPaletteDock: true }
        : {}),
      ...(typeof pack.createdAt === 'string' && pack.createdAt.trim()
        ? { createdAt: pack.createdAt.trim() }
        : {}),
      createdAtMs: normalizedEpochMs(pack.createdAtMs),
      ...(installMsMaybe !== undefined ? { installUpdatedAtMs: installMsMaybe } : {}),
    },
    category: asCategory(kind.category),
    label: kind.label,
    icon,
    inputPorts,
    outputPorts,
    editor: kind.editor,
    inPalette: true,
    paletteOrder,
    description: kind.description,
    hasCode: kind.hasCode,
    hasWidgets: kind.hasWidgets,
    hasGrammar: kind.hasGrammar,
    ...(kind.hasProvenance !== null ? { hasProvenance: kind.hasProvenance } : {}),
    ...(kind.tutorialId ? { tutorialId: kind.tutorialId } : {}),
    ...(kind.grammarId ? { grammarId: kind.grammarId } : {}),
    ...(kind.badge ? { badge: kind.badge } : isBuiltin ? {} : { badge: 'PACK' as const }),
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
export function registerPackKinds(packs: RawPack[]): NodeDescriptor[] {
  const registered: NodeDescriptor[] = [];
  let order = 0;
  for (const pack of packs) {
    for (const kind of pack.kinds ?? []) {
      const descriptor = buildDescriptor(pack, kind, order++);
      registerNode(descriptor);
      registered.push(descriptor);
    }
  }
  return registered;
}

/**
 * Fetch installed packs from the backend and register a descriptor per kind.
 *
 * Returns the list of registered descriptors (empty if the user has no
 * packs installed, or if the request fails). Failure is logged and
 * swallowed so app boot never blocks on pack discovery.
 */
export async function loadInstalledPacks(): Promise<NodeDescriptor[]> {
  try {
    const { packs } = await packsApi.listInstalled();
    // Replace pack-derived kinds wholesale — `registerNode` only adds/overwrites,
    // so without this pass, uninstalled packs would leave stale palette entries.
    // Notify subscribers only after clear + register so React Flow keeps pack node types wired.
    return withSuspendedRegistryNotifications(() => {
      clearPackNodes();
      return registerPackKinds(packs ?? []);
    });
  } catch (error) {
    const status = (error as { status?: number }).status;
    if (status !== 401) {
      console.warn('Failed to load installed packs:', error);
    }
    return [];
  }
}
