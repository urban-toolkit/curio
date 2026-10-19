/**
 * Every `iconRef` a shipped package names draws that icon, so no shipped node
 * falls back to the generic cube. The suite builds the palette the way the app
 * does, through `loadInstalledPackages`, with every shipped package installed,
 * so an icon Curio does not bundle is checked as the palette gets it.
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
import { faCube } from '@fortawesome/free-solid-svg-icons';
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

const PREFIXES: Record<string, string> = { 'fa-solid': 'fas', 'fa-brands': 'fab' };

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
  });

  it.each(refs)('%s names an icon Curio draws: %s', (_dir, ref) => {
    const icon = resolveIconRef(ref);
    if (ref !== 'fa-solid:cube') expect(icon).not.toBe(faCube);
    // The icon the ref names: its pack, and its name or one of its aliases.
    const [pack, name] = ref.split(':');
    expect(icon.prefix).toBe(PREFIXES[pack]);
    expect([icon.iconName, ...(icon.icon[2] as unknown[])]).toContain(name);
  });

  it.each(tiles)('%s: the palette tile of %s draws %s', (_dir, id, ref) => {
    const descriptor = getAllNodeTypes().find((d) => d.id === id);
    expect(descriptor).toBeDefined();
    expect(descriptor?.icon).toBe(resolveIconRef(ref));
    if (ref !== 'fa-solid:cube') expect(descriptor?.icon).not.toBe(faCube);
  });
});
