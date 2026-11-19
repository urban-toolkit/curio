/**
 * What a suite that mounts an Autark node (_support/autkNode) mocks the node's
 * modules with: the flow, the toasts, the input it fetches, and a stand-in
 * grammar that records what the node hands it and reports picks and brushes
 * as autk-grammar does. Free of app imports, so a `jest.mock` factory can
 * require it:
 *
 *     jest.mock("<src>/providers/FlowProvider", () => require("<this file>").flowProviderModule);
 */
import { arrangeViews } from './autkArrangeViews';

/** One run of the stand-in grammar. */
export type GrammarRun = {
  targets: Record<string, unknown>;
  spec: any;
  /** A pick on the map, as autk-grammar reports one: drawn positions. */
  pick: (selection: number[]) => void;
  /** A brush on the plot, as autk-grammar reports one: positions in the plot's table. */
  brush: (selection: number[]) => void;
  /** A pick as autk-grammar 5.0.0 reports one: on the map *mapId* names, on its layer *layerId*, drawn positions. */
  pickOn: (mapId: string | number, layerId: string, selection: number[]) => void;
  /** A brush as autk-grammar 5.0.0 reports one: on the plot *plotId* names (its `id`, else its `dataRef`). */
  brushOn: (plotId: string, selection: number[]) => void;
  /** Each highlight the node asked of this run's map, in order: the table and the positions lit up (none: cleared). */
  highlights: Array<[string, number[]]>;
  /** The map each of `highlights` named, by autk-grammar's `mapId` (none: every map that draws the table). */
  highlightMaps: Array<string | number | undefined>;
  /** Each selection the node asked of this run's plot, in order: the plot and its positions (none: cleared). */
  plotSelections: Array<[string, number[]]>;
  /** The maps this run drew, made by `drawnMaps.make` when a test sets it. */
  maps: any[];
  /**
   * What ends the DuckDB worker of the database this run made, as autk-grammar
   * keeps it (its engine's context, an AutkDb holding DuckDB-Wasm's database).
   */
  terminate: jest.Mock;
  /** The grammar's `destroy()`, which ends its maps and lets go of its engine, as autk-grammar 5's does. */
  destroy: jest.Mock;
};

/** Every run of the stand-in grammar, in order. */
export const grammarRuns: GrammarRun[] = [];

/** What makes the map a run draws, for a test that reads its camera; none unless a test sets it. */
export const drawnMaps: { make: null | (() => any) } = { make: null };

/**
 * What a run waits for once it made its maps, for a test that holds a draw
 * under way: the node has its maps only when the run ends. None unless a test
 * sets it.
 */
export const heldDraws: { until: Promise<void> | null } = { until: null };

/**
 * What autk-db exports of each table the node hands a run, from the features
 * handed, as `grammar.data` holds it: a test that sets it makes autk-db leave
 * rows out or keep them in an order of its own. None unless a test sets it.
 * As autk-grammar's, `grammar.data` lists the tables of the default workspace
 * alone; the run's database (`grammarEngine.context`) exports a table of any
 * workspace, in the workspace it works in.
 */
export const drawnExports: { of: null | ((table: string, handed: any[]) => any[]) } = { of: null };

/** autk-grammar's `enterWorkspace`, as its data entry has it: autk-db's default workspace is `autk`. */
export async function enterWorkspace(db: any, workspace?: string): Promise<void> {
  const name = workspace ?? 'autk';
  if (db.getCurrentWorkspace() !== name) await db.setWorkspace(name);
}

/** The workspace a source of a run's document loads into. */
const workspaceOf = (source: any): string =>
  typeof source?.workspace === 'string' && source.workspace ? source.workspace : 'autk';

/** What a run fails with once it made its database, for a test of a failed draw; none unless a test sets it. */
export const failedDraws: { error: Error | null } = { error: null };

