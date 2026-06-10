import React from 'react';
import { renderHook, act } from '@testing-library/react';
import type { NodeBehaviorHook, NodeBehaviorData, UseNodeStateReturn, NodeBehaviorResult } from '../../../registry/types';

jest.setTimeout(15000);

jest.mock('../../../hook/useVega', () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn().mockResolvedValue(undefined) }),
}));

jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({
    nodeExecProv: jest.fn(),
    provenanceGraphNodes: {},
    provenanceGraphNodesRef: { current: {} },
    selectedParentExecRef: { current: {} },
    setSelectedExec: jest.fn(),
    loadNodeProvenance: jest.fn(),
    getAllNodeProvenance: jest.fn(() => ({})),
  }),
}));

jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'test-workflow' } }),
}));

jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock('../../../services/api', () => ({
  fetchData: jest.fn().mockResolvedValue({ data: {}, dataType: 'dataframe' }),
}));

jest.mock('../../../components/editing/OutputContent', () => {
  const mockReact = require('react');
  return { __esModule: true, default: () => mockReact.createElement('div', null, 'output') };
});

jest.mock('reactflow', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  useStoreApi: () => ({
    subscribe: jest.fn().mockReturnValue(jest.fn()),
    getState: () => ({ edges: [] }),
  }),
  useEdges: () => [],
}));

jest.mock('../../../providers/StarterProvider', () => ({
  useStarterContext: () => ({ templates: [] }),
}));

jest.mock('../../../utils/parsing', () => ({
  shortenString: (s: string) => s,
}));

jest.mock('../../../utils/formatters', () => ({
  formatDate: () => '2026-01-01',
  getType: () => ['dataframe'],
  mapTypes: (t: any) => t,
}));

jest.mock('@urban-toolkit/autk-grammar', () => ({ AutkGrammar: jest.fn().mockImplementation(() => ({ run: jest.fn().mockResolvedValue(undefined), data: {} })) }), { virtual: true });

import { useCodeNodeBehavior } from '../../../adapters/node/codeNodeBehavior';
import { useDataExportBehavior } from '../../../adapters/node/dataExportBehavior';
import { useVegaBehavior } from '../../../adapters/node/vegaBehavior';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';
import { useMergeFlowBehavior } from '../../../adapters/node/mergeFlowBehavior';
import { useDataPoolBehavior } from '../../../adapters/node/dataPoolBehavior';
import { useAutkGrammarBehavior, attachMapInteractionZoomFix } from '../../../adapters/node/autkGrammarBehavior';

function makeMockData(overrides: Partial<NodeBehaviorData> = {}): NodeBehaviorData {
  return {
    nodeId: 'node-1',
    nodeType: 'DATA_LOADING',
    outputCallback: jest.fn(),
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
    input: '',
    ...overrides,
  };
}

function makeMockNodeState(overrides: Partial<UseNodeStateReturn> = {}): UseNodeStateReturn {
  return {
    output: { code: '', content: '', outputType: '' },
    setOutput: jest.fn(),
    code: '',
    setCode: jest.fn(),
    sendCode: undefined,
    templateData: {},
    setTemplateData: jest.fn(),
    newTemplateFlag: false,
    showDescriptionModal: false,
    user: undefined,
    setTemplateConfig: jest.fn(),
    promptModal: jest.fn(),
    closeModal: jest.fn(),
    promptDescription: jest.fn(),
    closeDescription: jest.fn(),
    updateTemplate: jest.fn(),
    setSendCodeCallback: jest.fn(),
    ...overrides,
  } as unknown as UseNodeStateReturn;
}

const BEHAVIOR_RESULT_KEYS: (keyof NodeBehaviorResult)[] = [
  'applyGrammar',
  'customWidgetsCallback',
  'defaultValueOverride',
  'sendCodeOverride',
  'setSendCodeCallbackOverride',
  'showLoading',
  'contentComponent',
  'setOutputCallbackOverride',
  'outputOverride',
  'outputIdOverride',
  'disablePlay',
  'dynamicHandles',
  'handlesOverride',
];

function assertValidBehaviorResult(result: NodeBehaviorResult) {
  for (const key of Object.keys(result)) {
    expect(BEHAVIOR_RESULT_KEYS).toContain(key);
  }
}

