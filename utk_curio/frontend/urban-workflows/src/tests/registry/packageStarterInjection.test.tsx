/**
 * Regression guard: a package template that ships a `source` starter must get
 * that code injected into a freshly-dropped node's editor — even when its
 * manifest names a behavior key that resolves to a registered built-in hook.
 *
 * Every `curio.weather@1` / `ai.utk.uhvi@1` template declares
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
// The cell the backend writes for a segmentation model package's template
// without a `source` (application/starters.py), named for the template's id.
const DEFAULT_CELL = 'model = curio_load_model("model.example.tiny")\nclasses = None\n\nreturn curio_segment(input_0, model, classes)\n';

jest.mock('../../providers/StarterProvider', () => ({
  useStarterContext: () => ({
    getStarters: (type: string) => {
      if (type === 'curio.weather/mrt-load@1') {
        return [{ id: 's1', type, name: 'mrt-load', description: '', accessLevel: 'ANY', code: STARTER_CODE, custom: false }];
      }
      if (type === 'model.example.tiny/image-segmentation@1') {
        return [{ id: 's2', type, name: 'image-segmentation', description: '', accessLevel: 'ANY', code: DEFAULT_CELL, custom: false }];
      }
      if (type === 'curio.scout/raster-calculator@1') return mockCalculatorStarters(type);
      if (type === 'curio.scout/dots-with-a-range@1') return mockChartStarters(type);
      return [];
    },
  }),
}));

import * as fs from 'fs';
import * as path from 'path';
import { faCalculator } from '@fortawesome/free-solid-svg-icons/faCalculator';
import '../../registry/builtinBehaviors'; // side-effect: registers 'code', 'vega', …
import { loadIconRefs } from '../../registry/iconRegistry';
import { BUILTIN_PACKAGE_ID, registerPackageTemplates } from '../../registry/packagesClient';
import { clearPackageNodes } from '../../registry/nodeRegistry';
import { getBehavior } from '../../registry/behaviorRegistry';
import { packageStarterCode, usePackageNodeBehavior } from '../../adapters/node/packageNodeBehavior';
import { useStarterContext } from '../../providers/StarterProvider';
import { behaviorDataView } from '../../utils/behaviorDataView';
import { VEGA_LITE, resolveReferences } from '../../utils/references/codeReferences';
import { normalizeWidgets } from '../../utils/widgets/widgetModel';
import type { NodeBehaviorData, UseNodeStateReturn } from '../../registry/types';

const REPO_ROOT = path.resolve(__dirname, '../../../../../..');
/** Scout, as the repository ships it. */
const SCOUT = path.join(REPO_ROOT, 'packages', 'curio.scout@1');

/** The starter Scout ships for its Raster Calculator. */
function readCalculatorStarter(): string {
  return fs.readFileSync(path.join(SCOUT, 'sources', 'raster-calculator.py'), 'utf-8');
}

/** What the starters feed (`application/starters.py`) lists for the Raster
 *  Calculator: its package's `sources/raster-calculator.py`, under that file's
 *  name. Read when asked, so only the cases that drop it read it. */
function mockCalculatorStarters(type: string) {
  return [{
    id: 's3', type, name: 'raster-calculator', description: '', accessLevel: 'ANY',
    code: readCalculatorStarter(), custom: false,
  }];
}

/** The spec Scout ships for its Dots with a range. */
function readChartStarter(): string {
  return fs.readFileSync(path.join(SCOUT, 'sources', 'dots-with-a-range.vl.json'), 'utf-8');
}

/** What the starters feed lists for Dots with a range: its package's
 *  `sources/dots-with-a-range.vl.json`, under that file's name. */
function mockChartStarters(type: string) {
  return [{
    id: 's4', type, name: 'dots-with-a-range.vl', description: '', accessLevel: 'ANY',
    code: readChartStarter(), custom: false,
  }];
}

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
};

const FIXTURE_PACK = {
  packageId: 'curio.weather',
  major: 1,
  version: '1.0.0',
  name: 'Weather Analysis',
  publisher: 'Curio',
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
  kind?: 'node' | 'model';
  templates: Array<
    Omit<(typeof FIXTURE_PACK)["templates"][number], "source"> & { source: string | null }
  >;
};