/**
 * Whether a run hands each pass of its spec's `compute` to the grammar's
 * compute adapter, in order, before it draws, each pass on the context the
 * last one returned, as autk-grammar's engine does: not unless a test sets
 * it. The stand-in adapter runs none of them, unless a test gives the grammar
 * an adapter of its own (`adapter`, made as each grammar is, such as
 * autk-grammar's `createComputeAdapter`, handed the cache of the grammar's
 * data adapter, `sources`, as autk-grammar 5.2.0 makes its own); a node that
 * wraps the adapter runs its wrapper. A run whose database exports its tables
 * (`drawnExports`) has that database before its passes run, and puts each
 * GeoJSON source of its spec in `sources` through the grammar's own data
 * adapter (`createDataAdapter`, the build the app bundles), as its run loads
 * one, so a pass reads a `fromFeature` table as the source gave it.
 */
export const grammarComputes: { on: boolean; adapter: null | ((sources: Map<string, any>) => any) } = {
  on: false, adapter: null,
};

/**
 * Put each GeoJSON source of *spec* in *sources*, the cache of the grammar's
 * data adapter, through the grammar's own `createDataAdapter`, on *context*,
 * a database that exports its tables (`drawnExports`); nothing when the
 * grammar module offers no data adapter.
 */
async function handedToTheDataAdapter(sources: Map<string, any>, spec: any, context: any): Promise<void> {
  const { createDataAdapter } = jest.requireMock('@urban-toolkit/autk-grammar') as { createDataAdapter?: any };
  if (typeof createDataAdapter !== 'function') return;
  const adapter = createDataAdapter(undefined, sources);
  for (const source of Array.isArray(spec?.data) ? spec.data : []) {
    if (source?.type === 'geojson' && Array.isArray(source.geojsonObject?.features)) await adapter.resolveSource(context, source);
  }
  await context.setWorkspace('autk');
}

