/**
 * The canvas decides what a node is by what its template declares, as the
 * backend does: `registry/declaredNodes.cases.json` holds the cases, and
 * `test_projects/test_declared_node_cases.py` runs the same cases through the
 * backend's rules.
 *
 * The case packages are registered as the app registers installed packages
 * (`registerPackageTemplates`), beside `curio.builtin@1` read from
 * `packages/`. The rules are required inside the tests, so a checkout without
 * one fails each test on its own.
 */
import fs from 'fs';
import path from 'path';

// vega and vega-lite ship ESM that Jest's default transform skips; the
// registry path here never compiles a chart.
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import cases from '../../registry/declaredNodes.cases.json';
import { registerPackageTemplates } from '../../registry/packagesClient';
import { clearPackageNodes, tryGetNodeDescriptor } from '../../registry/nodeRegistry';

const PACKAGES = path.resolve(__dirname, '../../../../../../packages');

type ManifestTemplate = {
  id: string;
  label?: string;
  category: string;
  engine?: string;
  editor: string;
  behavior?: string;
  grammarId?: string;
  hasCode?: boolean;
  hasGrammar?: boolean;
  hasWidgets?: boolean;
  inputPorts: Array<{ types: string[]; cardinality?: string }>;
  outputPorts: Array<{ types: string[]; cardinality?: string }>;
};

type Manifest = {
  id: string;
  name?: string;
  version?: string;
  publisher?: string;
  compatibility?: { major?: number };
  templates: ManifestTemplate[];
};

/** A manifest as `GET /api/packages` lists it, the shape the registry reads. */
function listed(manifest: Manifest) {
  const major = manifest.compatibility?.major ?? 1;
  return {
    packageId: manifest.id,
    major,
    version: manifest.version ?? '1.0.0',
    name: manifest.name ?? manifest.id,
    publisher: manifest.publisher ?? '',
    description: '',
    license: null,
    permissions: [],
    lineage: null,
    templates: manifest.templates.map((t) => ({
      id: `${manifest.id}/${t.id}@${major}`,
      templateId: t.id,
      label: t.label ?? t.id,
      category: t.category,
      engine: (t.engine === 'javascript' ? 'javascript' : 'python') as 'python' | 'javascript',
      description: '',
      icon: null,
      iconRef: null,
      behavior: t.behavior ?? null,
      paletteOrder: null,
      editor: t.editor as 'code' | 'widgets' | 'grammar' | 'none',
      hasCode: Boolean(t.hasCode),
      hasWidgets: Boolean(t.hasWidgets),
      hasGrammar: Boolean(t.hasGrammar),
      grammarId: t.grammarId ?? null,
      badge: null,
      inputPorts: t.inputPorts,
      outputPorts: t.outputPorts,
      source: null,
      bidirectional: false,
      containerStyle: null,
      hasProvenance: null,
    })),
  };
}

type Case = {
  name: string;
  type: string;
  content?: string;
  passThrough: boolean;
  selfDrawn: boolean;
  nonProducing: boolean;
  loadsData: boolean;
};

const BUILTIN: Manifest = JSON.parse(
  fs.readFileSync(path.join(PACKAGES, 'curio.builtin@1', 'manifest.json'), 'utf8'),
);
const PACKAGES_OF_THE_CASES = cases.packages as unknown as Manifest[];
const CASES = cases.cases as unknown as Case[];

/** The behavior the registered template of *nodeType* declares. */
function behaviorOf(nodeType: string): string | undefined {
  return (tryGetNodeDescriptor(nodeType) as unknown as { behavior?: string } | undefined)?.behavior;
}

beforeAll(() => {
  clearPackageNodes();
  registerPackageTemplates([listed(BUILTIN), ...PACKAGES_OF_THE_CASES.map(listed)]);
});

afterAll(() => clearPackageNodes());

