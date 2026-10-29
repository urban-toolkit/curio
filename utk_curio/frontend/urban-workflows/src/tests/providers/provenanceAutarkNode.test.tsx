/**
 * #860: the provenance drawer lists an Autark node's runs. It reads
 * `provenanceGraphNodes[nodeId]` (NodeRunsProvenance.tsx), as it does for every
 * node (#448, provenanceNodeKey.test.tsx), so each run has to be filed there,
 * once, with its document as written: a run's button in the drawer puts that
 * code back in the editor.
 *
 * - A map or a plot draws in the browser, in a run on the server too, which
 *   only forwards it, so its run in the browser is the only one to file.
 * - A document that only loads data runs in the browser wherever runs stay
 *   there, as on a guest's canvas. Its data section reaches the sandbox through
 *   the JavaScript interpreter, a part of the run and not a run of its own.
 * - In a run on the server, the server runs a data node and useServerRun files
 *   that run. The node only shows its outcome, which files nothing more.
 *
 * Each test runs the real node behavior, interpreter or server-run hook into the
 * real provider.
 */
import React from 'react';
import { act, render } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../providers/FlowProvider', () => require('../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../providers/ToastProvider', () => require('../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../services/api', () => require('../_support/autkNodeMocks').apiModule);
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => require('../_support/autkNodeMocks').autkGrammarModule,
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
// A data load that falls back to the browser's own AutkDb fails here, so a data
// node can only succeed through the sandbox.
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({ AutkDb: class { async init() { throw new Error('no autk-db in this test'); } } }),
  { virtual: true },
);
jest.mock('../../services/runs/runsApi', () => {
  const actual = jest.requireActual('../../services/runs/runsApi');
  return {
    ...actual,
    runsApi: {
      start: jest.fn(),
      get: jest.fn(),
      listForProject: jest.fn(),
      cancel: jest.fn(),
      reportStep: jest.fn(),
      follow: jest.fn(),
    },
  };
});

import ProvenanceProvider, { useProvenanceContext, NodeExecRecord } from '../../providers/ProvenanceProvider';
import { useAutkGrammarBehavior } from '../../adapters/node/autkGrammarBehavior';
import { JavaScriptInterpreter } from '../../JavaScriptInterpreter';
import { useServerRun } from '../../providers/flow/useServerRun';
import { runsApi } from '../../services/runs/runsApi';
import type { Run, RunEvent, RunStep } from '../../services/runs/runsApi';
import { grammarRuns, resetAutkNodeMocks } from '../_support/autkNodeMocks';
import { stubWebGpu, unstubWebGpu } from '../_support/autkNode';

const api = runsApi as jest.Mocked<typeof runsApi>;

const MAP_ID = '3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57';
const DATA_ID = '8c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f';
const INPUT = { path: 'art-1', dataType: 'geodataframe' };

/** A map of the node's input, as written: its table named by a chip (#662). */
const MAP_WRITTEN = '{\n  "map": { "layerRefs": [{ "dataRef": [!! input_0 !!] }] }\n}';
/** The same document as the editor hands it to a run, the chip resolved. */
const MAP_RAN = JSON.stringify({ map: { layerRefs: [{ dataRef: 'input_0' }] } });
/** Two maps in one document, which a node refuses before anything runs. */
const TWO_MAPS = JSON.stringify({
  map: [{ layerRefs: [{ dataRef: 'input_0' }] }, { layerRefs: [{ dataRef: 'input_0' }] }],
});
/** Example 06's data node: Back Bay's layers from its extract. */
const DATA_WRITTEN = JSON.stringify({
  data: [{
    type: 'osm',
    pbfFileUrl: 'docs/examples/data/back_bay.osm.pbf',
    queryArea: { geocodeArea: 'Boston', areas: ['Back Bay'] },
    outputTableName: 'table_osm',
    autoLoadLayers: { layers: ['surface', 'roads'] },
  }],
}, null, 2);

type MountedNode = {
  /** Run *spec* as the editor hands it over, and wait for the run to end. */
  run: (spec: string) => Promise<void>;
  /** The runs the provenance drawer lists for the node. */
  runs: () => NodeExecRecord[];
  /** Every run filed, by node id. */
  filed: () => Record<string, NodeExecRecord[]>;
  lastOutput: () => any;
};