/** A segmentation model package whose one template ships no `source`, as
 *  DDRNet23-Slim's and every Discovery download's does. */
const MODEL_PACK: StarterPack = {
  ...FIXTURE_PACK,
  packageId: 'model.example.tiny',
  name: 'Tiny model',
  kind: 'model',
  templates: [{
    ...TEMPLATE,
    id: 'model.example.tiny/image-segmentation@1',
    templateId: 'image-segmentation',
    label: 'Image Segmentation',
    category: 'computation',
    source: null,
  }],
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

describe('a model package\'s template without a source', () => {
  beforeEach(() => clearPackageNodes());
  const { getStarters } = useStarterContext();

  test('opens with the default cell the backend writes for its model on a fresh drop', () => {
    expect(runBehavior(MODEL_PACK, undefined)).toContain(DEFAULT_CELL);
    const [desc] = registerPackageTemplates([MODEL_PACK]);
    expect(packageStarterCode(desc, getStarters)).toBe(DEFAULT_CELL);
  });

  test('a restored node keeps the code it was saved with', () => {
    expect(runBehavior(MODEL_PACK, 'user code')).not.toContain(DEFAULT_CELL);
  });

  test('the same template in a node package opens empty, as any template without a source does', () => {
    const pack: StarterPack = { ...MODEL_PACK, kind: 'node' };
    expect(runBehavior(pack, undefined)).not.toContain(DEFAULT_CELL);
    const [desc] = registerPackageTemplates([pack]);
    expect(packageStarterCode(desc, getStarters)).toBeUndefined();
  });
});

/** Scout with its Raster Calculator's template, read from its manifest. */
function calculatorPack(): StarterPack {
  const manifest = JSON.parse(fs.readFileSync(path.join(SCOUT, 'manifest.json'), 'utf-8'));
  const template = manifest.templates.find((t: { id: string }) => t.id === 'raster-calculator');
  return {
    packageId: manifest.id,
    major: 1,
    version: manifest.version,
    name: manifest.name,
    publisher: manifest.publisher,
    description: manifest.description,
    license: manifest.license,
    permissions: [],
    lineage: null,
    templates: [{
      id: `${manifest.id}/raster-calculator@1`,
      templateId: template.id,
      label: template.label,
      category: template.category,
      engine: template.engine,
      description: template.description,
      icon: null,
      iconRef: template.iconRef,
      behavior: template.behavior,
      paletteOrder: template.paletteOrder,
      editor: template.editor,
      hasCode: template.hasCode,
      hasWidgets: template.hasWidgets,
      hasGrammar: template.hasGrammar,
      grammarId: null,
      badge: null,
      inputPorts: template.inputPorts,
      outputPorts: template.outputPorts,
      source: template.source ?? null,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
    }],
  };
}

describe('Scout\'s Raster Calculator, as the repository ships it', () => {
  beforeEach(() => clearPackageNodes());
  const { getStarters } = useStarterContext();

  test('a fresh drop opens with the starter its package ships, from the starters feed', () => {
    const starter = readCalculatorStarter();
    expect(runBehavior(calculatorPack(), undefined)).toContain(starter);
    const [desc] = registerPackageTemplates([calculatorPack()]);
    expect(packageStarterCode(desc, getStarters)).toBe(starter);
  });

  test('the starter returns a subtraction and lists the other operations, statistics among them', () => {
    const starter = readCalculatorStarter();
    expect(starter.endsWith('\nreturn raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)\n')).toBe(true);
    expect(starter).toContain('\n#   return raster_statistics(input_0, mask=input_1)\n');
    expect(starter).toContain('as a table of one row');
    expect(starter).toContain('where=lambda value: value < 1.08');
    expect(starter).toContain('mask_values=[0]');
  });

  test('a restored node keeps the code a dataflow carries, and one saved with no code opens empty', () => {
    const starter = readCalculatorStarter();
    expect(runBehavior(calculatorPack(), 'return raster_calculate("add", [input_0, input_1], output_file=curio_output_file)')).not.toContain(starter);
    expect(runBehavior(calculatorPack(), '').filter((code) => code !== undefined)).toEqual([]);
  });

  test('is a package node with its icon and the PACKAGE pill, and core holds no node or behavior of its own', async () => {
    const read = (dir: string) =>
      JSON.parse(fs.readFileSync(path.join(REPO_ROOT, 'packages', dir, 'manifest.json'), 'utf-8'));
    const templates = read('curio.scout@1').templates;
    const template = templates.find((t: { id: string }) => t.id === 'raster-calculator');
    expect([template.behavior, template.source]).toEqual(['code', 'sources/raster-calculator.py']);
    expect(read(`${BUILTIN_PACKAGE_ID}@1`).templates.map((t: { id: string }) => t.id)).not.toContain('raster-calculator');
    // Statistics are one of its operations, with no node or behavior of their own.
    expect(templates.map((t: { id: string }) => t.id).filter((id: string) => id.includes('statistics'))).toEqual([]);
    expect(getBehavior('raster-calculator')).toBeUndefined();
    expect(getBehavior('raster-statistics')).toBeUndefined();

    // Its icon is loaded on demand, as the app loads it before building descriptors.
    await loadIconRefs([template.iconRef]);
    const [descriptor] = registerPackageTemplates([calculatorPack()]);
    expect(descriptor.package?.packageId).toBe('curio.scout');
    expect(descriptor.package?.name).toBe('Scout');
    expect(descriptor.package?.source).toBe('sources/raster-calculator.py');
    expect(descriptor.icon).toBe(faCalculator);
    expect(descriptor.badge).toBe('PACKAGE');
    expect(descriptor.category).toBe('computation');
  });
});

type ShippedPack = Parameters<typeof registerPackageTemplates>[0][number];

/** Scout with its Dots with a range's template, read from its manifest. */
function chartPack(): ShippedPack {
  const manifest = JSON.parse(fs.readFileSync(path.join(SCOUT, 'manifest.json'), 'utf-8'));
  const template = manifest.templates.find((t: { id: string }) => t.id === 'dots-with-a-range');
  return {
    packageId: manifest.id,
    major: 1,
    version: manifest.version,
    name: manifest.name,
    publisher: manifest.publisher,
    description: manifest.description,
    license: manifest.license,
    permissions: [],
    lineage: null,
    templates: [{
      id: `${manifest.id}/dots-with-a-range@1`,
      templateId: template.id,
      label: template.label,
      category: template.category,
      engine: template.engine,
      description: template.description,
      icon: null,
      iconRef: template.iconRef,
      behavior: template.behavior,
      paletteOrder: template.paletteOrder,
      editor: template.editor,
      hasCode: template.hasCode,
      hasWidgets: template.hasWidgets,
      hasGrammar: template.hasGrammar,
      grammarId: template.grammarId,
      badge: template.badge,
      inputPorts: template.inputPorts,
      outputPorts: template.outputPorts,
      source: template.source,
      widgets: template.widgets,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
    }],
  };
}

/** The starter injection on a node of Dots with a range with *data*: every
 *  spec it offers the editor, and the node's data after. Run alone, as the
 *  chart's own behavior (`vegaBehavior`) draws on a canvas this suite does not
 *  hold. */
function dropChart(data: Record<string, unknown>) {
  const [desc] = registerPackageTemplates([chartPack()]);
  const node: Record<string, unknown> = { nodeType: desc.id, ...data };
  const nodeState = { code: typeof data.code === 'string' ? data.code : '' } as unknown as UseNodeStateReturn;
  const offered: Array<string | undefined> = [];
  renderHook(() => {
    const result = usePackageNodeBehavior(node as unknown as NodeBehaviorData, nodeState);
    offered.push(result.defaultValueOverride);
    return result;
  });
  return { offered, node };
}

describe('Scout\'s charts, as the repository ships them (the plan answering komar41\'s review, step 6.2)', () => {
  beforeEach(() => clearPackageNodes());

  test('a fresh drop opens with its template\'s spec, which reads its inputs by the dataset\'s chip, and its widgets', () => {
    const { offered, node } = dropChart({});
    const starter = readChartStarter();
    expect(offered).toContain(starter);
    // Read with each chip that stands on its own (its scenarios' scale) as null.
    expect(JSON.parse(starter.replace(/(?<=[:[,]\s*)\[!!.*?!!\]/g, 'null')).data).toEqual({ name: '[!! inputs !!]' });
    // Wired, it reads that dataset: the chip as its editor resolves it before a run.
    const box = { scenario: 's-base', name: 'Baseline', color: '#2a9d8f', rank: 0 };
    const wired = resolveReferences(
      starter, { widgets: normalizeWidgets(node.widgets), inputs: [{ slot: 0, scenario: box }], shared: [] }, 'json', VEGA_LITE,
    );
    expect(wired.problems).toEqual([]);
    expect(JSON.parse(wired.code).data).toEqual({ name: 'inputs' });
    expect(node.widgets).toEqual(chartPack().templates[0].widgets);
  });

  test('a node saved with its spec edited reloads with the edit, and with its widgets as saved', () => {
    const edited = readChartStarter().replace('"size": 60', '"size": 140');
    expect(edited).not.toBe(readChartStarter());
    const widgets = [{ name: 'category', type: 'text', label: 'Category column', default: 'category', value: 'park' }];
    const { offered, node } = dropChart({ code: edited, widgets });
    expect(offered.filter((code) => code !== undefined)).toEqual([]);
    expect(node.code).toBe(edited);
    expect(node.widgets).toBe(widgets);
  });
});

describe('a template\'s widgets on a fresh drop (#662)', () => {
  beforeEach(() => clearPackageNodes());

  const WIDGETS = [{ name: 'season', type: 'text', label: 'Season', default: 'winter' }];

  /** Runs the behavior the way UniversalNode does, through `behaviorDataView`,
   *  and returns the node's own data afterwards. */
  function dropThroughTheView(code?: string): Record<string, unknown> {
    const pack = { ...FIXTURE_PACK, templates: [{ ...TEMPLATE, hasWidgets: true, widgets: WIDGETS }] };
    const [desc] = registerPackageTemplates([pack]);
    const data: Record<string, unknown> = { nodeType: desc.id, ...(code !== undefined ? { code } : {}) };
    const nodeState = { code: code ?? '' } as unknown as UseNodeStateReturn;
    renderHook(() => desc.adapter.useNodeBehavior(
      behaviorDataView(data) as unknown as NodeBehaviorData, nodeState,
    ));
    return data;
  }

  test('are seeded on the node\'s data beside its starter', () => {
    const data = dropThroughTheView();
    expect(data.widgets).toEqual(WIDGETS);
    // The view never writes its `content` alias to the node.
    expect('content' in data).toBe(false);
  });

  test('a restored node keeps what it was saved with', () => {
    expect(dropThroughTheView('user code').widgets).toBeUndefined();
  });
});

describe('packageStarterCode', () => {
  beforeEach(() => clearPackageNodes());
  // The mocked context is a plain function, so it can be read outside React.
  const { getStarters } = useStarterContext();

  test('is the code a fresh node of the template opens with', () => {
    const [desc] = registerPackageTemplates([FIXTURE_PACK]);
    expect(packageStarterCode(desc, getStarters)).toBe(STARTER_CODE);
    expect(runBehavior(FIXTURE_PACK, undefined)).toContain(packageStarterCode(desc, getStarters));
  });

  test('a template without a source has none', () => {
    const [desc] = registerPackageTemplates([{ ...FIXTURE_PACK, templates: [{ ...TEMPLATE, source: null }] }]);
    expect(packageStarterCode(desc, getStarters)).toBeUndefined();
  });

  test('nor does a template the feed has not sent yet, or no template', () => {
    const [desc] = registerPackageTemplates([{
      ...FIXTURE_PACK,
      packageId: 'curio.elsewhere',
      templates: [{ ...TEMPLATE, id: 'curio.elsewhere/mrt-load@1' }],
    }]);
    expect(packageStarterCode(desc, getStarters)).toBeUndefined();
    expect(packageStarterCode(undefined, getStarters)).toBeUndefined();
  });
});
