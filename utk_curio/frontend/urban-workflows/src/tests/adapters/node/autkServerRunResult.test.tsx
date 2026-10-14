/**
 * A step of a run on the server reaches an Autark node through the setter
 * UniversalNode hands `data.serverOutput` to, the behavior's
 * `setOutputCallbackOverride`. A document that only loads data runs in the
 * sandbox there, as the node's own run posts it, so its body then says what it
 * loaded, in the line its own run shows (`describeAutkRun('Loaded', 'table',
 * requestedLayerTables(...))`), and not that it has not run yet.
 */
import React from 'react';
import { act, render } from '@testing-library/react';

// The node reads its input edge from the flow context (hook/useGrammarInputState);
// the real provider would load the whole node registry, vega included.
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => require('../../_support/autkNodeMocks').autkGrammarModule,
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
jest.mock(
  '@urban-toolkit/autk-db',
  () => ({ AutkDb: class { async init() { throw new Error('no autk-db in this test'); } } }),
  { virtual: true },
);

import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { requestedLayerTables } from '../../../adapters/node/autkDataCompile';
import { describeAutkRun } from '../../../adapters/node/autkRunDescriptions';
import type { NodeOutput } from '../../../hook/useNodeState';
import { resetAutkNodeMocks } from '../../_support/autkNodeMocks';

/** Example 06's data node: Back Bay's five layers from its extract. */
const BACK_BAY = {
  data: [{
    type: 'osm',
    pbfFileUrl: 'docs/examples/data/back_bay.osm.pbf',
    queryArea: { geocodeArea: 'Boston', areas: ['Back Bay'] },
    outputTableName: 'table_osm',
    autoLoadLayers: { layers: ['surface', 'parks', 'water', 'roads', 'buildings'] },
  }],
};

/** A server step's result as useServerRun shows it (utils/executionResult). */
const SERVER_RESULT: NodeOutput = { code: 'success', content: 'Saved to file: art-layers' };

/** Mount an Autark node holding *spec*; `show` sets its status from outside its own run. */
function mountNode(spec: object) {
  const code = JSON.stringify(spec, null, 2);
  const setOutput = jest.fn();
  let fromOutside: ((output: NodeOutput) => void) | undefined;
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId: 'loader', input: '', defaultCode: code, code } as any,
      { output: { code: '', content: '' }, setOutput, code, setCode: jest.fn(), templateData: {} } as any,
    );
    fromOutside = behavior.setOutputCallbackOverride;
    return <>{behavior.contentComponent}</>;
  };
  const { container } = render(<Probe />);
  return {
    container,
    setOutput,
    show: (output: NodeOutput) => {
      expect(typeof fromOutside).toBe('function');
      act(() => { fromOutside!(output); });
    },
    summary: () => container.querySelector('[data-curio-autk-summary]')?.textContent ?? null,
  };
}

beforeEach(() => resetAutkNodeMocks());

test('a data node the server ran says what it loaded, as its own run says it', () => {
  const node = mountNode(BACK_BAY);
  // Before: the notice a data node shows until it runs.
  expect(node.container.querySelector('[data-curio-node-empty="not-run"]')).not.toBeNull();

  node.show(SERVER_RESULT);

  expect(node.setOutput).toHaveBeenLastCalledWith(SERVER_RESULT);
  expect(node.summary()).toBe(
    describeAutkRun('Loaded', 'table', requestedLayerTables(BACK_BAY.data)),
  );
  expect(node.summary()).toBe(
    'Loaded 5 tables: table_osm_surface, table_osm_parks, table_osm_water, table_osm_roads, table_osm_buildings',
  );
  expect(node.container.querySelector('[data-curio-node-empty]')).toBeNull();
});

test('a new run, and a failed one, take the line away', () => {
  const node = mountNode(BACK_BAY);
  node.show(SERVER_RESULT);
  expect(node.summary()).not.toBeNull();

  node.show({ code: 'exec', content: '' });
  expect(node.summary()).toBeNull();

  node.show(SERVER_RESULT);
  node.show({ code: 'error', content: 'autk data load produced 1 fewer table(s) than the spec asked for' });
  expect(node.summary()).toBeNull();
  // A run was tried: the body does not say the node has not run.
  expect(node.container.querySelector('[data-curio-node-empty="not-run"]')).toBeNull();
});

test('a document that computes or draws keeps its own run\'s report', () => {
  for (const spec of [
    { compute: [{ dataRef: 'input_0' }] },
    { ...BACK_BAY, map: { layers: [{ dataRef: 'table_osm_roads' }] } },
  ]) {
    const node = mountNode(spec);
    node.show(SERVER_RESULT);
    expect(node.setOutput).toHaveBeenLastCalledWith(SERVER_RESULT);
    expect(node.summary()).toBeNull();
    node.container.remove();
  }
});