/** An Autark node holding *written* in its editor, inside the real provenance provider. */
function mountAutkNode(
  nodeId: string,
  written: string,
  more: { input?: unknown; jsInterpreter?: unknown } = {},
): MountedNode {
  const seen: { provenance?: ReturnType<typeof useProvenanceContext>; apply?: (spec: string) => Promise<void> } = {};
  const setOutput = jest.fn();
  const Probe: React.FC = () => {
    seen.provenance = useProvenanceContext();
    const behavior = useAutkGrammarBehavior(
      { nodeId, input: more.input ?? '', code: written, defaultCode: written, jsInterpreter: more.jsInterpreter } as any,
      { output: { code: '', content: '' }, setOutput, code: written, setCode: jest.fn(), templateData: {} } as any,
    );
    seen.apply = behavior.applyGrammar;
    return <>{behavior.contentComponent}</>;
  };
  render(<ProvenanceProvider><Probe /></ProvenanceProvider>);
  return {
    run: async (spec) => {
      await act(async () => { await seen.apply!(spec); });
    },
    runs: () => seen.provenance!.provenanceGraphNodes[nodeId] ?? [],
    filed: () => seen.provenance!.provenanceGraphNodes,
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
  };
}

/** A sandbox reply to the node's data section, as the backend sends one. */
function sandboxReply(reply: object) {
  return { ok: true, status: 200, json: async () => reply };
}

const realFetch = global.fetch;

beforeEach(() => {
  jest.clearAllMocks();
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
  global.fetch = realFetch;
  jest.restoreAllMocks();
});

test("a run of an Autark map is filed under the node's own id, with its document as written", async () => {
  const node = mountAutkNode(MAP_ID, MAP_WRITTEN, { input: INPUT });

  await node.run(MAP_RAN);

  expect(node.lastOutput()).toMatchObject({ code: 'success' });
  expect(grammarRuns).toHaveLength(1);
  expect(Object.keys(node.filed())).toEqual([MAP_ID]);
  expect(node.runs()).toHaveLength(1);
  // The chip, not what it resolved to: the tab puts this back in the editor.
  expect(node.runs()[0].code).toBe(MAP_WRITTEN);

  // Each run is listed, after the one before it.
  await node.run(MAP_RAN);
  expect(node.runs()).toHaveLength(2);
  expect(node.runs()[1].parentId).toBe(node.runs()[0].id);
});

test("a run that fails is listed too, as a code node's failed run is", async () => {
  const node = mountAutkNode(MAP_ID, TWO_MAPS, { input: INPUT });

  await node.run(TWO_MAPS);

  expect(node.lastOutput()).toMatchObject({ code: 'error' });
  expect(node.runs()).toHaveLength(1);
  expect(node.runs()[0].code).toBe(TWO_MAPS);
});

test('a data node run in the browser is filed once, though its data section reached the sandbox twice', async () => {
  jest.spyOn(console, 'warn').mockImplementation(() => {});
  // The first load fails and the node tries again (runDataInBackend); the second loads.
  const fetchMock = jest.fn()
    .mockResolvedValueOnce(sandboxReply({
      stdout: [], stderr: 'sandbox cold start', output: { path: '', dataType: 'str' },
    }))
    .mockResolvedValueOnce(sandboxReply({
      stdout: [], stderr: '', input: { dataType: '' }, output: { path: 'art-layers', dataType: 'outputs' },
    }));
  global.fetch = fetchMock as any;
  const node = mountAutkNode(DATA_ID, DATA_WRITTEN, { jsInterpreter: new JavaScriptInterpreter() });

  await node.run(DATA_WRITTEN);

  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(node.lastOutput()).toMatchObject({ code: 'success' });
  expect(Object.keys(node.filed())).toEqual([DATA_ID]);
  expect(node.runs()).toHaveLength(1);
  expect(node.runs()[0].code).toBe(DATA_WRITTEN);
});

// A run on the server, as serverRun.test.tsx follows one.

function serverStep(nodeId: string): RunStep {
  return {
    nodeId, label: nodeId, nodeType: 'curio.builtin/autk-grammar', level: 0,
    role: 'run', status: 'pending', startedAt: null, finishedAt: null, durationMs: null,
    outputPath: null, outputType: null, installedDatasetId: null, codeSha256: null,
    stdoutTail: null, stderrTail: null, skipReason: null,
  };
}

