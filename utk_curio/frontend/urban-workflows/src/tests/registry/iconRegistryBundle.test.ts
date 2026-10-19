/**
 * Curio bundles only the icons curio.builtin@1's templates name, and the cube
 * an unknown name falls back to. Every other package's icons load on demand,
 * so `iconRegistry.ts` names no other package: a new package never needs an
 * edit there to show its icon.
 */

import fs from 'fs';
import path from 'path';
import { faCube } from '@fortawesome/free-solid-svg-icons';
import { resolveIconRef } from '../../registry/iconRegistry';

const PACKAGES = path.resolve(__dirname, '../../../../../../packages');
const ICON_REGISTRY = path.resolve(__dirname, '../../registry/iconRegistry.ts');

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
  .map((dir): [string, { id: string }] => [
    dir,
    JSON.parse(fs.readFileSync(path.join(PACKAGES, dir, 'manifest.json'), 'utf8')),
  ]);

const BUILTIN_DIR = 'curio.builtin@1';
const builtinManifest = manifests.find(([dir]) => dir === BUILTIN_DIR)?.[1];
const bundled = new Set([...iconRefs(builtinManifest, new Set()), 'fa-solid:cube']);
const others = [
  ...new Set(
    manifests
      .filter(([dir]) => dir !== BUILTIN_DIR)
      .flatMap(([, manifest]) => [...iconRefs(manifest, new Set())])
      .filter((ref) => !bundled.has(ref)),
  ),
];

/** `fa-solid:map-location-dot` -> `solid:faMapLocationDot`, as the file imports it. */
function importedAs(ref: string): string {
  const [pack, name] = ref.split(':');
  const moduleName = `fa${name
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('')}`;
  return `${pack.replace(/^fa-/, '')}:${moduleName}`;
}

describe('the icons Curio bundles', () => {
  const source = fs.readFileSync(ICON_REGISTRY, 'utf8');

  it('reads curio.builtin@1 and the other shipped packages', () => {
    expect(builtinManifest).toBeDefined();
    expect(bundled.size).toBeGreaterThan(1);
    expect(others.length).toBeGreaterThan(0);
  });

  it('are the icons curio.builtin@1 names, and the cube', () => {
    const imported = [
      ...source.matchAll(/import\s*\{([^}]*)\}\s*from\s*'@fortawesome\/free-(solid|brands)-svg-icons'/g),
    ].flatMap(([, names, pack]) =>
      names
        .split(',')
        .map((name) => name.trim())
        .filter(Boolean)
        .map((name) => `${pack}:${name}`),
    );
    expect(imported.sort()).toEqual([...bundled].map(importedAs).sort());
  });

  it('are registered when the registry loads, before any package does', () => {
    for (const ref of bundled) {
      const [pack, name] = ref.split(':');
      expect(`${ref} ${resolveIconRef(ref).prefix}:${resolveIconRef(ref).iconName}`).toBe(
        `${ref} ${pack === 'fa-brands' ? 'fab' : 'fas'}:${name}`,
      );
    }
  });

  it("leave out every other package's icons, which load on demand", () => {
    expect(others.filter((ref) => resolveIconRef(ref) !== faCube)).toEqual([]);
  });

  it('come from a file that names no package but curio.builtin', () => {
    const ids = manifests.map(([, manifest]) => manifest.id).filter((id) => id !== 'curio.builtin');
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.filter((id) => source.includes(id))).toEqual([]);
    // Nor any package coordinate, `<id>@<major>`, a shipped package or not.
    const coordinates = [...source.matchAll(/\b[a-z0-9-]+(?:\.[a-z0-9-]+)+@\d+/g)].map(([found]) => found);
    expect(coordinates.filter((found) => found !== BUILTIN_DIR)).toEqual([]);
  });
});
