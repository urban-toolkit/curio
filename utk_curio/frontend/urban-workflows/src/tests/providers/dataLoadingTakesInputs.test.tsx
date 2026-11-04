/**
 * A Data Loading node takes inputs: the canvas draws an input circle on it,
 * and an edge from a node that returns a value, such as the area several
 * loaders read, lands there, through the REAL FlowProvider (onConnect in
 * providers/flow/useConnect.ts, ConnectionValidator.ts). So do the readers of
 * a shared value in the Scout packages: an Accumulated Shadow node takes a
 * season on its second circle, and a Raster Calculator a region on its third.
 *
 * The templates are registered as the app registers them at boot: the shipped
 * manifests, as GET /api/packages lists them, through registerPackageTemplates
 * (registry/packagesClient.ts buildDescriptor). Harness as in
 * interactionEdgeRouting.test.tsx.
 */
import fs from 'fs';
import path from 'path';
import React from 'react';
import { render, act } from '@testing-library/react';
import { ReactFlow, ReactFlowProvider } from 'reactflow';
import type { Connection, Node } from 'reactflow';

// jsdom polyfills ReactFlow needs.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(global as any).ResizeObserver = ResizeObserverStub;
if (!(global as any).DOMMatrixReadOnly) {
  (global as any).DOMMatrixReadOnly = class { m22 = 1; constructor() {} };
}

// Mocks: replace the heavy and IO collaborators, keep reactflow REAL.
jest.mock('../../hook/useWorkflowOperations', () => ({
  useWorkflowOperations: () => ({
    markNodeExecuted: jest.fn(),
    markNodeStale: jest.fn(),
    markDirty: jest.fn(),
    recordOutputs: jest.fn().mockResolvedValue(undefined),
    beginPendingInstall: jest.fn(),
    endPendingInstall: jest.fn(),
    applyRemoveChanges: jest.fn(),
    allMinimized: false,
    setAllMinimized: jest.fn(),
    expandStatus: {},
    setExpandStatus: jest.fn(),
    updateDataNode: jest.fn(),
    updateDefaultCode: jest.fn(),
    workflowGoal: '',
    acceptSuggestion: jest.fn(),
  }),
}));

// onConnect says why it refuses an edge in a toast.
const mockShowToast = jest.fn();
jest.mock('../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock('../../providers/CollaborationProvider', () => ({
  useCollab: () => ({
    onRemote: jest.fn(),
  }),
}));

jest.mock('../../hook/useCode', () => ({
  pythonInterpreter: {},
  jsInterpreter: {},
}));

