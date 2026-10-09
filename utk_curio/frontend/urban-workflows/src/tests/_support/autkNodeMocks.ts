/**
 * What a suite that mounts an Autark node (_support/autkNode) mocks the node's
 * modules with: the flow, the toasts, the input it fetches, and a stand-in
 * grammar that records what the node hands it and reports picks and brushes
 * as autk-grammar does. Free of app imports, so a `jest.mock` factory can
 * require it:
 *
 *     jest.mock("<src>/providers/FlowProvider", () => require("<this file>").flowProviderModule);
 */

/** One run of the stand-in grammar. */
export type GrammarRun = {
  targets: Record<string, unknown>;
  spec: any;
  /** A pick on the map, as autk-grammar reports one: drawn positions. */
  pick: (selection: number[]) => void;
  /** A brush on the plot, as autk-grammar reports one: positions in the plot's table. */
  brush: (selection: number[]) => void;
};

/** Every run of the stand-in grammar, in order. */
export const grammarRuns: GrammarRun[] = [];

export const AutkGrammar = jest.fn().mockImplementation((targets: Record<string, unknown>) => {
  const handlers: Record<string, (event: any) => void> = {};
  const grammar: any = {
    data: {},
    interactions: {
      on: (event: string, handler: (event: any) => void) => {
        handlers[event] = handler;
        return () => { delete handlers[event]; };
      },
    },
  };
  grammar.run = jest.fn(async (spec: any) => {
    grammarRuns.push({
      targets,
      spec,
      pick: (selection) => handlers['map:picking']?.({ selection }),
      brush: (selection) => handlers['plot:selection']?.({ selection }),
    });
  });
  return grammar;
});

export const markNodeErrored = jest.fn();
export const showToast = jest.fn();

/** One upstream row, so a layer or a plot naming `input_0` resolves. */
export const ONE_ROW = {
  type: 'FeatureCollection',
  features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: { pop: 1 } }],
};

/** The FeatureCollection the node's input reads. */
export const nodeInput: { current: any } = { current: ONE_ROW };

export const flowProviderModule = {
  useFlowContext: () => ({ edges: [], nodeExecStatus: {}, markNodeErrored, workflowNameRef: { current: 'wf' } }),
};
export const toastProviderModule = { useToastContext: () => ({ showToast }) };
export const apiModule = {
  fetchData: jest.fn(async () => ({ dataType: 'geodataframe', data: nodeInput.current })),
  fetchPreviewData: jest.fn(),
};
export const autkGrammarModule = { AutkGrammar };

/** Forget the runs and calls of the last test, and read ONE_ROW again. */
export function resetAutkNodeMocks(): void {
  grammarRuns.length = 0;
  AutkGrammar.mockClear();
  markNodeErrored.mockClear();
  showToast.mockClear();
  nodeInput.current = ONE_ROW;
}
