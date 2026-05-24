/**
 * IconRegistry: resolves `iconRef` strings from pack manifests into
 * FontAwesome icon definitions used by node descriptors.
 *
 * Manifests can't import JS icon constants, so they reference icons by
 * a string key like `"fa-solid:upload"`. The frontend bootstraps the
 * registry with the icons it actually uses (built-ins + common pack
 * icons); unknown refs fall back to `faCube`.
 */

import {
  faCity,
  faCube,
  faChartColumn,
  faChartLine,
  faCodeMerge,
  faCubes,
  faDatabase,
  faDownload,
  faMap,
  faMapLocationDot,
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
      `[iconRegistry] no icon registered for "${ref}"; falling back to faCube. ` +
      `Register it via registerIcon() in src/registry/iconRegistry.ts.`,
    );
  }
  return faCube;
}

// Bootstrap the icons used by the curio.builtin@1 pack and common third-party packs.
registerIcon('fa-solid:upload', faUpload);
registerIcon('fa-solid:download', faDownload);
registerIcon('fa-solid:database', faDatabase);
registerIcon('fa-solid:server', faServer);
registerIcon('fa-solid:rectangle-list', faRectangleList);
registerIcon('fa-solid:chart-line', faChartLine);
registerIcon('fa-solid:chart-column', faChartColumn);
registerIcon('fa-solid:table', faTable);
registerIcon('fa-solid:city', faCity);
registerIcon('fa-solid:cubes', faCubes);
registerIcon('fa-solid:cube', faCube);
registerIcon('fa-solid:map', faMap);
registerIcon('fa-solid:map-location-dot', faMapLocationDot);
registerIcon('fa-solid:code-merge', faCodeMerge);
registerIcon('fa-brands:js', faJs);
registerIcon('fa-brands:python', faPython);
