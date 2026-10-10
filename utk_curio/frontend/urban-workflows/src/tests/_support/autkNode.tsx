/**
 * An Autark node under test (adapters/node/autkGrammarBehavior), drawing with
 * the stand-in grammar of _support/autkNodeMocks. A suite that mounts one
 * mocks the node's modules first:
 *
 *     jest.mock("<src>/providers/FlowProvider", () => require("<_support>/autkNodeMocks").flowProviderModule);
 *     jest.mock("<src>/providers/ToastProvider", () => require("<_support>/autkNodeMocks").toastProviderModule);
 *     jest.mock("<src>/services/api", () => require("<_support>/autkNodeMocks").apiModule);
 *     jest.mock("<src>/JavaScriptInterpreter", () => ({ JavaScriptInterpreter: class {} }));
 *     jest.mock("@urban-toolkit/autk-grammar", () => require("<_support>/autkNodeMocks").autkGrammarModule, { virtual: true });
 *     jest.mock("@urban-toolkit/autk-compute", () => ({ ComputeGpgpu: jest.fn() }), { virtual: true });
 */
import React from 'react';
import { act, render } from '@testing-library/react';
import { useAutkGrammarBehavior } from '../../adapters/node/autkGrammarBehavior';
import { __resetWebGpuSupportCache } from '../../utils/webgpuSupport';
import { nodeInput } from './autkNodeMocks';

export type MountedAutkNode = {
  /** Run *spec* and wait for the run to end. */
  run: (spec: object) => Promise<void>;
  lastOutput: () => any;
  /** What the node tells the nodes it is linked to. */
  interactions: jest.Mock;
};

/** Mount the node *nodeId*, its input reading *features* (one row when none is given). */
export function mountAutkNode(nodeId: string, features?: unknown): MountedAutkNode {
  if (features !== undefined) nodeInput.current = features;
  let apply: (spec: string) => Promise<void> = async () => { };
  const setOutput = jest.fn();
  const interactions = jest.fn();
  const input = { path: 'art-1', dataType: 'geodataframe' };
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      {
        nodeId,
        input,
        defaultCode: '{}',
        interactionsCallback: interactions,
      } as any,
      {
        output: { code: '', content: '' },
        setOutput,
        setCode: jest.fn(),
        templateData: {},
      } as any,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    return <>{behavior.contentComponent}</>;
  };
  render(<Probe />);
  return {
    run: async (spec) => {
      await act(async () => { await apply(JSON.stringify(spec)); });
    },
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
    interactions,
  };
}

/** What the node sent last: its `autk_selection`. */
export function lastSelection(node: MountedAutkNode): any {
  const calls = node.interactions.mock.calls;
  return calls[calls.length - 1]?.[0]?.autk_selection;
}

/** A browser with a WebGPU adapter, as the node asks for one before it draws. */
export function stubWebGpu(): void {
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', {
    configurable: true,
    value: {
      requestAdapter: jest.fn().mockResolvedValue({ name: 'fake' }),
      getPreferredCanvasFormat: () => 'bgra8unorm',
    },
  });
}

export function unstubWebGpu(): void {
  __resetWebGpuSupportCache();
  Object.defineProperty(navigator, 'gpu', { configurable: true, value: undefined });
}
