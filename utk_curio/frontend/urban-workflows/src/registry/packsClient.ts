/**
 * Pack-store client.
 *
 * At boot, the app calls {@link loadInstalledPacks} which hits
 * `GET /api/packs`, clears any prior `source === 'pack'` descriptors
 * ({@link clearPackNodes}), then registers each kind from the response.
 * Subscriber notifications are coalesced so the UI never observes an empty pack
 * registry between clear and register.
 *
 * Pack descriptors use the same registry slot as built-ins — see
 * ``docs/nodesfactory@docs/frontend.md`` (registry refresh and pack descriptors). The difference is:
 *
 *   - their `id` is the canonical string `<packId>/<kindId>@<major>`,
 *   - `source === 'pack'`, and
 *   - `pack` carries the pack-provenance metadata used by the palette to
 *     section Built-in vs PACKS.
 * 
 * A specific lifecycle hook is needed for pack nodes: `usePackNodeLifecycle`
 * which injects the default template code into the editor when the node is
 * first dropped onto the canvas.
 */

import {
  faChartLine,
  faCodeMerge,
  faCube,
  faDatabase,
  faUpload,
  faTable,
} from '@fortawesome/free-solid-svg-icons';
import { faPython } from '@fortawesome/free-brands-svg-icons';

import { SupportedType } from '../constants';
import {
  inputOnly,
  outputOnly,
  standardInOut,
  usePackNodeLifecycle,
} from '../adapters/node';
import { packsApi } from 'api/packsApi';

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
  editor: 'code' | 'widgets' | 'grammar' | 'none';
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  inputPorts: Array<{ types: string[]; cardinality?: string }>;
  outputPorts: Array<{ types: string[]; cardinality?: string }>;
  templateDir: string | null;
  defaultTemplate: string | null;
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

const PACK_CATEGORY_ICONS: Record<NodeCategory, typeof faCube> = {
  data: faUpload,
  computation: faPython,
  vis_grammar: faChartLine,
  vis_simple: faTable,
  flow: faCodeMerge,
};

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

function buildDescriptor(pack: RawPack, kind: RawPackKind, order: number): NodeDescriptor {
  const inputPorts = kind.inputPorts.map(asPortDef);
  const outputPorts = kind.outputPorts.map(asPortDef);

  const installMsMaybe = normalizedInstallUpdatedAtMs(pack.installUpdatedAtMs);

  let handles;
  if (inputPorts.length === 0) handles = outputOnly();
  else if (outputPorts.length === 0) handles = inputOnly();
  else handles = standardInOut();

  return {
    id: kind.id,
    source: 'pack',
    pack: {
      packId: pack.packId,
      major: pack.major,
      version: pack.version,
      name: pack.name,
      publisher: pack.publisher,
      defaultTemplate: kind.defaultTemplate ?? undefined,
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
    icon: PACK_CATEGORY_ICONS[asCategory(kind.category)] ?? faCube,
    inputPorts,
    outputPorts,
    editor: kind.editor,
    inPalette: true,
    paletteOrder: 1000 + order, // packs sort after built-ins
    description: kind.description,
    hasCode: kind.hasCode,
    hasWidgets: kind.hasWidgets,
    hasGrammar: kind.hasGrammar,
    badge: 'PACK',
    adapter: {
      handles,
      editor: {
        code: kind.hasCode,
        grammar: kind.hasGrammar,
        widgets: kind.hasWidgets,
      },
      container: {
        handleType:
          inputPorts.length === 0
            ? 'out'
            : outputPorts.length === 0
              ? 'in'
              : 'in/out',
      },
      inputIconType: inputPorts.length > 0 ? (inputPorts.length > 1 ? '2' : '1') : undefined,
      outputIconType: outputPorts.length > 0 ? (outputPorts.length > 1 ? '2' : '1') : undefined,
      showTemplateModal: !!kind.templateDir,
      useLifecycle: usePackNodeLifecycle,
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
    // Matches Nodes Hub (`packsApi.listInstalled`): same URL and auth wiring as `apiFetch`.
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