function serverRun(id: string, steps: RunStep[]): Run {
  return {
    id, projectId: 'p1', projectName: 'Flow', trigger: 'all', targetNodeId: null,
    wholeDataflow: true, rerunOf: null, specRevision: 3, status: 'queued',
    createdAt: null, startedAt: null, finishedAt: null,
    counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 }, error: null, live: true,
    steps,
  };
}

/** Follow the run through a stream the test drives. */
function followedStream() {
  const handle: { emit: (event: RunEvent) => void } = { emit: () => {} };
  api.follow.mockImplementation((_runId, onEvent, signal) => {
    handle.emit = (event) => act(() => onEvent(event));
    return new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()));
  });
  return handle;
}

test('a data node in a run on the server is filed once: the server ran it, and the node only shows it', async () => {
  const live = followedStream();
  api.start.mockResolvedValue(serverRun('r1', [serverStep(DATA_ID)]));
  let nodes: any[] = [{ id: DATA_ID, position: { x: 0, y: 0 }, data: { code: DATA_WRITTEN } }];
  const playNodes = jest.fn().mockReturnValue(true);
  const deps = {
    reactFlow: {
      getNode: (id: string) => nodes.find((n) => n.id === id),
      getNodes: () => nodes,
      getEdges: () => [],
    },
    setNodes: jest.fn((next: any) => { nodes = typeof next === 'function' ? next(nodes) : next; }),
    showToast: jest.fn(),
    keepDataflow: jest.fn().mockResolvedValue('p1'),
    applyNewOutput: jest.fn(),
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: jest.fn(),
    markNodeErroredRef: { current: jest.fn() },
    playNodes,
    playAllStateRef: { current: null },
    emittedForInputRef: { current: new Map() },
    outputsRef: { current: [] },
    workflowNameRef: { current: 'Flow' },
    flushInstallSyncRef: { current: jest.fn() },
    surfaceInstallWarnings: jest.fn(),
  };
  const seen: { provenance?: any; node?: any; run?: any } = {};
  const Probe: React.FC = () => {
    seen.provenance = useProvenanceContext();
    seen.node = useAutkGrammarBehavior(
      { nodeId: DATA_ID, input: '', code: DATA_WRITTEN, defaultCode: DATA_WRITTEN } as any,
      { output: { code: '', content: '' }, setOutput: jest.fn(), code: DATA_WRITTEN, setCode: jest.fn(), templateData: {} } as any,
    );
    seen.run = useServerRun({ ...deps, nodeExecProv: seen.provenance.nodeExecProv } as any);
    return <>{seen.node.contentComponent}</>;
  };
  render(<ProvenanceProvider><Probe /></ProvenanceProvider>);
  // What UniversalNode does with each outcome the run shows on the node: it
  // hands it to the setter the node's own run uses.
  const showOnTheNode = () => {
    const shown = nodes.find((n) => n.id === DATA_ID)?.data?.serverOutput?.output;
    act(() => { seen.node.setOutputCallbackOverride(shown); });
    return shown;
  };

  await act(async () => { await seen.run.startRun(); });
  live.emit({ kind: 'step_started', nodeId: DATA_ID, startedAt: 1700000000 });
  expect(showOnTheNode()).toEqual({ code: 'exec', content: '' });
  live.emit({
    kind: 'step_finished', nodeId: DATA_ID, status: 'ok', startedAt: 1700000000, finishedAt: 1700000004,
    reply: { stdout: [], stderr: '', input: null, output: { path: 'art-layers', dataType: 'outputs' } },
  });
  expect(showOnTheNode()).toMatchObject({ code: 'success' });

  // The browser runs it no more, and the one run filed is the server's.
  expect(playNodes).not.toHaveBeenCalled();
  expect(Object.keys(seen.provenance.provenanceGraphNodes)).toEqual([DATA_ID]);
  expect(seen.provenance.provenanceGraphNodes[DATA_ID]).toHaveLength(1);
  expect(seen.provenance.provenanceGraphNodes[DATA_ID][0].code).toBe(DATA_WRITTEN);
});
