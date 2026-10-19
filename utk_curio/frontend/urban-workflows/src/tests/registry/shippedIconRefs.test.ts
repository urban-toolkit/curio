/**
 * Every `iconRef` a shipped package names draws exactly the Font Awesome icon
 * it names, so no shipped node falls back to the generic cube or draws another
 * icon. The suite builds the palette the way the app does, through
 * `loadInstalledPackages`, with every shipped package installed, so an icon
 * Curio does not bundle is checked as the palette gets it.
 */

// vega and vega-lite ship ESM that Jest's default transform skips; this suite
// never reaches the Vega compile path (same stubbing as packagesClient.test.ts).
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

jest.mock('../../utils/authApi', () => ({
  getToken: () => 'test-token',
}));

const mockListInstalled = jest.fn();
jest.mock('../../services/packages/packagesApi', () => ({
  packagesApi: { listInstalled: (...a: unknown[]) => mockListInstalled(...a) },
}));

import fs from 'fs';
import path from 'path';
import * as solid from '@fortawesome/free-solid-svg-icons';
import * as brands from '@fortawesome/free-brands-svg-icons';
// The module the registry loads the calculator from: curio.builtin@1 does not
// name it, so Curio does not bundle it.
import { faCalculator } from '@fortawesome/free-solid-svg-icons/faCalculator';
import '../../registry/builtinBehaviors';
import { resolveIconRef } from '../../registry/iconRegistry';
import { loadInstalledPackages } from '../../registry/packagesClient';
import { getAllNodeTypes } from '../../registry/nodeRegistry';

const PACKAGES = path.resolve(__dirname, '../../../../../../packages');

interface ManifestTemplate {
  id: string;
  label: string;
  category: string;
  iconRef?: string;
}

interface Manifest {
  id: string;
  name: string;
  publisher: string;
  version: string;
  templates?: ManifestTemplate[];
}

function iconRefs(value: unknown, into: Set<string>): Set<string> {
  if (Array.isArray(value)) value.forEach((v) => iconRefs(v, into));
  else if (value && typeof value === 'object') {
    for (const [key, v] of Object.entries(value)) {
      if (key === 'iconRef' && typeof v === 'string') into.add(v);
      else iconRefs(v, into);
    }
  }
  return into;
}

const manifests = fs
  .readdirSync(PACKAGES)
  .filter((dir) => fs.existsSync(path.join(PACKAGES, dir, 'manifest.json')))
  .map((dir): [string, Manifest] => [
    dir,
    JSON.parse(fs.readFileSync(path.join(PACKAGES, dir, 'manifest.json'), 'utf8')),
  ]);

const refs = manifests.flatMap(([dir, manifest]) =>
  [...iconRefs(manifest, new Set())].map((ref): [string, string] => [dir, ref]),
);

const majorOf = (dir: string) => Number(dir.slice(dir.lastIndexOf('@') + 1));

/** Each shipped template that names an icon: `[dir, descriptor id, iconRef]`. */
const tiles = manifests.flatMap(([dir, manifest]) =>
  (manifest.templates ?? [])
    .filter((t) => typeof t.iconRef === 'string')
    .map((t): [string, string, string] => [dir, `${manifest.id}/${t.id}@${majorOf(dir)}`, t.iconRef as string]),
);

/** The icons Curio bundles: those curio.builtin@1 names, and the cube. */
const bundled = new Set([
  ...iconRefs(manifests.find(([dir]) => dir === 'curio.builtin@1')?.[1], new Set()),
  'fa-solid:cube',
]);

const PACKS: Record<string, { index: object; folder: string }> = {
  'fa-solid': { index: solid, folder: '@fortawesome/free-solid-svg-icons' },
  'fa-brands': { index: brands, folder: '@fortawesome/free-brands-svg-icons' },
};

/** `map-location-dot` -> `faMapLocationDot`, the name Font Awesome exports it under. */
function exportName(name: string): string {
  return `fa${name
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('')}`;
}

/**
 * The Font Awesome object `ref` names: the pack's own export for an icon Curio
 * bundles, and the export of the icon's module, which the registry loads, for
 * any other.
 */
async function namedIcon(ref: string): Promise<unknown> {
  const [pack, name] = ref.split(':');
  const exported = exportName(name);
  if (bundled.has(ref)) return (PACKS[pack].index as Record<string, unknown>)[exported];
  const loaded = await import(`${PACKS[pack].folder}/${exported}`);
  return loaded[exported];
}

/** What `GET /api/packages` answers for one shipped package. */
function installed(dir: string, manifest: Manifest) {
  const major = majorOf(dir);
  return {
    packageId: manifest.id,
    major,
    version: manifest.version,
    name: manifest.name,
    publisher: manifest.publisher,
    description: '',
    license: null,
    permissions: [],
    lineage: null,
    templates: (manifest.templates ?? []).map((t) => ({
      id: `${manifest.id}/${t.id}@${major}`,
      templateId: t.id,
      label: t.label,
      category: t.category,
      engine: 'python' as const,
      description: '',
      icon: null,
      iconRef: t.iconRef ?? null,
      behavior: null,
      paletteOrder: null,
      editor: 'code' as const,
      hasCode: true,
      hasWidgets: false,
      hasGrammar: false,
      grammarId: null,
      badge: null,
      inputPorts: [],
      outputPorts: [],
      source: null,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
    })),
  };
}

describe('shipped package icons', () => {
  beforeAll(async () => {
    mockListInstalled.mockResolvedValue({
      packages: manifests.map(([dir, manifest]) => installed(dir, manifest)),
    });
    await loadInstalledPackages();
  });

  it('finds the shipped packages', () => {
    expect(refs.some(([dir]) => dir === 'curio.media@1')).toBe(true);
    expect(tiles.some(([dir]) => dir === 'scout.rasters@1')).toBe(true);
    expect(bundled.size).toBeGreaterThan(1);
  });

  it.each(refs)('%s names an icon Curio draws: %s', async (_dir, ref) => {
    const named = await namedIcon(ref);
    expect(named).toBeDefined();
    expect(resolveIconRef(ref)).toBe(named);
  });

  it.each(tiles)('%s: the palette tile of %s draws %s', async (_dir, id, ref) => {
    const descriptor = getAllNodeTypes().find((d) => d.id === id);
    expect(descriptor).toBeDefined();
    expect(descriptor?.icon).toBe(await namedIcon(ref));
  });

  it("draws SCOUT Rasters' Raster Calculator with the calculator", () => {
    const descriptor = getAllNodeTypes().find((d) => d.id === 'scout.rasters/raster-calculator@1');
    expect(descriptor?.icon).toBe(faCalculator);
  });
});
