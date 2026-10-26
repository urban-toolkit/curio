/**
 * IconRegistry: resolves `iconRef` strings from package manifests into
 * FontAwesome icon definitions used by node descriptors.
 *
 * Manifests can't import JS icon constants, so they name an icon by a string
 * key: `"fa-solid:<name>"` or `"fa-brands:<name>"`, any icon of Font Awesome's
 * free solid or brands set. The icons curio.builtin@1's templates name are
 * bundled and registered below, with the cube every unknown name falls back
 * to. Any other icon is loaded on demand, one small file per icon, by
 * {@link loadIconRefs}, which the package loader awaits before it builds
 * descriptors, so {@link resolveIconRef} stays synchronous.
 */

import {
  faChartLine,
  faCity,
  faCube,
  faDatabase,
  faDownload,
  faHandPointer,
  faNoteSticky,
  faObjectGroup,
  faRectangleList,
  faServer,
  faTable,
  faUpload,
} from '@fortawesome/free-solid-svg-icons';
import { faJs, faPython } from '@fortawesome/free-brands-svg-icons';
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';

const iconRegistry = new Map<string, IconDefinition>();

export function registerIcon(ref: string, icon: IconDefinition): void {
  iconRegistry.set(ref, icon);
}

const warnedMisses = new Set<string>();

export function resolveIconRef(ref: string | null | undefined): IconDefinition {
  if (!ref) return faCube;
  const hit = iconRegistry.get(ref);
  if (hit) return hit;
  if (!warnedMisses.has(ref)) {
    warnedMisses.add(ref);
    console.warn(
      `[iconRegistry] no Font Awesome solid or brands icon is loaded for "${ref}"; falling back to faCube.`,
    );
  }
  return faCube;
}

// The icons curio.builtin@1's templates name, and the cube.
registerIcon('fa-solid:upload', faUpload);
registerIcon('fa-solid:download', faDownload);
registerIcon('fa-solid:database', faDatabase);
registerIcon('fa-solid:server', faServer);
registerIcon('fa-solid:rectangle-list', faRectangleList);
registerIcon('fa-solid:chart-line', faChartLine);
registerIcon('fa-solid:table', faTable);
registerIcon('fa-solid:city', faCity);
registerIcon('fa-solid:object-group', faObjectGroup);
registerIcon('fa-solid:hand-pointer', faHandPointer);
registerIcon('fa-solid:note-sticky', faNoteSticky);
registerIcon('fa-solid:cube', faCube);
registerIcon('fa-brands:js', faJs);
registerIcon('fa-brands:python', faPython);

type IconModule = Record<string, unknown>;

/**
 * One loader per pack an `iconRef` can name, by its prefix. Each imports the
 * one module of the named icon (`@fortawesome/free-solid-svg-icons/faTree`),
 * which webpack splits into a chunk of its own; `webpackInclude` keeps the
 * packs' index files out of those chunks.
 */
const PACKS: Record<string, (moduleName: string) => Promise<IconModule>> = {
  'fa-solid': (moduleName) =>
    import(
      /* webpackInclude: /[\\/]fa[A-Z0-9][A-Za-z0-9]*\.js$/ */
      `@fortawesome/free-solid-svg-icons/${moduleName}`
    ),
  'fa-brands': (moduleName) =>
    import(
      /* webpackInclude: /[\\/]fa[A-Z0-9][A-Za-z0-9]*\.js$/ */
      `@fortawesome/free-brands-svg-icons/${moduleName}`
    ),
};

/** An icon name as Font Awesome writes it: `map-location-dot`, `500px`. */
const ICON_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** `map-location-dot` -> `faMapLocationDot`, its module's name and export. */
function moduleNameOf(name: string): string {
  return `fa${name
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('')}`;
}

function isIconDefinition(value: unknown): value is IconDefinition {
  const icon = value as IconDefinition | null | undefined;
  return (
    !!icon &&
    typeof icon.prefix === 'string' &&
    typeof icon.iconName === 'string' &&
    Array.isArray(icon.icon)
  );
}

/** Refs that name no icon of either pack; they keep the cube. */
const misses = new Set<string>();
const inFlight = new Map<string, Promise<void>>();

async function loadIconRef(ref: string): Promise<void> {
  const colon = ref.indexOf(':');
  const pack = colon > 0 ? PACKS[ref.slice(0, colon)] : undefined;
  const name = ref.slice(colon + 1);
  if (!pack || !ICON_NAME.test(name)) {
    misses.add(ref);
    return;
  }
  const moduleName = moduleNameOf(name);
  let loaded: IconModule;
  try {
    loaded = await pack(moduleName);
  } catch (error) {
    // A name the pack does not have is a module that does not exist. Anything
    // else (a chunk that failed to download) is tried again on the next load.
    if ((error as { code?: string } | null)?.code === 'MODULE_NOT_FOUND') misses.add(ref);
    else console.warn(`[iconRegistry] could not load the icon "${ref}":`, error);
    return;
  }
  const icon = loaded[moduleName] ?? loaded.definition;
  if (isIconDefinition(icon)) registerIcon(ref, icon);
  else misses.add(ref);
}

/**
 * Load every icon `refs` name that is not registered yet. The returned
 * promise never rejects: it settles once each icon has loaded or turned out
 * not to exist, and a ref that names nothing resolves to the cube. Returns
 * null when there is nothing to wait for.
 */
export function loadIconRefs(refs: Iterable<string | null | undefined>): Promise<void> | null {
  const pending: Promise<void>[] = [];
  for (const ref of new Set(refs)) {
    if (!ref || iconRegistry.has(ref) || misses.has(ref)) continue;
    let load = inFlight.get(ref);
    if (!load) {
      load = loadIconRef(ref)
        .catch(() => undefined)
        .finally(() => inFlight.delete(ref));
      inFlight.set(ref, load);
    }
    pending.push(load);
  }
  return pending.length > 0 ? Promise.all(pending).then(() => undefined) : null;
}
