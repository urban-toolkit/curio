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

// `useEdges()` is settable per test so a Play-All test can wire the merge's
// input slots. Defaults to [] for every other behavior test; reset in afterEach.
let mockEdges: any[] = [];
jest.mock('reactflow', () => ({
  Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
  useStoreApi: () => ({
    subscribe: jest.fn().mockReturnValue(jest.fn()),
    getState: () => ({ edges: [] }),
  }),
  useEdges: () => mockEdges,
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

// In-browser AutkDb fallback (loadSpecLayers). Mockable per test so the
// "backend fails → fall back to browser" path can be exercised. `mock`-prefixed
// names are the only out-of-scope refs jest.mock's hoisted factory may capture.
const mockAutkDbLoadOsm = jest.fn().mockResolvedValue(undefined);
// Declared with a rest parameter so the forwarding wrapper below
// (`(...a: any[]) => mockAutkDbGetLayerTables(...a)`) can spread into it.
const mockAutkDbGetLayerTables = jest.fn(
  (..._a: unknown[]) => [] as Array<{ name: string; type?: string }>,
);
jest.mock('@urban-toolkit/autk-db', () => ({
  AutkDb: jest.fn().mockImplementation(() => ({
    init: jest.fn().mockResolvedValue(undefined),
    loadOsm: (...a: any[]) => mockAutkDbLoadOsm(...a),
    loadGeojson: jest.fn().mockResolvedValue(undefined),
    loadCsv: jest.fn().mockResolvedValue(undefined),
    loadJson: jest.fn().mockResolvedValue(undefined),
    getLayerTables: (...a: any[]) => mockAutkDbGetLayerTables(...a),
    getLayer: jest.fn().mockResolvedValue({ type: 'FeatureCollection', features: [] }),
  })),
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: 'EPSG:3395',
}), { virtual: true });

import { useCodeNodeBehavior } from '../../../adapters/node/codeNodeBehavior';
import { useDataExportBehavior } from '../../../adapters/node/dataExportBehavior';
import { useVegaBehavior } from '../../../adapters/node/vegaBehavior';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';
import { useMergeFlowBehavior } from '../../../adapters/node/mergeFlowBehavior';
import { useDataPoolBehavior } from '../../../adapters/node/dataPoolBehavior';
import { useAutkGrammarBehavior, attachMapInteractionZoomFix, requestedLayerTables, SANDBOX_BACKEND_URL_TOKEN } from '../../../adapters/node/autkGrammarBehavior';
import { __resetWebGpuSupportCache } from '../../../utils/webgpuSupport';

function makeMockData(overrides: Partial<NodeBehaviorData> = {}): NodeBehaviorData {
  return {
    nodeId: 'node-1',
    // Real versioned dispatcher id, as the palette/loadTrill produce since the
    // curio.builtin@1 pack — invented unversioned strings masked dev/64.
    nodeType: 'curio.builtin/data-loading@1',
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

    // Regression for #151: Merge Flow must not set `disablePlay`. When it did,
    // UniversalNode's Play-All handler short-circuited (signalNodeExecDone +
    // return) before invoking `sendCode`, so the run advanced to the downstream
    // level before the merged output was propagated — downstream nodes then ran
    // with stale/empty input. Routing Play All through `sendCodeOverride`
    // (which emits synchronously, then signals done) is what fixes it.
    test('does not disable Play and exposes sendCodeOverride for Play All', async () => {
      const result = await callBehavior(useMergeFlowBehavior);
      expect(result.current.disablePlay).toBeFalsy();
      expect(typeof result.current.sendCodeOverride).toBe('function');
    });

    afterEach(() => {
      mockEdges = [];
    });

    // The actual #151 bug was about ORDERING: Play All must propagate the merged
    // output downstream *synchronously* (before the run advances). This drives
    // sendCodeOverride and asserts outputCallback fires synchronously with the
    // full merged array — so a regression where sendCodeOverride stops emitting
    // synchronously (e.g. becomes async) is caught, not just re-adding disablePlay.
    test('sendCodeOverride emits the merged output synchronously when all slots are ready', async () => {
      mockEdges = [
        { source: 'a', target: 'merge-1', targetHandle: 'in_0' },
        { source: 'b', target: 'merge-1', targetHandle: 'in_1' },
      ];
      const outputCallback = jest.fn();
      const setOutput = jest.fn();
      const result = await callBehavior(
        useMergeFlowBehavior,
        { nodeId: 'merge-1', outputCallback, input: [{ id: 'a-data' }, { id: 'b-data' }] },
        { setOutput },
      );

      // Ignore any emission from the mount effect; assert only the Play-All call.
      outputCallback.mockClear();
      act(() => {
        result.current.sendCodeOverride!('print(1)');
      });

      // Propagated synchronously (we assert right after the sync act, no await)
      // with the merged slot array — and no "inputs not ready" error.
      expect(outputCallback).toHaveBeenCalledTimes(1);
      expect(outputCallback).toHaveBeenCalledWith('merge-1', {
        data: [{ id: 'a-data' }, { id: 'b-data' }],
        dataType: 'outputs',
      });
      expect(setOutput).not.toHaveBeenCalled();
    });

    // The flip side: Play All must NOT emit stale/partial input when a wired slot
    // is still empty — it surfaces an error instead of propagating downstream.
    test('sendCodeOverride does not propagate partial input; reports inputs-not-ready', async () => {
      mockEdges = [
        { source: 'a', target: 'merge-2', targetHandle: 'in_0' },
        { source: 'b', target: 'merge-2', targetHandle: 'in_1' },
      ];
      const outputCallback = jest.fn();
      const setOutput = jest.fn();
      const result = await callBehavior(
        useMergeFlowBehavior,
        { nodeId: 'merge-2', outputCallback, input: [{ id: 'a-data' }] }, // only 1 of 2 ready
        { setOutput },
      );

      outputCallback.mockClear();
      act(() => {
        result.current.sendCodeOverride!('print(1)');
      });

      expect(outputCallback).not.toHaveBeenCalled();
      expect(setOutput).toHaveBeenCalledTimes(1);
      expect(setOutput.mock.calls[0][0].code).toBe('error');
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
    // Autark refuses to run without a WebGPU adapter now (#201), and jsdom has
    // no `navigator.gpu` at all - so without this every case in here would take
    // the refusal path and assert nothing about the grammar. The dedicated
    // coverage for the refusal itself is
    // `autkGrammarWebgpuFallback.test.tsx`.
    beforeEach(() => {
      __resetWebGpuSupportCache();
      Object.defineProperty(navigator, 'gpu', {
        configurable: true,
        value: { requestAdapter: jest.fn().mockResolvedValue({ name: 'fake' }) },
      });
    });

    afterEach(() => {
      __resetWebGpuSupportCache();
      Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });
    });

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

    // dev/70 regression: the seed decision is frozen at mount. ``data.code`` is
    // mutated by useNodeState one commit behind the editor (and the old reset
    // chain even wrote ``undefined`` into it), so deriving the override from it
    // per render flip-flopped ``defaultValue`` and reset the editor to the
    // default spec while the user typed.
    test('defaultValueOverride stays stable while data.code mutates mid-typing (dev/70)', async () => {
      const stableData = makeMockData();
      const stableNodeState = makeMockNodeState();
      let rendered: any;
      await act(async () => {
        rendered = renderHook(() => useAutkGrammarBehavior(stableData, stableNodeState));
      });

      const seed = rendered.result.current.defaultValueOverride;
      expect(typeof seed).toBe('string');

      // Editor floats a keystroke back into the mutable node data.
      (stableData as any).code = '{"user":"typed"}';
      await act(async () => { rendered.rerender(); });
      expect(rendered.result.current.defaultValueOverride).toBe(seed);

      // The old reset chain cleared it again — the override must not flip back.
      (stableData as any).code = undefined;
      await act(async () => { rendered.rerender(); });
      expect(rendered.result.current.defaultValueOverride).toBe(seed);

      // An explicit external update (dataset drop / LLM apply) writes
      // data.defaultCode via updateDefaultCode and must win over the seed.
      (stableData as any).defaultCode = '{"map":{}}';
      await act(async () => { rendered.rerender(); });
      expect(rendered.result.current.defaultValueOverride).toBeUndefined();
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

    // Regression: the flaky 06-autark-what-if-shadow-study failure. The backend
    // data load occasionally returns no artifact; the node then fell back to an
    // in-browser AutkDb load whose PBF fetch 404'd, and autk-db crashed with
    // "Cannot read properties of null (reading 'length')" — surfaced to the user
    // as an opaque error with no hint at the real (backend) cause. The fix:
    // retry the backend load once, and when both paths fail, report BOTH reasons
    // instead of letting a null-deref escape.
    test('data-only node: backend failure retries once, then surfaces an attributed error (no null crash)', async () => {
      // Backend load always fails (no output.path) with a known stderr.
      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) =>
          cb({ stdout: [], stderr: 'sandbox boom', output: { path: '', dataType: 'str' } }),
      );
      // In-browser fallback also fails: the PBF load rejects (mirrors the 404),
      // and no tables result — loadSpecLayers must report this, not crash.
      mockAutkDbLoadOsm.mockReset();
      mockAutkDbLoadOsm.mockRejectedValue(new Error('HTTP error! Status: 404'));
      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([]);

      const setOutput = jest.fn();
      const result = await callBehavior(
        useAutkGrammarBehavior,
        { jsInterpreter: { interpretCode } as any },
        { setOutput },
      );

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'osm',
            pbfFileUrl: 'docs/examples/data/back_bay.osm.pbf',
            outputTableName: 'table_osm',
            autoLoadLayers: { layers: ['surface'] },
          }],
          // no map / plot => data-only node
        }));
      });

      // The backend load was retried once (2 attempts total) before falling back.
      expect(interpretCode).toHaveBeenCalledTimes(2);

      // The node ends in error with an ATTRIBUTED message carrying BOTH reasons …
      const errCall = setOutput.mock.calls.find((c: any[]) => c[0]?.code === 'error');
      expect(errCall).toBeTruthy();
      expect(errCall![0].content).toContain('sandbox boom');
      expect(errCall![0].content).toContain('404');
      // … and never the opaque autk-db null-deref the user used to see.
      expect(errCall![0].content).not.toContain("reading 'length'");

      // Restore defaults so the persistent rejection can't leak to later tests.
      mockAutkDbLoadOsm.mockReset();
      mockAutkDbLoadOsm.mockResolvedValue(undefined);
      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([]);
    });

    // Regression for #248. autk-db's loadOsm walks autoLoadLayers.layers in
    // order and lets a per-layer failure propagate, so a throw partway leaves
    // the earlier tables registered and the later ones absent. Both loaders used
    // to publish whatever getLayerTables() held, so the node that actually
    // failed went green and the breakage surfaced two nodes downstream as
    // "Table table_osm_roads not found" from a spatialQuery.
    test('data-only node: a SHORT load fails the node and names the missing table (#248)', async () => {
      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) =>
          cb({ stdout: [], stderr: 'sandbox short load', output: { path: '', dataType: 'str' } }),
      );
      // The exact #248 state: the load broke partway (a recorded reason) and
      // three of the four requested layers exist. `roads` is last in the spec,
      // so `roads` is the one that goes missing.
      mockAutkDbLoadOsm.mockReset();
      mockAutkDbLoadOsm.mockRejectedValue(new Error('undici assert(!this.paused)'));
      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([
        { name: 'table_osm_surface', type: 'surface' },
        { name: 'table_osm_parks', type: 'parks' },
        { name: 'table_osm_water', type: 'water' },
      ]);

      const setOutput = jest.fn();
      const outputCallback = jest.fn();
      const result = await callBehavior(
        useAutkGrammarBehavior,
        { jsInterpreter: { interpretCode } as any, outputCallback },
        { setOutput },
      );

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'osm',
            pbfFileUrl: 'docs/examples/data/niteroi.osm.pbf',
            outputTableName: 'table_osm',
            autoLoadLayers: { dropOsmTable: true, layers: ['surface', 'parks', 'water', 'roads'] },
          }],
          // no map / plot => data-only node
        }));
      });

      // The node ends in error naming the table that is missing, and why .
      const errCall = setOutput.mock.calls.find((c: any[]) => c[0]?.code === 'error');
      expect(errCall).toBeTruthy();
      expect(errCall![0].content).toContain('table_osm_roads');
      expect(errCall![0].content).toContain('undici');
      // . and the three layers that DID load are never published downstream, so
      // no consumer can trip over the missing fourth.
      expect(outputCallback).not.toHaveBeenCalled();
      // dropOsmTable drops the raw osm tables on purpose - they must not be
      // reported as missing, or every spec that sets it would fail.
      expect(errCall![0].content).not.toContain('table_osm_boundaries');

      mockAutkDbLoadOsm.mockReset();
      mockAutkDbLoadOsm.mockResolvedValue(undefined);
      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([]);
    });

    // The recovery half of #248: a short load is usually a transient in a
    // city-scale PBF read, and making it a failure is what finally reaches
    // runDataInBackend's existing retry (which only ever fired on "no
    // output.path", a shape a partial load never produced).
    test('data-only node: a load that fails once then succeeds recovers on the retry (#248)', async () => {
      let attempt = 0;
      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) => {
          attempt += 1;
          cb(attempt === 1
            ? {
              stdout: [],
              stderr: 'autk data load produced 1 fewer table(s) than the spec asked for'
                + ' - missing: table_osm_roads',
              output: { path: '', dataType: 'str' },
            }
            : { stdout: [], stderr: '', output: { path: 'art-ok', dataType: 'list' } });
        },
      );

      const setOutput = jest.fn();
      const outputCallback = jest.fn();
      const result = await callBehavior(
        useAutkGrammarBehavior,
        { jsInterpreter: { interpretCode } as any, outputCallback },
        { setOutput },
      );

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'osm',
            pbfFileUrl: 'docs/examples/data/niteroi.osm.pbf',
            outputTableName: 'table_osm',
            autoLoadLayers: { layers: ['surface', 'parks', 'water', 'roads'] },
          }],
        }));
      });

      expect(interpretCode).toHaveBeenCalledTimes(2);
      // Recovered: the artifact ref goes downstream and the node is not in error.
      expect(outputCallback).toHaveBeenCalledWith('node-1', { path: 'art-ok', dataType: 'list' });
      expect(setOutput.mock.calls.find((c: any[]) => c[0]?.code === 'error')).toBeFalsy();
    });

    // The other side of the predicate: missing WITHOUT a recorded error is a
    // genuinely empty query area (autk-db creates a layer table even at zero
    // features), so it must warn rather than fail. This is what keeps the
    // contract check from turning sparse data into a red node.
    test('data-only node: an empty query area with no load error does not fail (#248)', async () => {
      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) =>
          cb({ stdout: [], stderr: 'sandbox down', output: { path: '', dataType: 'str' } }),
      );
      // Load succeeded (nothing recorded), it just found nothing.
      mockAutkDbLoadOsm.mockReset();
      mockAutkDbLoadOsm.mockResolvedValue(undefined);
      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([]);

      const setOutput = jest.fn();
      const result = await callBehavior(
        useAutkGrammarBehavior,
        { jsInterpreter: { interpretCode } as any },
        { setOutput },
      );

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'osm',
            pbfFileUrl: 'docs/examples/data/niteroi.osm.pbf',
            outputTableName: 'table_osm',
            autoLoadLayers: { layers: ['parks'] },
          }],
        }));
      });

      const errCall = setOutput.mock.calls.find((c: any[]) => c[0]?.code === 'error');
      expect(errCall?.[0]?.content ?? '').not.toContain('fewer table');
    });

    // The case the seven-workflow e2e run turned up: the layers exist in the DB
    // but getLayer() throws "Cannot read properties of null" for some of them,
    // so the array published downstream is short. That is the same loss as a
    // table that was never created - a consumer asking for table_osm_roads
    // cannot tell the two apart - so it has to fail here too. An genuinely
    // EMPTY layer is not affected: getLayer returns an empty FeatureCollection
    // for it and it stays in the published array.
    test('data-only node: a requested layer that cannot be exported also fails (#248)', async () => {
      const interpretCode = jest.fn(
        (_unresolved, _code, _input, _inputTypes, cb) =>
          cb({ stdout: [], stderr: 'osm: fetch failed', output: { path: '', dataType: 'str' } }),
      );
      // The load itself succeeded and created all four tables .
      mockAutkDbLoadOsm.mockReset();
      mockAutkDbLoadOsm.mockResolvedValue(undefined);
      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([
        { name: 'table_osm_surface', type: 'surface' },
        { name: 'table_osm_parks', type: 'parks' },
        { name: 'table_osm_water', type: 'water' },
        { name: 'table_osm_roads', type: 'roads' },
      ]);
      // . but two of them are empty, so exporting them throws.
      const { AutkDb } = require('@urban-toolkit/autk-db');
      (AutkDb as jest.Mock).mockImplementationOnce(() => ({
        init: jest.fn().mockResolvedValue(undefined),
        loadOsm: (...a: any[]) => mockAutkDbLoadOsm(...a),
        loadGeojson: jest.fn().mockResolvedValue(undefined),
        loadCsv: jest.fn().mockResolvedValue(undefined),
        loadJson: jest.fn().mockResolvedValue(undefined),
        getLayerTables: (...a: any[]) => mockAutkDbGetLayerTables(...a),
        getLayer: jest.fn((name: string) => (
          name === 'table_osm_parks' || name === 'table_osm_water'
            ? Promise.reject(new TypeError("Cannot read properties of null (reading 'length')"))
            : Promise.resolve({ type: 'FeatureCollection', features: [] })
        )),
      }));

      const setOutput = jest.fn();
      const result = await callBehavior(
        useAutkGrammarBehavior,
        { jsInterpreter: { interpretCode } as any },
        { setOutput },
      );

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'osm',
            pbfFileUrl: 'docs/examples/data/niteroi.osm.pbf',
            outputTableName: 'table_osm',
            autoLoadLayers: { layers: ['surface', 'parks', 'water', 'roads'] },
          }],
        }));
      });

      // Reported by name, with the export failure as the reason, rather than
      // handing a two-layer array to a node that asked for four.
      const errCall = setOutput.mock.calls.find((c: any[]) => c[0]?.code === 'error');
      expect(errCall).toBeTruthy();
      expect(errCall![0].content).toContain('table_osm_parks');
      expect(errCall![0].content).toContain('table_osm_water');
      // The two that DID export are not reported as missing.
      expect(errCall![0].content).not.toContain('table_osm_surface');
      expect(errCall![0].content).not.toContain('table_osm_roads');

      mockAutkDbGetLayerTables.mockReset();
      mockAutkDbGetLayerTables.mockReturnValue([]);
    });

    // The browser must not put a host or port in a URL the SANDBOX will fetch:
    // the two are in different network namespaces under Docker, and on a
    // custom-port stack no constant is right. Forcing :5002 here made every
    // OSM/PBF load fail with "fetch failed" on any non-default-port stack,
    // which silently pushed each Autark data load onto the in-browser
    // fallback (#248).
    test('data-only node: the sandbox gets a backend-URL token, never an address (#248)', async () => {
      let sentCode = '';
      const interpretCode = jest.fn(
        (_unresolved, code, _input, _inputTypes, cb) => {
          sentCode = code;
          cb({ stdout: [], stderr: '', output: { path: 'art-1', dataType: 'list' } });
        },
      );

      const result = await callBehavior(useAutkGrammarBehavior, {
        jsInterpreter: { interpretCode } as any,
      });

      await act(async () => {
        await result.current.applyGrammar!(JSON.stringify({
          data: [{
            type: 'osm',
            pbfFileUrl: 'docs/examples/data/niteroi.osm.pbf',
            outputTableName: 'table_osm',
            autoLoadLayers: { layers: ['roads'] },
          }],
        }));
      });

      // The relative path is still resolved against a base .
      expect(sentCode).toContain(
        `${SANDBOX_BACKEND_URL_TOKEN}/file/docs/examples/data/niteroi.osm.pbf`,
      );
      // . but that base is the token the sandbox resolves at execution time,
      // not an address guessed in the browser.
      expect(sentCode).not.toContain('5002');
      expect(sentCode).not.toContain('127.0.0.1');
      expect(sentCode).not.toContain('localhost');
    });
  });

  // The naming rules the contract check is built on. Kept as a direct unit test
  // because a wrong name here is invisible in the happy path and shows up only
  // as a phantom "missing table" failure - or, worse, as the silent short load
  // of #248 going undetected.
  describe('requestedLayerTables (autk data-spec contract)', () => {
    test('osm: one table per requested layer, using autk-db naming', () => {
      expect(requestedLayerTables([{
        type: 'osm',
        outputTableName: 'table_osm',
        autoLoadLayers: { layers: ['surface', 'parks', 'water', 'roads'] },
      }])).toEqual([
        'table_osm_surface', 'table_osm_parks', 'table_osm_water', 'table_osm_roads',
      ]);
    });

    test('osm: dropOsmTable does not make the raw osm tables expected', () => {
      const names = requestedLayerTables([{
        type: 'osm',
        outputTableName: 'table_osm',
        autoLoadLayers: { dropOsmTable: true, layers: ['roads'] },
      }]);
      expect(names).toEqual(['table_osm_roads']);
      expect(names).not.toContain('table_osm');
      expect(names).not.toContain('table_osm_boundaries');
    });

    test('geojson / csv / json: the declared outputTableName', () => {
      expect(requestedLayerTables([
        { type: 'geojson', outputTableName: 'g' },
        { type: 'csv', outputTableName: 'c' },
        { type: 'json', outputTableName: 'j' },
      ])).toEqual(['g', 'c', 'j']);
    });

    test('join: expects nothing (it rewrites a table another source created)', () => {
      expect(requestedLayerTables([{
        type: 'join',
        tableRootName: 'table_osm_roads',
        tableJoinName: 'lst',
        output: { type: 'MODIFY_ROOT' },
      }])).toEqual([]);
    });

    test('tolerates specs with nothing to promise', () => {
      expect(requestedLayerTables([])).toEqual([]);
      expect(requestedLayerTables(undefined as any)).toEqual([]);
      // osm with no autoLoadLayers splits no layers, so it promises no layer table.
      expect(requestedLayerTables([{ type: 'osm', outputTableName: 'table_osm' }])).toEqual([]);
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
