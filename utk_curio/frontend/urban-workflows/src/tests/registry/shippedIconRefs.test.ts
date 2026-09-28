import fs from 'fs';
import path from 'path';
import { faCube } from '@fortawesome/free-solid-svg-icons';
import { resolveIconRef } from '../../registry/iconRegistry';

/**
 * Every `iconRef` a shipped package names is registered, so no shipped node
 * falls back to the generic cube.
 */

const PACKAGES = path.resolve(__dirname, '../../../../../../packages');

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

const refs = fs
  .readdirSync(PACKAGES)
  .filter((dir) => fs.existsSync(path.join(PACKAGES, dir, 'manifest.json')))
  .flatMap((dir) => {
    const manifest = JSON.parse(fs.readFileSync(path.join(PACKAGES, dir, 'manifest.json'), 'utf8'));
    return [...iconRefs(manifest, new Set())].map((ref): [string, string] => [dir, ref]);
  });

describe('shipped package icons', () => {
  it('finds the shipped packages', () => {
    expect(refs.some(([dir]) => dir === 'curio.media@1')).toBe(true);
  });

  it.each(refs)('%s names a registered icon: %s', (_dir, ref) => {
    const icon = resolveIconRef(ref);
    if (ref !== 'fa-solid:cube') expect(icon).not.toBe(faCube);
  });
});
