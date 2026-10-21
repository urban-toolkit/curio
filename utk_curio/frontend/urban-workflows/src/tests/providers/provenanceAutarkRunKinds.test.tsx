/**
 * #1022: an Autark node's runs are filed with the kinds of data they read and
 * returned, as every node's are (provenanceRunKinds.test.tsx), so its runs in
 * the provenance drawer name them. A map hands on the layer it drew, and a run
 * that fails returned an error (adapters/node/autkGrammarBehavior, `recordRun`).
 *
 * Each test runs the real node behavior into the real provider, as
 * provenanceAutarkNode.test.tsx does.
 */
import React from 'react';
import { act, render } from '@testing-library/react';

jest.mock('../../providers/FlowProvider', () => require('../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../providers/ToastProvider', () => require('../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../services/api', () => require('../_support/autkNodeMocks').apiModule);
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => require('../_support/autkNodeMocks').autkGrammarModule,
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({ AutkDb: class { async init() { throw new Error('no autk-db in this test'); } } }),
  { virtual: true },
);

import ProvenanceProvider, { useProvenanceContext, NodeExecRecord } from '../../providers/ProvenanceProvider';
import { useAutkGrammarBehavior } from '../../adapters/node/autkGrammarBehavior';
import { grammarRuns, resetAutkNodeMocks } from '../_support/autkNodeMocks';
import { stubWebGpu, unstubWebGpu } from '../_support/autkNode';

const MAP_ID = '3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57';
/** The map's input: a layer an upstream node returned. */
const INPUT = { path: 'art-1', dataType: 'geodataframe' };
/** A map of the node's input. */
const MAP = JSON.stringify({ map: { layerRefs: [{ dataRef: 'input_0' }] } });
/** Two maps in one document, which a node refuses before anything runs. */
const TWO_MAPS = JSON.stringify({
  map: [{ layerRefs: [{ dataRef: 'input_0' }] }, { layerRefs: [{ dataRef: 'input_0' }] }],
});

/** An Autark map holding *written*, fed INPUT, inside the real provenance provider. */
function mountMap(written: string) {
  const seen: { provenance?: ReturnType<typeof useProvenanceContext>; apply?: (spec: string) => Promise<void> } = {};
  const setOutput = jest.fn();
  const Probe: React.FC = () => {
    seen.provenance = useProvenanceContext();
    const behavior = useAutkGrammarBehavior(
      { nodeId: MAP_ID, input: INPUT, code: written, defaultCode: written } as any,
      { output: { code: '', content: '' }, setOutput, code: written, setCode: jest.fn(), templateData: {} } as any,
    );
    seen.apply = behavior.applyGrammar;
    return <>{behavior.contentComponent}</>;
  };
  render(<ProvenanceProvider><Probe /></ProvenanceProvider>);
  return {
    run: async () => {
      await act(async () => { await seen.apply!(written); });
    },
    runs: (): NodeExecRecord[] => seen.provenance!.provenanceGraphNodes[MAP_ID] ?? [],
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  resetAutkNodeMocks();
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
  jest.restoreAllMocks();
});

test("an Autark map's run is filed with the kind of the layer it drew, which it passes on", async () => {
  const node = mountMap(MAP);

  await node.run();

  expect(node.lastOutput()).toMatchObject({ code: 'success' });
  expect(grammarRuns).toHaveLength(1);
  expect(node.runs()).toHaveLength(1);
  expect(node.runs()[0].inputs).toEqual(['GEODATAFRAME']);
  expect(node.runs()[0].outputs).toEqual(['GEODATAFRAME']);
});

test('an Autark run that fails is filed with what it read, and as returning an error', async () => {
  const node = mountMap(TWO_MAPS);

  await node.run();

  expect(node.lastOutput()).toMatchObject({ code: 'error' });
  expect(node.runs()).toHaveLength(1);
  expect(node.runs()[0].inputs).toEqual(['GEODATAFRAME']);
  expect(node.runs()[0].outputs).toEqual(['ERROR']);
});
