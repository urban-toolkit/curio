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
import { useAutkGrammarBehavior, type AutkBehaviorOptions } from '../../adapters/node/autkGrammarBehavior';
import { __resetWebGpuSupportCache } from '../../utils/webgpuSupport';
import { nodeInput } from './autkNodeMocks';

export type MountedAutkNode = {
  /** Run *spec* and wait for the run to end. */
  run: (spec: object) => Promise<void>;
  lastOutput: () => any;
  /** What the node tells the nodes it is linked to. */
  interactions: jest.Mock;
  /** Render the node again, as a change in the flow it reads does. */
  rerender: () => void;
  /** Take the node off the page, as a deleted node or a closed dataflow does. */
  unmount: () => void;
  /** The rows of panes the node's last run arranged its views in (the behavior's `viewRows`). */
  viewRows: () => number | undefined;
  /** The handles the node adds to its kind's: a dot per view (the behavior's `dynamicHandles`). */
  dynamicHandles: () => any[] | undefined;
  /** What reaches the node over its interaction edges, as the flow delivers it (`data.interactions`). */
  receive: (entries: unknown[]) => Promise<void>;
  /** The node's document written as *code*, as typing it in the node's editor writes it. */
  write: (code: string) => void;
};

/**
 * Mount the node *nodeId*, its input reading *features* (one row when none is
 * given). *input* is what reaches it instead of one artifact (several circles,
 * say), *options* are the behavior's, and *code* is the node's document as
 * written (`{}` when none is given).
 */
export function mountAutkNode(
  nodeId: string,
  features?: unknown,
  { input = { path: 'art-1', dataType: 'geodataframe' }, options, code = '{}' }: {
    input?: unknown; options?: AutkBehaviorOptions; code?: string;
  } = {},
): MountedAutkNode {
  if (features !== undefined) nodeInput.current = features;
  let apply: (spec: string) => Promise<void> = async () => { };
  const setOutput = jest.fn();
  const interactions = jest.fn();
  let viewRows: number | undefined;
  let dynamicHandles: any[] | undefined;
  let written = code;
  let received: unknown[] | undefined;
  const Probe: React.FC = () => {
    const behavior = useAutkGrammarBehavior(
      {
        nodeId,
        input,
        defaultCode: written,
        interactionsCallback: interactions,
        ...(received ? { interactions: received } : {}),
      } as any,
      {
        output: { code: '', content: '' },
        setOutput,
        setCode: jest.fn(),
        templateData: {},
      } as any,
      options,
    );
    apply = behavior.applyGrammar as (spec: string) => Promise<void>;
    viewRows = behavior.viewRows;
    dynamicHandles = behavior.dynamicHandles;
    return <>{behavior.contentComponent}</>;
  };
  const mounted = render(<Probe />);
  return {
    run: async (spec) => {
      await act(async () => { await apply(JSON.stringify(spec)); });
    },
    lastOutput: () => setOutput.mock.calls[setOutput.mock.calls.length - 1]?.[0],
    interactions,
    rerender: () => act(() => { mounted.rerender(<Probe />); }),
    unmount: () => act(() => { mounted.unmount(); }),
    viewRows: () => viewRows,
    dynamicHandles: () => dynamicHandles,
    receive: async (entries) => {
      received = entries;
      await act(async () => {
        mounted.rerender(<Probe />);
        // The highlights are lit once the input is read again.
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    },
    write: (next) => {
      written = next;
      act(() => { mounted.rerender(<Probe />); });
    },
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
