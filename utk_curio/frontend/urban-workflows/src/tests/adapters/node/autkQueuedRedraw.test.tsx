/**
 * An Autark map asked to draw while a draw is under way draws once more when
 * that draw ends (adapters/node/autkGrammarBehavior), and that draw reads the
 * node's input as it is then, not as it was when the draw under way began. The
 * Map Edits node hands its map a new input on each edit, so a second edit made
 * while the map still drew the first left the map on the first edit's input.
 *
 * The grammar is a stand-in whose runs wait until a test lets them end.
 */
jest.mock('../../../providers/FlowProvider', () => require('../../_support/autkNodeMocks').flowProviderModule);
jest.mock('../../../providers/ToastProvider', () => require('../../_support/autkNodeMocks').toastProviderModule);
jest.mock('../../../services/api', () => require('../../_support/autkNodeMocks').apiModule);
jest.mock('../../../JavaScriptInterpreter', () => ({
  JavaScriptInterpreter: class { },
}));
const mockHeldRuns: Array<{ spec: any; end: () => void }> = [];
jest.mock(
  '@urban-toolkit/autk-grammar',
  () => ({
    AutkGrammar: jest.fn().mockImplementation(() => {
      const grammar: any = { data: {}, maps: [], interactions: { on: () => () => {} } };
      grammar.run = jest.fn((spec: any) => new Promise<void>((resolve) => {
        mockHeldRuns.push({ spec, end: resolve });
      }));
      return grammar;
    }),
  }),
  { virtual: true },
);
jest.mock('@urban-toolkit/autk-compute', () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });

import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { useAutkGrammarBehavior } from '../../../adapters/node/autkGrammarBehavior';
import { inputsByPath, resetAutkNodeMocks } from '../../_support/autkNodeMocks';
import { stubWebGpu, unstubWebGpu } from '../../_support/autkNode';

const MAP = JSON.stringify({ map: { layerRefs: [{ dataRef: 'input_0' }] } });

/** One point whose `marker` says which input it came from. */
function layer(marker: string) {
  return {
    type: 'FeatureCollection',
    features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { marker } }],
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  resetAutkNodeMocks();
  mockHeldRuns.length = 0;
  inputsByPath.current = {
    'art-first': { dataType: 'geodataframe', data: layer('first-input') },
    'art-second': { dataType: 'geodataframe', data: layer('second-input') },
  };
  stubWebGpu();
});

afterEach(() => {
  unstubWebGpu();
});

test('a draw asked for while one is under way runs when it ends, on the input the node holds then', async () => {
  let input: unknown = { path: 'art-first', dataType: 'geodataframe' };
  let apply: (spec: string) => Promise<void> = async () => { };
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      { nodeId: 'map-1', input, defaultCode: '{}', interactionsCallback: jest.fn() } as any,
      { output: { code: '', content: '' }, setOutput: jest.fn(), setCode: jest.fn(), templateData: {} } as any,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <>{behavior.contentComponent}</>;
  };
  const view = render(<Probe />);

  let first: Promise<void> = Promise.resolve();
  act(() => {
    first = apply(MAP);
  });
  await waitFor(() => expect(mockHeldRuns).toHaveLength(1));
  expect(JSON.stringify(mockHeldRuns[0].spec)).toContain('first-input');

  // The node's input changes while the first draw is under way, and a draw is
  // asked for: it waits for the first to end.
  input = { path: 'art-second', dataType: 'geodataframe' };
  act(() => {
    view.rerender(<Probe />);
  });
  let second: Promise<void> = Promise.resolve();
  act(() => {
    second = apply(MAP);
  });

  await act(async () => {
    mockHeldRuns[0].end();
  });
  await waitFor(() => expect(mockHeldRuns).toHaveLength(2));
  const drawn = JSON.stringify(mockHeldRuns[1].spec);
  expect(drawn).toContain('second-input');
  expect(drawn).not.toContain('first-input');

  await act(async () => {
    mockHeldRuns[1].end();
    await first;
    await second;
  });
});