export const AutkGrammar = jest.fn().mockImplementation((targets: Record<string, unknown>) => {
  const handlers: Record<string, (event: any) => void> = {};
  const highlights: Array<[string, number[]]> = [];
  const highlightMaps: Array<string | number | undefined> = [];
  const plotSelections: Array<[string, number[]]> = [];
  // The cache of the grammar's data adapter, which its compute adapter reads.
  const grammarSources = new Map<string, any>();
  const grammar: any = {
    data: {},
    interactions: {
      on: (event: string, handler: (event: any) => void) => {
        handlers[event] = handler;
        return () => { delete handlers[event]; };
      },
    },
    highlightOnMap: jest.fn((table: string, positions: number[], mapId?: string | number) => {
      highlights.push([table, [...positions]]);
      highlightMaps.push(mapId);
    }),
    clearHighlightOnMap: jest.fn((table: string, mapId?: string | number) => {
      highlights.push([table, []]);
      highlightMaps.push(mapId);
    }),
    setPlotSelection: jest.fn((plot: string, positions: number[]) => { plotSelections.push([plot, [...positions]]); }),
    clearHighlightOnPlot: jest.fn((plot: string) => { plotSelections.push([plot, []]); }),
    // Where autk-grammar keeps the adapter its run hands each compute pass to.
    computeAdapter: grammarComputes.adapter
      ? grammarComputes.adapter(grammarSources)
      : { resolveCompute: jest.fn(async (context: unknown) => context) },
  };
  // autk-grammar 5's destroy() lets go of its engine, and with it the database.
  const destroy = jest.fn(() => { grammar.grammarEngine = undefined; });
  grammar.destroy = destroy;
  grammar.run = jest.fn(async (spec: any) => {
    // The database the run reads, where autk-grammar keeps it.
    const terminate = jest.fn(async () => undefined);
    grammar.grammarEngine = { context: { db: { terminate } } };
    if (failedDraws.error) {
      grammarRuns.push({
        targets, spec, pick: () => {}, brush: () => {}, pickOn: () => {}, brushOn: () => {},
        highlights, highlightMaps, plotSelections, maps: [], terminate, destroy,
      });
      throw failedDraws.error;
    }
    const exportOf = drawnExports.of;
    if (exportOf) {
      const sources: any[] = (Array.isArray(spec?.data) ? spec.data : [])
        .filter((source: any) => Array.isArray(source?.geojsonObject?.features));
      const exported = (source: any) =>
        Promise.resolve({ type: 'FeatureCollection', features: exportOf(source.outputTableName, source.geojsonObject.features) });
      grammar.data = Object.fromEntries(sources
        .filter((source) => workspaceOf(source) === 'autk')
        .map((source) => [source.outputTableName, exported(source)]));
      // A table a pass writes, under its outputTableName or in place, is what
      // the pass computed over the table it read, as autk-grammar's compute
      // cache keeps it: every feature of that table's export, listed under its
      // key (the name in the default workspace, `<workspace>/<name>` in another).
      const keyOf = (workspace: string, name: string) => (workspace === 'autk' ? name : `${workspace}/${name}`);
      for (const pass of Array.isArray(spec?.compute) ? spec.compute : []) {
        const workspace = workspaceOf(pass);
        const source = sources.find((s) => s.outputTableName === pass?.dataRef && workspaceOf(s) === workspace);
        const read = grammar.data[keyOf(workspace, pass?.dataRef)] ?? (source ? exported(source) : undefined);
        if (read) grammar.data[keyOf(workspace, pass.outputTableName ?? pass.dataRef)] = read;
      }
      // The run's database, left in the default workspace, as autk-grammar leaves it.
      const context = grammar.grammarEngine.context;
      context.workspace = 'autk';
      context.getCurrentWorkspace = () => context.workspace;
      context.setWorkspace = async (name: string) => { context.workspace = name; };
      // autk-db's CRS, and a load whose table the export above stands for.
      context.getWorkspaceConfiguration = () => ({ coordinateFormat: 'EPSG:3395', precisionGrid: 0.01 });
      context.loadGeojson = async () => undefined;
      context.getLayer = async (name: string) => {
        const source = sources.find((s) => s.outputTableName === name && workspaceOf(s) === context.workspace);
        if (!source) throw new Error(`Table ${name} not found.`);
        return exported(source);
      };
    }
    if (grammarComputes.on) {
      let context = grammar.grammarEngine.context;
      if (exportOf) await handedToTheDataAdapter(grammarSources, spec, context);
      for (const pass of Array.isArray(spec?.compute) ? spec.compute : []) {
        context = await grammar.computeAdapter.resolveCompute(context, pass);
      }
      grammar.grammarEngine.context = context;
    }
    const maps = drawnMaps.make && spec?.map ? [drawnMaps.make()] : [];
    if (maps.length > 0) grammar.maps = maps;
    grammarRuns.push({
      targets,
      spec,
      pick: (selection) => handlers['map:picking']?.({ selection }),
      brush: (selection) => handlers['plot:selection']?.({ selection }),
      pickOn: (mapId, layerId, selection) => handlers['map:picking']?.({ mapId, layerId, selection }),
      brushOn: (plotId, selection) => handlers['plot:selection']?.({ plotId, event: 'brush', selection }),
      highlights,
      highlightMaps,
      plotSelections,
      maps,
      terminate,
      destroy,
    });
    if (heldDraws.until) await heldDraws.until;
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
export const toastProviderModule = {
  useToastContext: () => ({ showToast }),
  useOptionalToastContext: () => ({ showToast }),
};
export const apiModule = {
  fetchData: jest.fn(async (path?: string) => (
    (path !== undefined && inputsByPath.current[path]) || { dataType: 'geodataframe', data: nodeInput.current }
  )),
  fetchPreviewData: jest.fn(),
};
export const autkGrammarModule = { AutkGrammar, arrangeViews, enterWorkspace };

/** Forget the runs and calls of the last test, read ONE_ROW again, and hold no
 * scenario, node or edge. */
export function resetAutkNodeMocks(): void {
  grammarRuns.length = 0;
  drawnMaps.make = null;
  heldDraws.until = null;
  drawnExports.of = null;
  failedDraws.error = null;
  grammarComputes.on = false;
  grammarComputes.adapter = null;
  AutkGrammar.mockClear();
  markNodeErrored.mockClear();
  showToast.mockClear();
  nodeInput.current = ONE_ROW;
  inputsByPath.current = {};
  flowScenarios.current = [];
  flowNodes.current = [];
  flowEdges.current = [];
}
