/**
 * The behaviors Curio's bundle registers (`registry/builtinBehaviors.ts`) are
 * the ones `curio.builtin@1`'s templates name, no more and no fewer. A
 * package's node takes one of them, most often `code` with the starter the
 * package ships as the template's `source`, or a behavior the package ships
 * itself (`behaviorScript`): core registers no behavior for one package.
 */
// The built-in behaviors pull in vega and vega-lite, whose ESM Jest's default
// transform skips; this suite never compiles a chart.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import * as fs from 'fs';
import * as path from 'path';
import { getBehavior } from '../../registry/behaviorRegistry';
import '../../registry/builtinBehaviors';

const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
const BUILTIN_BEHAVIORS = path.resolve(__dirname, '../../registry/builtinBehaviors.ts');

/** The keys `builtinBehaviors.ts` registers, in its order. */
function registeredKeys(): string[] {
  const source = fs.readFileSync(BUILTIN_BEHAVIORS, 'utf-8');
  const keys = [...source.matchAll(/registerBehavior\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1]);
  // Every registration names its key as a literal the scan reads.
  expect(keys).toHaveLength((source.match(/registerBehavior\(/g) ?? []).length);
  return keys;
}

/** The behavior keys `curio.builtin@1`'s templates name. */
function builtinTemplateBehaviors(): string[] {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(REPO_ROOT, 'packages', 'curio.builtin@1', 'manifest.json'), 'utf-8'),
  );
  return manifest.templates
    .map((template: { behavior?: string | null }) => template.behavior)
    .filter((key: string | null | undefined): key is string => typeof key === 'string' && key.length > 0);
}

describe('the behaviors Curio registers', () => {
  test('are read whole from builtinBehaviors.ts, each one registered', () => {
    const keys = registeredKeys();
    expect(keys).toContain('code');
    expect(new Set(keys).size).toBe(keys.length);
    for (const key of keys) expect(getBehavior(key)).toBeDefined();
  });

  test('are exactly the ones curio.builtin@1 templates name', () => {
    const named = new Set(builtinTemplateBehaviors());
    expect(named.has('code')).toBe(true);
    expect(registeredKeys().filter((key) => !named.has(key))).toEqual([]);
    expect([...named].filter((key) => !registeredKeys().includes(key))).toEqual([]);
  });
});