test('a registered template keeps the behavior its manifest declares', () => {
  expect(behaviorOf('curio.builtin/data-pool@1')).toBe('data-pool');
  expect(behaviorOf('acme.tools/pool@1')).toBe('data-pool');
  expect(behaviorOf('acme.tools/data-pool@1')).toBe('code');
  expect(behaviorOf('acme.tools/bare@1')).toBeUndefined();
});

describe('the canvas rules that read what a template declares', () => {
  test('a dataset dropped on a node applies to it as to Data Loading when its template loads data', () => {
    const { canApplyDatasetToNode } = require('../../services/datasetCatalog/datasetApplication');
    // A package's own loader: the data category with no input port.
    expect(canApplyDatasetToNode({ nodeType: 'acme.tools/fetch-parcels@1' })).toBe(true);
    // Named like Data Loading, but a node with an input, and no code to apply it to.
    expect(canApplyDatasetToNode({ nodeType: 'acme.tools/data-loading@1' })).toBe(false);
    expect(canApplyDatasetToNode({ nodeType: 'curio.builtin/data-loading@1' })).toBe(true);
  });

  test("the nodes after a package's loader are the dataset's consumers, as after Data Loading", () => {
    const { selectDatasetDownstreamUsage } = require('../../services/datasetLineage/datasetLineageResolver');
    const consumers = (loaderType: string) =>
      selectDatasetDownstreamUsage({
        datasetId: 'acme.parcels',
        nodes: [
          { data: { nodeId: 'loader', nodeType: loaderType, datasetRefs: ['acme.parcels'] } },
          { data: { nodeId: 'after', nodeType: 'curio.builtin/computation-analysis@1' } },
        ],
        edges: [{ source: 'loader', target: 'after' }],
      }).consumingNodes.map((n: { nodeId: string }) => n.nodeId);

    expect(consumers('acme.tools/fetch-parcels@1')).toEqual(['after']);
    expect(consumers('acme.tools/data-loading@1')).toEqual(['loader']);
    expect(consumers('curio.builtin/data-loading@1')).toEqual(['after']);
  });

  test("a pinned node is its own dashboard source when its template declares Compare Scenarios' behavior", () => {
    const { dashboardSourceNodeIds } = require('../../utils/dashboardLayout');
    const nodes = [
      { id: 'py', type: 'curio.builtin/computation-analysis@1', data: { nodeType: 'curio.builtin/computation-analysis@1' } },
      { id: 'mine', type: 'acme.tools/compare@1', data: { nodeType: 'acme.tools/compare@1', dashboardPinned: true } },
      { id: 'named', type: 'acme.tools/compare-scenarios@1', data: { nodeType: 'acme.tools/compare-scenarios@1', dashboardPinned: true } },
    ];
    const edges = [{ source: 'py', target: 'mine' }, { source: 'py', target: 'named' }];
    // `mine` draws its own output; `named` is only named so, and reads `py`.
    expect([...dashboardSourceNodeIds(nodes, edges)].sort()).toEqual(['mine', 'py']);
  });
});

describe.each(CASES)('$name', (c) => {
  test('the canvas decides it as the backend does', () => {
    const { isPassThroughNode, isSelfDrawnNode } = require('../../utils/dashboardLayout');
    const { isNonProducingNodeType } = require('../../utils/saveOutputDataset');
    const { loadsData } = require('../../registry/declaredNodes');

    const node = { id: 'n', type: c.type, data: { nodeId: 'n', nodeType: c.type, code: c.content ?? '' } };
    expect({
      passThrough: isPassThroughNode(node),
      selfDrawn: isSelfDrawnNode(node),
      nonProducing: isNonProducingNodeType(c.type),
      loadsData: loadsData(c.type),
    }).toEqual({
      passThrough: c.passThrough,
      selfDrawn: c.selfDrawn,
      nonProducing: c.nonProducing,
      loadsData: c.loadsData,
    });
  });
});