jest.mock('../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('vega', () => ({}), { virtual: true });
jest.mock('vega-lite', () => ({}), { virtual: true });

import FlowProvider, { useFlowContext } from '../../providers/FlowProvider';
import { CURIO_UNIVERSAL_NODE_TYPE } from '../../constants';
import { registerPackageTemplates } from '../../registry/packagesClient';
import { clearPackageNodes, tryGetNodeDescriptor } from '../../registry/nodeRegistry';

const LOADER = 'curio.builtin/data-loading@1';
const PYTHON = 'curio.builtin/computation-analysis@1';
const RASTERIZE = 'curio.scout/rasterize-buildings@1';
const CALCULATOR = 'curio.scout/raster-calculator@1';
const SHADOW = 'model.scout.deep-umbra/accumulated-shadow@1';

const PACKAGES_ROOT = path.resolve(__dirname, '../../../../../../packages');

/** A shipped package as GET /api/packages lists it (``package_payload`` in
 * packages/schemas/responses.py), read from its manifest in packages/. */
function listedPackage(dirName: string): any {
  const manifest = JSON.parse(fs.readFileSync(path.join(PACKAGES_ROOT, dirName, 'manifest.json'), 'utf8'));
  const major = manifest.compatibility.major;
  return {
    packageId: manifest.id,
    major,
    version: manifest.version,
    name: manifest.name,
    publisher: manifest.publisher,
    description: manifest.description,
    license: manifest.license ?? null,
    permissions: manifest.permissions ?? [],
    dirName,
    kind: manifest.kind ?? 'node',
    lineage: null,
    templates: manifest.templates.map((template: any) => ({
      id: `${manifest.id}/${template.id}@${major}`,
      templateId: template.id,
      label: template.label,
      category: template.category,
      engine: template.engine,
      description: template.description,
      icon: template.icon ?? null,
      iconRef: template.iconRef ?? null,
      behavior: template.behavior ?? null,
      paletteOrder: template.paletteOrder ?? null,
      editor: template.editor,
      hasCode: template.hasCode,
      hasWidgets: template.hasWidgets,
      hasGrammar: template.hasGrammar,
      grammarId: template.grammarId ?? null,
      badge: template.badge ?? null,
      inputPorts: template.inputPorts,
      outputPorts: template.outputPorts,
      source: template.source ?? null,
      widgets: template.widgets ?? null,
      bidirectional: template.bidirectional ?? false,
      containerStyle: template.containerStyle ?? null,
      hasProvenance: template.hasProvenance ?? null,
      backendHandler: template.backendHandler ?? null,
      loadsDataset: template.loadsDataset ?? false,
    })),
  };
}

beforeAll(() => {
  registerPackageTemplates([
    listedPackage('curio.builtin@1'),
    listedPackage('curio.scout@1'),
    listedPackage('model.scout.deep-umbra@1'),
  ]);
});

afterAll(() => {
  clearPackageNodes();
});

type FlowApi = ReturnType<typeof useFlowContext>;
let api: FlowApi;

const Bridge: React.FC = () => {
  const ctx = useFlowContext();
  api = ctx;
  return (
    <div style={{ width: 800, height: 600 }}>
      <ReactFlow nodes={ctx.nodes} edges={ctx.edges} onNodesChange={ctx.onNodesChange} onEdgesChange={ctx.onEdgesChange} />
    </div>
  );
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

async function renderFlow() {
  render(
    <ReactFlowProvider>
      <FlowProvider>
        <Bridge />
      </FlowProvider>
    </ReactFlowProvider>,
  );
  await flush();
}

/** A node as a palette drop builds one: the universal React Flow type and
 * the versioned template id. */
function makeNode(id: string, nodeType: string): Node {
  return {
    id,
    type: CURIO_UNIVERSAL_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { nodeId: id, nodeType, input: '', inputTypes: [] },
  } as Node;
}

async function addNodes(...nodes: Node[]) {
  await act(async () => {
    nodes.forEach((n) => api.addNode(n, undefined, false));
  });
  await flush();
}

/** Drop an edge from *source*'s output on *target*'s circle *handle*, as on
 * the canvas, where MainCanvas hands the connection to onConnect. */
async function draw(source: string, target: string, handle = 'in') {
  await act(async () => {
    api.onConnect({ source, target, sourceHandle: 'out', targetHandle: handle } as Connection);
  });
  await flush();
}

/** The edges on the canvas, as [source, target, circle]. */
const drawn = () => api.edges.map((e) => [e.source, e.target, e.targetHandle]);

afterEach(() => {
  jest.clearAllMocks();
});

describe('a Data Loading node takes inputs', () => {
  test('its template, as the app registers it, gives it an input circle that grows', () => {
    const loader = tryGetNodeDescriptor(LOADER as any);
    expect(loader).toBeDefined();
    expect(loader!.inputPorts).toEqual([
      { types: ['DATAFRAME', 'GEODATAFRAME', 'VALUE', 'LIST', 'JSON', 'RASTER'], cardinality: '[0,n]' },
    ]);
    // A circle on its left, as on a JS Computation node, and one on its right.
    expect(loader!.adapter.handles.filter((h) => h.type === 'target').map((h) => h.id)).toEqual(['in']);
    expect(loader!.adapter.handles.filter((h) => h.type === 'source').map((h) => h.id)).toEqual(['out']);
    expect(loader!.adapter.inputIconType).toBe('N');
    // Its output can be a value, which a scenario drop's copy of a value node is.
    expect(loader!.outputPorts[0].types).toEqual(
      expect.arrayContaining(['DATAFRAME', 'GEODATAFRAME', 'VALUE', 'LIST', 'JSON', 'RASTER']),
    );
    expect(loader!.loadsDataset).toBe(true);
  });

  test('an edge from a Python node lands on its first circle, with no warning', async () => {
    await renderFlow();
    await addNodes(makeNode('area', PYTHON), makeNode('load', LOADER));

    await draw('area', 'load');

    expect(drawn()).toEqual([['area', 'load', 'in']]);
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test('a second node wired in takes its next circle, so several loaders and values meet in one loader', async () => {
    await renderFlow();
    await addNodes(makeNode('area', PYTHON), makeNode('period', PYTHON), makeNode('load', LOADER));

    await draw('area', 'load');
    // Dropped on the taken circle 0: the edge takes the free circle below it.
    await draw('period', 'load');

    expect(drawn()).toEqual([['area', 'load', 'in'], ['period', 'load', 'in_1']]);
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test('guard: an edge back from a node the loader feeds closes a loop and is refused', async () => {
    await renderFlow();
    await addNodes(makeNode('load', LOADER), makeNode('use', PYTHON));
    await draw('load', 'use');

    await draw('use', 'load');

    expect(drawn()).toEqual([['load', 'use', 'in']]);
    expect(mockShowToast).toHaveBeenCalledWith('Cycles are not allowed in the dataflow', 'warning');
  });
});

describe('the readers of a shared value take it on a circle of their own', () => {
  test("an Accumulated Shadow node takes a season on its second circle, and no third input", async () => {
    const shadow = tryGetNodeDescriptor(SHADOW as any);
    expect(shadow!.inputPorts).toEqual([{ types: ['RASTER', 'VALUE'], cardinality: '[1,2]' }]);
    await renderFlow();
    await addNodes(makeNode('heights', RASTERIZE), makeNode('season', PYTHON), makeNode('shadow', SHADOW));
    await draw('heights', 'shadow');

    // Dropped on the taken circle 0: the season takes the free circle below it.
    await draw('season', 'shadow');

    expect(drawn()).toEqual([['heights', 'shadow', 'in'], ['season', 'shadow', 'in_1']]);
    expect(mockShowToast).not.toHaveBeenCalled();

    await addNodes(makeNode('more', PYTHON));
    await draw('more', 'shadow');
    expect(drawn()).toHaveLength(2);
    expect(mockShowToast).toHaveBeenCalledWith('This node takes at most 2 inputs.', 'warning');
  });

  test("a scenario drop's copy of the season, a Data Loading node, feeds a shadow node's second circle", async () => {
    await renderFlow();
    await addNodes(makeNode('heights', RASTERIZE), makeNode('season-copy', LOADER), makeNode('shadow', SHADOW));
    await draw('heights', 'shadow');

    await draw('season-copy', 'shadow');

    expect(drawn()).toEqual([['heights', 'shadow', 'in'], ['season-copy', 'shadow', 'in_1']]);
    expect(mockShowToast).not.toHaveBeenCalled();
  });

  test('a Raster Calculator takes a region on its third circle, after two layers', async () => {
    const calculator = tryGetNodeDescriptor(CALCULATOR as any);
    expect(calculator!.inputPorts).toEqual([{ types: ['RASTER', 'GEODATAFRAME', 'JSON'], cardinality: '[1,3]' }]);
    await renderFlow();
    await addNodes(
      makeNode('tracts', LOADER), makeNode('water', LOADER), makeNode('region', PYTHON),
      makeNode('average', CALCULATOR),
    );
    await draw('tracts', 'average');
    await draw('water', 'average', 'in_1');

    await draw('region', 'average', 'in_2');

    expect(drawn()).toEqual([
      ['tracts', 'average', 'in'], ['water', 'average', 'in_1'], ['region', 'average', 'in_2'],
    ]);
    expect(mockShowToast).not.toHaveBeenCalled();
  });
});
