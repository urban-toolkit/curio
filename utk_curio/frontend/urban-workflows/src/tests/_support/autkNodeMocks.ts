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
  /** Each highlight the node asked of this run's map, in order: the table and the positions lit up (none: cleared). */
  highlights: Array<[string, number[]]>;
  /** The maps this run drew, made by `drawnMaps.make` when a test sets it. */
  maps: any[];
};

/** Every run of the stand-in grammar, in order. */
export const grammarRuns: GrammarRun[] = [];

/** What makes the map a run draws, for a test that reads its camera; none unless a test sets it. */
export const drawnMaps: { make: null | (() => any) } = { make: null };

export const AutkGrammar = jest.fn().mockImplementation((targets: Record<string, unknown>) => {
  const handlers: Record<string, (event: any) => void> = {};
  const highlights: Array<[string, number[]]> = [];
  const grammar: any = {
    data: {},
    interactions: {
      on: (event: string, handler: (event: any) => void) => {
        handlers[event] = handler;
        return () => { delete handlers[event]; };
      },
    },
    highlightOnMap: jest.fn((table: string, positions: number[]) => { highlights.push([table, [...positions]]); }),
    clearHighlightOnMap: jest.fn((table: string) => { highlights.push([table, []]); }),
  };
  grammar.run = jest.fn(async (spec: any) => {
    const maps = drawnMaps.make && spec?.map ? [drawnMaps.make()] : [];
    if (maps.length > 0) grammar.maps = maps;
    grammarRuns.push({
      targets,
      spec,
      pick: (selection) => handlers['map:picking']?.({ selection }),
      brush: (selection) => handlers['plot:selection']?.({ selection }),
      highlights,
      maps,
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

/** What an artifact of the input reads, by its path; any other path reads `nodeInput`. */
export const inputsByPath: { current: Record<string, any> } = { current: {} };

/** The dataflow's scenarios, as the flow holds them: none unless a test sets some. */
export const flowScenarios: { current: any[] } = { current: [] };

/** The dataflow's nodes and edges, as the flow holds them: none unless a test sets some. */
export const flowNodes: { current: any[] } = { current: [] };
export const flowEdges: { current: any[] } = { current: [] };

export const flowProviderModule = {
  useFlowContext: () => ({
    nodes: flowNodes.current, edges: flowEdges.current, nodeExecStatus: {}, markNodeErrored,
    workflowNameRef: { current: 'wf' }, scenarios: flowScenarios.current,
  }),
};
export const toastProviderModule = { useToastContext: () => ({ showToast }) };
export const apiModule = {
  fetchData: jest.fn(async (path?: string) => (
    (path !== undefined && inputsByPath.current[path]) || { dataType: 'geodataframe', data: nodeInput.current }
  )),
  fetchPreviewData: jest.fn(),
};
export const autkGrammarModule = { AutkGrammar };

/** Forget the runs and calls of the last test, read ONE_ROW again, and hold no
 * scenario, node or edge. */
export function resetAutkNodeMocks(): void {
  grammarRuns.length = 0;
  drawnMaps.make = null;
  AutkGrammar.mockClear();
  markNodeErrored.mockClear();
  showToast.mockClear();
  nodeInput.current = ONE_ROW;
  inputsByPath.current = {};
  flowScenarios.current = [];
  flowNodes.current = [];
  flowEdges.current = [];
}
