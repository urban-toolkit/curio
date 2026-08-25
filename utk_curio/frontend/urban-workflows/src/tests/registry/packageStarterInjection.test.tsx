/**
 * Regression guard: a package template that ships a `source` starter must get
 * that code injected into a freshly-dropped node's editor — even when its
 * manifest names a behavior key that resolves to a registered built-in hook.
 *
 * Every `curio.weather@1` / `ai.urbanlab.uhvi@1` template declares
 * `behavior: "code"` next to `source: "sources/<x>.py"`. Resolving `"code"`
 * through the behavior registry yields the no-op `useCodeNodeBehavior`, which
 * used to win outright over the starter-injecting `usePackageNodeBehavior` —
 * so those nodes opened with an empty editor.
 */

import { renderHook } from '@testing-library/react';

// vega/vega-lite ship ESM Jest's default transform skips; this suite only
// exercises manifest → descriptor → behavior wiring.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

const STARTER_CODE = 'import rasterio\nds = rasterio.open("mrt.tif")\n';

jest.mock('../../providers/StarterProvider', () => ({
  useStarterContext: () => ({
    getStarters: (type: string) =>
      type === 'curio.weather/mrt-load@1'
        ? [{ id: 's1', type, name: 'mrt-load', description: '', accessLevel: 'ANY', code: STARTER_CODE, custom: false }]
        : [],
  }),
}));

import '../../registry/builtinBehaviors'; // side-effect: registers 'code', 'vega', …
import '../../registry/iconRegistry';
import { registerPackageTemplates } from '../../registry/packagesClient';
import { clearPackageNodes } from '../../registry/nodeRegistry';
import type { NodeBehaviorData, UseNodeStateReturn } from '../../registry/types';

const TEMPLATE = {
  id: 'curio.weather/mrt-load@1',
  templateId: 'mrt-load',
  label: 'Milan MRT Loader',
  category: 'data',
  engine: 'python' as const,
  description: '',
  icon: null,
  iconRef: null,
  behavior: 'code', // ← resolves to the built-in no-op hook
  paletteOrder: null,
  editor: 'code' as const,
  hasCode: true,
  hasWidgets: false,
  hasGrammar: false,
  grammarId: null,
  badge: null,
  inputPorts: [],
  outputPorts: [{ types: ['RASTER'], cardinality: '1' }],
  source: 'sources/mrt-load.py',
  bidirectional: false,
  containerStyle: null,
  hasProvenance: null,
  tutorialId: null,
};

const FIXTURE_PACK = {
  packageId: 'curio.weather',
  major: 1,
  version: '1.0.0',
  name: 'Weather Analysis',
  publisher: 'Urban Analytics Lab',
  description: '',
  license: 'MIT',
  permissions: [],
  lineage: null,
  templates: [TEMPLATE],
};

/**
 * Returns every `defaultValueOverride` the behavior emitted across renders.
 *
 * The override is deliberately transient: `usePackageNodeBehavior` clears it
 * one render after `CodeEditor` consumes it (so the user can clear the buffer
 * without it snapping back). Asserting on `result.current` alone would
 * therefore always see `undefined` — we record each render instead.
 */
/** The fixture, with `source` allowed to be null — which is exactly the case
 *  the "no source" test below exercises. */
type StarterPack = Omit<typeof FIXTURE_PACK, "templates"> & {
  templates: Array<
    Omit<(typeof FIXTURE_PACK)["templates"][number], "source"> & { source: string | null }
  >;
};

function runBehavior(pack: StarterPack, code: unknown): Array<string | undefined> {
  const [desc] = registerPackageTemplates([pack]);
  const data = { nodeType: desc.id, ...(code !== undefined ? { code } : {}) } as unknown as NodeBehaviorData;
  const nodeState = { code: typeof code === 'string' ? code : '' } as unknown as UseNodeStateReturn;
  const seen: Array<string | undefined> = [];
  renderHook(() => {
    const result = desc.adapter.useNodeBehavior(data, nodeState);
    seen.push(result.defaultValueOverride);
    return result;
  });
  return seen;
}

describe('package starter injection', () => {
  beforeEach(() => clearPackageNodes());

  test('behavior:"code" + source → starter code injected on a fresh drop', () => {
    expect(runBehavior(FIXTURE_PACK, undefined)).toContain(STARTER_CODE);
  });

  test('a restored node (data.code already set) is left untouched', () => {
    expect(runBehavior(FIXTURE_PACK, 'user code')).not.toContain(STARTER_CODE);
  });

  test('no source → nothing injected', () => {
    const pack = { ...FIXTURE_PACK, templates: [{ ...TEMPLATE, source: null }] };
    expect(runBehavior(pack, undefined)).not.toContain(STARTER_CODE);
  });
});