async function callBehavior(
  hook: NodeBehaviorHook,
  data?: Partial<NodeBehaviorData>,
  nodeState?: Partial<UseNodeStateReturn>,
) {
  const stableData = makeMockData(data);
  const stableNodeState = makeMockNodeState(nodeState);
  let hookResult: { current: NodeBehaviorResult };
  await act(async () => {
    const rendered = renderHook(() =>
      hook(stableData, stableNodeState),
    );
    hookResult = rendered.result;
  });
  return hookResult!;
}

describe('Behavior hooks — NodeBehaviorHook contract conformance', () => {
  describe('useCodeNodeBehavior', () => {
    test('returns empty behavior (output is inline in CodeEditor)', async () => {
      const result = await callBehavior(useCodeNodeBehavior);
      assertValidBehaviorResult(result.current);
      expect(result.current.contentComponent).toBeUndefined();
    });
  });

  describe('useDataExportBehavior', () => {
    test('returns expected fields', async () => {
      const result = await callBehavior(useDataExportBehavior);
      assertValidBehaviorResult(result.current);
      expect(typeof result.current.sendCodeOverride).toBe('function');
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
      expect(typeof result.current.customWidgetsCallback).toBe('function');
      expect(result.current.contentComponent).toBeDefined();
    });
  });

  describe('useVegaBehavior', () => {
    test('returns applyGrammar', async () => {
      const result = await callBehavior(useVegaBehavior);
      assertValidBehaviorResult(result.current);
      expect(typeof result.current.applyGrammar).toBe('function');
    });
  });

  describe('useSimpleVisBehavior', () => {
    test('renders table for tabular input', async () => {
      const result = await callBehavior(useSimpleVisBehavior, {
        input: { dataType: 'dataframe', data: {} } as any,
      });
      assertValidBehaviorResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });

    test('renders image grid for image DataFrame input', async () => {
      const result = await callBehavior(useSimpleVisBehavior, {
        input: { dataType: 'dataframe', data: { image_id: {}, image_content: {} } } as any,
      });
      assertValidBehaviorResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });

    test('returns no contentComponent for non-tabular input (text/value mode)', async () => {
      const result = await callBehavior(useSimpleVisBehavior, {
        input: { dataType: 'value', data: 42 } as any,
      });
      assertValidBehaviorResult(result.current);
      expect(result.current.contentComponent).toBeUndefined();
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
    });
  });

  describe('useMergeFlowBehavior', () => {
    test('returns handlesOverride and setOutputCallbackOverride', async () => {
      const result = await callBehavior(useMergeFlowBehavior);
      assertValidBehaviorResult(result.current);
      expect(Array.isArray(result.current.handlesOverride)).toBe(true);
      // 5 input slots + 1 output handle (fully replaces adapter.handles).
      expect(result.current.handlesOverride!.length).toBe(6);
      expect(typeof result.current.setOutputCallbackOverride).toBe('function');
    });

    test('handles override has correct ids and positions', async () => {
      const result = await callBehavior(useMergeFlowBehavior);
      const handles = result.current.handlesOverride!;

      const inputs = handles.slice(0, 5);
      inputs.forEach((h, i) => {
        expect(h.id).toBe(`in_${i}`);
        expect(h.type).toBe('target');
        expect(h.position).toBe('left');
      });

      const output = handles[5];
      expect(output.id).toBe('out');
      expect(output.type).toBe('source');
      expect(output.position).toBe('right');
    });
  });

  describe('useDataPoolBehavior', () => {
    test('returns contentComponent, customWidgetsCallback, overrides', async () => {
      const result = await callBehavior(useDataPoolBehavior);
      assertValidBehaviorResult(result.current);
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.customWidgetsCallback).toBe('function');
      expect(typeof result.current.setOutputCallbackOverride).toBe('function');
      expect(typeof result.current.setSendCodeCallbackOverride).toBe('function');
      // sendCodeOverride lets Play All wait for processDataAsync to propagate
      // before the next topological level fires.
      expect(typeof result.current.sendCodeOverride).toBe('function');
    });
  });

  describe('useAutkGrammarBehavior', () => {
    test('returns applyGrammar, contentComponent, and default spec', async () => {
      const result = await callBehavior(useAutkGrammarBehavior);
      assertValidBehaviorResult(result.current);
      expect(typeof result.current.applyGrammar).toBe('function');
      expect(result.current.contentComponent).toBeDefined();
      expect(typeof result.current.defaultValueOverride).toBe('string');
    });

    test('omits defaultValueOverride when node already has code', async () => {
      const result = await callBehavior(useAutkGrammarBehavior, {
        defaultCode: '{"map":{}}',
      } as any);
      assertValidBehaviorResult(result.current);
      expect(result.current.defaultValueOverride).toBeUndefined();
    });

    test('data-only node runs the data section in the backend and emits the DuckDB artifact ref', async () => {
      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) =>
          cb({ stdout: [], stderr: '', output: { path: 'art-1', dataType: 'list' } }),
      );
      const outputCallback = jest.fn();
      const result = await callBehavior(useAutkGrammarBehavior, {
        outputCallback,
        jsInterpreter: { interpretCode } as any,
      });

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'geojson',
            geojsonObject: { type: 'FeatureCollection', features: [] },
            outputTableName: 't',
          }],
          // no map / plot => data-only node
        }));
      });

      // The authored data section was sent to the backend sandbox …
      expect(interpretCode).toHaveBeenCalledTimes(1);
      // … and the node emits the DuckDB artifact reference downstream (DB-backed,
      // like a normal code node), not an in-memory layer array.
      expect(outputCallback).toHaveBeenCalledWith('node-1', { path: 'art-1', dataType: 'list' });
    });

    test('render node loads data in the backend, then runs the grammar in the browser', async () => {
      const { fetchData } = require('../../../services/api');
      const { AutkGrammar } = require('@urban-toolkit/autk-grammar');
      // Capture the spec handed to grammar.run so we can assert the backend layer
      // actually survives the DuckDB round-trip into spec.data.
      let runSpec: any = null;
      (AutkGrammar as jest.Mock).mockReset();
      (AutkGrammar as jest.Mock).mockImplementation(() => ({
        run: jest.fn((s: any) => { runSpec = s; return Promise.resolve(); }),
        data: {},
      }));
      // Mock fetchData with the REAL /get shape: parseOutput wraps the 'list'
      // artifact AND each element, so a backend layer array round-trips as
      // {dataType:'list', data:[{dataType:'dict', data:{name,type,geojson}}]}.
      // (The earlier bare-array mock masked a layer-dropping bug in asFc.)
      // Layer carries one feature: the behavior drops empty-FeatureCollection
      // layers before handing them to the grammar (autk-db 2.1.2's loadGeojson
      // throws on an empty FC), so a non-empty layer is needed to verify the
      // backend layer is injected (and that asFc doesn't drop the wrapped layer).
      (fetchData as jest.Mock).mockResolvedValueOnce({
        dataType: 'list',
        data: [
          { dataType: 'dict', data: { name: 't', type: 'points', geojson: { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: {} }] } } },
        ],
      });

      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) =>
          cb({ stdout: [], stderr: '', output: { path: 'art-2', dataType: 'list' } }),
      );
      const result = await callBehavior(useAutkGrammarBehavior, {
        jsInterpreter: { interpretCode } as any,
      });

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'geojson',
            geojsonObject: { type: 'FeatureCollection', features: [] },
            outputTableName: 't',
          }],
          map: { layerRefs: [{ dataRef: 't' }] },
        }));
      });

      // Data ran in the backend …
      expect(interpretCode).toHaveBeenCalledTimes(1);
      // … the layers were fetched back from DuckDB …
      expect(fetchData).toHaveBeenCalledWith('art-2');
      // … and compute/map/plot ran in the browser via AutkGrammar.
      expect(AutkGrammar).toHaveBeenCalledTimes(1);
      // … and the backend layer was injected as a geojson source the map can
      // reference (this fails if asFc drops the parseOutput-wrapped layer).
      expect(runSpec).toBeTruthy();
      const injected = (runSpec.data || []).find((s: any) => s.outputTableName === 't');
      expect(injected).toBeTruthy();
      expect(injected.geojsonObject?.type).toBe('FeatureCollection');
      // coordinateFormat reflects the coordinates as loaded (autk-db 2.1.2
      // keeps tables in EPSG:4326; 2.0.1 projected to EPSG:3395). The mock
      // layer's Point sits at (0,0) degrees, so detection yields WGS84.
      expect(injected.coordinateFormat).toBe('EPSG:4326');
    });
  });

  // The map canvas renders inside React Flow's CSS-scaled viewport, but autk-map
  // reads pointer positions from getBoundingClientRect() (post-scale) while sizing
  // its renderer from offsetWidth (pre-scale). attachMapInteractionZoomFix
  // re-dispatches picking (double-click), wheel-zoom, and drag-pan events with
  // coordinates corrected back into unscaled CSS space so they match the cursor.
  // See autkGrammarBehavior.attachMapInteractionZoomFix.
  describe('attachMapInteractionZoomFix (map interaction under React Flow zoom)', () => {
    let dispose: (() => void) | null = null;

    // Build a canvas whose layout size (offsetWidth/Height) and on-screen rect
    // differ by `scale`, mimicking React Flow's `transform: scale(zoom)`.
    function makeCanvas(opts: { layoutW: number; layoutH: number; left: number; top: number; scale: number }) {
      const canvas = document.createElement('canvas');
      document.body.appendChild(canvas);
      Object.defineProperty(canvas, 'offsetWidth', { value: opts.layoutW, configurable: true });
      Object.defineProperty(canvas, 'offsetHeight', { value: opts.layoutH, configurable: true });
      const width = opts.layoutW * opts.scale;
      const height = opts.layoutH * opts.scale;
      canvas.getBoundingClientRect = () => ({
        left: opts.left, top: opts.top, width, height,
        right: opts.left + width, bottom: opts.top + height,
        x: opts.left, y: opts.top, toJSON: () => {},
      }) as DOMRect;
      return canvas;
    }

    // attach() also captures the disposer so afterEach removes the window listeners.
    function attach(canvas: HTMLCanvasElement) { dispose = attachMapInteractionZoomFix(canvas); }

    afterEach(() => { dispose?.(); dispose = null; document.body.innerHTML = ''; });

    test('corrects double-click picking into unscaled CSS space at zoom 0.5', () => {
      const canvas = makeCanvas({ layoutW: 800, layoutH: 600, left: 100, top: 50, scale: 0.5 });
      attach(canvas);

      // Stand-in for autk-map's own (registration-order: later) dblclick handler.
      const received: Array<{ x: number; y: number }> = [];
      canvas.addEventListener('dblclick', (e) => received.push({ x: e.clientX, y: e.clientY }));

      // Click at the rendered canvas's midpoint (rect spans x:100..500, y:50..350).
      canvas.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, clientX: 300, clientY: 200 }));

      // The handler must see exactly one event, in unscaled CSS coordinates: the
      // midpoint click maps to (400,300) past the rect origin → clientX/Y 500/350.
      expect(received).toEqual([{ x: 500, y: 350 }]);
    });

    test('corrects wheel-zoom coordinates (zoom center) at zoom 0.5', () => {
      const canvas = makeCanvas({ layoutW: 800, layoutH: 600, left: 100, top: 50, scale: 0.5 });
      attach(canvas);

      const received: Array<{ x: number; y: number; deltaY: number }> = [];
      // autk-map binds 'wheel' on the canvas; mirror that to capture what it sees.
      canvas.addEventListener('wheel', (e) => received.push({ x: e.clientX, y: e.clientY, deltaY: e.deltaY }));

      canvas.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, clientX: 300, clientY: 200, deltaY: 120 }));

      // Same midpoint correction as picking, with the scroll delta preserved.
      expect(received).toEqual([{ x: 500, y: 350, deltaY: 120 }]);
    });

    test('passes the event through untouched when there is no zoom (scale 1)', () => {
      const canvas = makeCanvas({ layoutW: 800, layoutH: 600, left: 0, top: 0, scale: 1 });
      attach(canvas);

      const received: Array<{ x: number; y: number }> = [];
      canvas.addEventListener('dblclick', (e) => received.push({ x: e.clientX, y: e.clientY }));

      canvas.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, clientX: 300, clientY: 200 }));

      // No re-dispatch, original coordinates preserved.
      expect(received).toEqual([{ x: 300, y: 200 }]);
    });
  });
});
