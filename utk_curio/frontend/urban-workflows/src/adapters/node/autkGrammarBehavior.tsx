import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import type { HandleDef, NodeBehaviorData, NodeBehaviorResult, UseNodeStateReturn } from '../../registry/types';
import type { NodeOutput } from '../../hook/useNodeState';
import { detectWebGpuSupport, reprobeWebGpuSupport } from '../../utils/webgpuSupport';
import { useToastContext } from '../../providers/ToastProvider';
import { VisInteractionType, NodeType } from '../../constants';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { useStarterSpec } from '../../hook/useStarterSpec';
import { opensWithPackageStarter } from '../../registry/packageStarter';
import { autkStarterText } from '../../utils/autkDefaultSpec';
import { useFlowContext } from '../../providers/FlowProvider';
import { useProvenanceContext } from '../../providers/ProvenanceProvider';
import { formatDate, mapTypes } from '../../utils/formatters';
import { resolveGrammarEmptyReason, type NodeEmptyReason } from '../../utils/nodeEmptyState';
import { clearEmptyState, writeEmptyState } from '../../utils/writeEmptyState';
import { isEmptySpecBuffer } from '../../utils/starterSpec';
import { backendUrl } from '../../utils/backendUrl';
import { RenderCounts, emptyRenderKind, partialRenderNote, renderOutcome } from '../../utils/renderOutcome';
import { detectCoordinateFormat } from '../../utils/geoCrs';
import { snapSourceToGrid } from '../../utils/geoPrecision';
import { fitPlotToPane } from '../../utils/autkPlotSizing';
import { UNREPORTED_MESSAGE, describeError, runAndAlwaysSettle } from './autkRunSettlement';
import { withExtensionRetry } from './duckdbExtensionRetry';
import { closeGrammarDb } from './autkDbClose';
import { AutkSpecKind, classifyAutkSpec, classifyAutkSpecString } from '../../utils/autkSpecKind';
import { autkKeyProblem, autkRasterPassProblem, autkViewProblem } from '../../contracts/autkGrammar';
import {
    autkNeedsInput, autkReadsInput, autkSourcesFrom, documentTableRefs, drawnFeatures, drawnRows, heightUses, heightsAtUse, inputRow, keyValues,
    loadableSource, ownTableNames, passesAtHand, readAutkInput, selectFieldsOf, selectFieldsProblem, tableKeyOf, tablePositions, tablesToLoad,
    withReadableHeights, writtenTables,
    type LoadOrder,
    type PreparedAutkInput,
} from '../../utils/autkInput';
import { type GrammarInput } from '../../utils/grammarInput';
import { featureRows, matchSelections, type IncomingSelection } from '../../utils/selectionMatch';
import { EDIT_SELECTION, type SentSelection } from '../../utils/editFeatures/mapEditSelection';
import { AUTK_SELECTION, autkSelectionKey, byAutkLayer, type AutkSelect } from '../../utils/autkSelects';
import { provideViewRows } from '../../utils/references/viewSelections';
import { withChipPlaceholders } from '../../utils/references/codeReferences';
import { selectionEchoSource } from '../../utils/selectionEcho';
import {
    SANDBOX_BACKEND_URL_TOKEN,
    autkTableKey,
    autkUsesWorkspaces,
    autkWorkspaceOf,
    compileDataSpecToAutkDbJs,
    osmElementTables,
    requestedLayerTables,
    resolveDataSourceUrls as resolveDataSourceUrlsWithBase,
    sectionChangedTables,
    sectionInputTables,
    sectionTablesHandedOn,
} from './autkDataCompile';
import { executionInputRef } from '../../utils/flowOutputRef';
import { attachMapInteractionZoomFix } from './autkMapZoom';
import { attachMapPressGuard } from './autkMapPressGuard';
import {
    countedItem, describeAutkRun, emptyStateWords, featureCount, hasFeatures, totalCount,
} from './autkRunDescriptions';
import {
    RASTER_TABLE, loadSpecLayers, loadedRows, materializeBackendLayers, runDataInBackend, toPoolOutput,
    type AutkLayer,
} from './autkLayerMaterialize';
import {
    bleedRasterEdges, isCurioRasterSource, newAutkDb, rasterSourceOf, resolveRasterInputs, withLayersOverRasters,
    withOpaqueRasters, withRasterSources, type CurioRasterSource,
} from './autkRasters';
import { applyComputeBlocks } from './autkComputeBlocks';
import { withCheckedPasses } from './autkComputeScopes';
import { attachSpecCameras, frameMaps, keepMapViews, mapViews, showFramedViews, type MapView } from './autkMapView';
import { destroyFailedGrammar, grammarMaps, trackMaps } from './autkMapDrawing';
import {
    layOutPanes, lightViews, linksAtHand, mapEntries, mapIndexOf, mapLayerRefs, pickLayerOf, plotEntries, plotEntryOf, plotKey,
    receivedByView, viewTargets, workspaceOfLayer, type DrawnView, type LaidOutViews, type LitView, type ViewPanes,
} from './autkViews';
import { viewDots } from './handleHelpers';
import { documentViews, viewDotIds } from '../../utils/autkDocumentViews';
import { interactionHandleView, isInteractionEdge } from '../../contracts/interactionEdges';
import type { ViewArrangement } from '@urban-toolkit/autk-grammar';
import { mapSession, onMapSession, registerEditMap } from '../../utils/editFeatures/mapEditBus';
import {
    drawnFeatureAt, featurePositions, handedFeaturesOf, layerIdFor, mapDrawingOf, mapLayerOf, mapStateOf, pickOn,
    restoreMapLayers, showForEdits, snapshotBeforeSolo, snapshotMapLayers, type DrawnTables, type EditsView,
    type HandedFeature, type MapDrawing, type MapLayerState, type MapTableState,
} from './autkMapState';
import {
    drawnInput, editFeedsOf, editedMapView, fedByInteraction, feedsVersion, newLayerTables, type EditFeed,
} from '../../utils/editFeatures/mapEditsPreview';
import { codeEditRevision, subscribeToCodeEdits } from '../../utils/references/codeEdits';
import MapEditOverlay from '../../components/editFeatures/MapEditOverlay';

/** What a map no Map Editor node feeds listens to for code edits: nothing. */
const NO_CODE_EDITS = () => () => {};
const NO_REVISION = () => 0;

/**
 * What each Autark node's map draws and lights now, and where the camera of
 * each map it drew stands, by node id (autkMapState `mapStateOf`,
 * `drawnFeatureAt`; autkMapView `mapViews`).
 */
const mapStateReaders = new Map<string, {
    state: (view?: string | number) => Promise<Record<string, MapTableState> | null>;
    featureAt: (table: string, position: number, view?: string | number) => Promise<Record<string, unknown> | null>;
    views: () => Array<MapView | null>;
    showFramed: () => () => void;
    drawing: (view?: string | number) => MapDrawing | null;
    tourEnded: (view?: string | number) => Promise<boolean>;
    handed: (table: string, view?: string | number) => Promise<HandedFeature[] | null>;
}>();
/** What turns each node's maps back by their cameras, while they show their framed views. */
const turnBack = new Map<string, () => void>();
// The e2e tests read what a map draws and lights through them
// (test_frontend/test_autark_positions_e2e.py), and its camera
// (test_frontend/test_autark_camera_e2e.py); the map framing check (#773)
// shows a map its camera turns at its framed view, then turns it back
// (test_frontend/utils/node_drawings.py, autark_map_framing).
if (typeof window !== 'undefined') {
    // A map of a node of several is named by *view*: its key, the map's `id`,
    // else its index (autkViews `mapIndexOf`); without one, the first map.
    (window as any).__curio_mapState = (nodeId: string, view?: string | number) =>
        mapStateReaders.get(nodeId)?.state(view) ?? null;
    (window as any).__curio_mapFeatureAt = (nodeId: string, table: string, position: number, view?: string | number) =>
        mapStateReaders.get(nodeId)?.featureAt(table, position, view) ?? null;
    (window as any).__curio_mapViews = (nodeId: string) => mapStateReaders.get(nodeId)?.views() ?? null;
    // What a map draws of the keys of its map and its layers (autkMapState
    // `mapDrawingOf`), and, once its camera tour ends, true: false when it
    // plays none (test_frontend/test_autark_map_keys_e2e.py).
    (window as any).__curio_mapDrawing = (nodeId: string, view?: string | number) =>
        mapStateReaders.get(nodeId)?.drawing(view) ?? null;
    (window as any).__curio_mapTourEnded = (nodeId: string, view?: string | number) =>
        mapStateReaders.get(nodeId)?.tourEnded(view) ?? Promise.resolve(false);
    // The features of a table the grammar handed its map's autk-map, each
    // with its input row and the keys of a building's top it holds
    // (autkMapState `handedFeaturesOf`;
    // test_frontend/test_autark_buildings_zero_height_e2e.py).
    (window as any).__curio_mapHanded = (nodeId: string, table: string, view?: string | number) =>
        mapStateReaders.get(nodeId)?.handed(table, view) ?? Promise.resolve(null);
    (window as any).__curio_showMapsFramed = (nodeId: string, framed: boolean): boolean => {
        turnBack.get(nodeId)?.();
        turnBack.delete(nodeId);
        const reader = mapStateReaders.get(nodeId);
        if (!reader) return false;
        if (framed) turnBack.set(nodeId, reader.showFramed());
        return true;
    };
}

/**
 * The key the select of *view* (none: the node's first map, where a Map
 * Editor node picks) is sent under: `autk_selection` for a node of one view,
 * else the view's own, by its `id`, else by its place among the views of
 * *panes*, the panes of the document the grammar drew (utils/autkSelects,
 * which keeps the two forms apart).
 */
function selectionKeyOf(panes: ViewPanes | null, view: Pick<DrawnView, 'kind' | 'index'> | null | undefined): string {
    const all = panes ?? [];
    if (all.length <= 1) return AUTK_SELECTION;
    const where = view ?? { kind: 'map' as const, index: 0 };
    const at = Math.max(all.findIndex((pane) => pane.kind === where.kind && pane.index === where.index), 0);
    const id = all[at].id;
    return autkSelectionKey(typeof id === 'string' && id !== '' ? id : at);
}

/** Whether *select* holds a selection: a pick or a brush of rows, or of key values. */
function holdsSelection(select: AutkSelect | undefined): boolean {
    return Array.isArray(select?.data) && select!.data.length > 0;
}

/**
 * The layer a document's selections come from when they name none: its map's
 * pickable layer (or its first), else its plot's. The same layers a pick and a
 * plot brush report below.
 */
function selectionLayerOf(spec: any): string | undefined {
    for (const map of mapEntries(spec)) {
        const layer = pickLayerOf(map);
        if (typeof layer === 'string') return layer;
    }
    return plotEntries(spec).find((p) => typeof p?.dataRef === 'string')?.dataRef;
}

export type AutkBehaviorOptions = {
    /**
     * Whether a failed run marks the node errored, as an Autark node's does, so
     * the nodes it feeds say so. A Map Editor node draws its input through this
     * map: a map that cannot draw says so in its body, and the node's run
     * stands as it ran.
     */
    marksNodeErrored?: boolean;
    /**
     * Whether each run is listed among the node's runs in the provenance drawer, as every node
     * lists its own (#860). The Map Editor node's map draws under that node's
     * id, and a draw of it is not a run of that node, as a chart's redraw for a
     * recolored scenario box is not (useVega's `recordsProvenance`).
     */
    recordsProvenance?: boolean;
    /**
     * Whether a draw keeps the view of the maps the last draw made. Only the
     * first draw frames the layers and turns them by the document's camera
     * (`frameMaps`); each later one puts back the camera the person zoomed
     * and panned to (`keepMapViews`), unless the map's camera in the document
     * changed, which frames and turns it again. A map a Map Editor node feeds
     * always does, so an edit, and the Commit after it, leave the map where
     * it was.
     */
    keepsView?: boolean;
};

export const useAutkGrammarBehavior = (
    data: NodeBehaviorData,
    nodeState: UseNodeStateReturn,
    { marksNodeErrored = true, recordsProvenance = true, keepsView = false }: AutkBehaviorOptions = {},
): NodeBehaviorResult => {
    const toasts = useToastContext();
    const wrapperRef = useRef<HTMLDivElement>(null);
    // Set when the browser cannot run Autark at all (#201). Renders an
    // in-node explanation instead of the map container, so the node says why
    // it is empty rather than looking like it simply produced nothing.
    const [gpuBlocked, setGpuBlocked] = useState<string | null>(null);
    // The fallback panel's "Check again" is re-probing (#272).
    const [gpuChecking, setGpuChecking] = useState(false);
    // The last spec handed to applyGrammar, so "Check again" can re-run it the
    // moment WebGPU answers instead of asking the user to press play again.
    const lastSpecRef = useRef<string | null>(null);
    // What kind of step this spec is, so the body can say so. A data-only or
    // compute-only node has no map/plot to draw, and used to render a blank
    // box under a green "Done" chip - indistinguishable from a node that
    // never ran or silently failed (#282). Seeded from the authored spec so the
    // pre-run body already says what running it will do; updated on every run.
    const [specKind, setSpecKind] = useState<AutkSpecKind>(() =>
        classifyAutkSpecString((data as any).code || data.defaultCode),
    );
    // One line per table/layer the last successful run produced. Null while
    // running and after an error, so a stale summary never outlives its data.
    const [runSummary, setRunSummary] = useState<string | null>(null);

    // Grammar instance and last-run spec, kept in refs so effects can access
    // them without causing re-renders.
    const grammarRef = useRef<any>(null);
    const specRef    = useRef<any>(null);
    // The panes of the views of the document the grammar ran, as its
    // arrangeViews places them, which give each view the key the grammar
    // knows it by (autkViews `mapKey`, `plotKey`).
    const panesRef   = useRef<ViewPanes | null>(null);
    // The rows of panes the last run arranged its views in: a notebook cell
    // gives each row a map's height (utils/notebookLayout).
    const [viewRows, setViewRows] = useState(1);
    // Unsubscribe functions returned by grammar.interactions.on(); cleared and
    // re-populated on every applyGrammar call and on unmount.
    const interactionOffRef = useRef<Array<() => void>>([]);
    // The select each view of the last draw sent, by the key it is sent
    // under (utils/autkSelects): `autk_selection` for a node of one view, one
    // per view for a node of several, as a Vega-Lite chart keeps one per
    // param. Kept until the node is drawn again, which empties those that
    // held a selection.
    const heldSelectsRef = useRef<Map<string, AutkSelect>>(new Map());
    // Disposer for the map canvas's window-bound pointer listeners (the
    // interaction zoom fix and the press guard), cleared and re-populated on
    // each applyGrammar run with a map, and on unmount.
    const pickFixCleanupRef = useRef<(() => void) | null>(null);
    // Destroys the last run's maps (adapters/node/autkMapDrawing) and ends its
    // database (autkDbClose): when the next run removes their canvas, and when
    // the node leaves the page.
    const destroyMapsRef = useRef<(() => void) | null>(null);
    const destroyLastMaps = () => {
        destroyMapsRef.current?.();
        destroyMapsRef.current = null;
    };
    // With keepsView: the view of the maps the last draw made, taken before
    // they are destroyed, which the next draw puts back.
    const keptViewsRef = useRef<Array<MapView | null> | null>(null);
    // Whether the node is on the page. It turns false in the commit that takes
    // the node off the page (the layout effect below), the moment its canvas
    // goes, so a run that goes on in that same moment already reads it.
    //
    // A node that leaves while its run is under way (File > New dataflow, a
    // deleted node) drops the run. The run makes no grammar after that, and
    // nothing it says reaches the page: no toast, no output, no rows handed
    // on. autk-grammar's own run cannot be stopped, so one already under way
    // goes on. Its map then finds no canvas, and that failure is dropped too,
    // or it draws on the canvas that left, and that map is destroyed at once.
    const mountedRef = useRef(true);
    const leftPage = () => !mountedRef.current;
    // What a run tells the person, while its node is on the page.
    const showToast: typeof toasts.showToast = (...args) => {
        if (!leftPage()) toasts.showToast(...args);
    };
    // What a run hands to the nodes this one feeds, while it is on the page.
    const handOn = (output: unknown) => {
        if (!leftPage()) data.outputCallback?.(data.nodeId, output);
    };
    // The toast is transient and the node UI has no error tab, so a failure
    // also goes to the console, the only durable place tooling (and the e2e
    // browser-log dump) can read it from. A dropped run's is no node error.
    const logFailure = (message: string) => {
        if (leftPage()) console.info('[autk-grammar] dropped the run of a node that left the page:', message);
        else console.error('[autk-grammar] node error:', message);
    };
    // Always-current ref to data so grammar event callbacks never close over a
    // stale data object (grammar subscriptions outlive individual renders).
    const dataRef = useRef(data);
    useEffect(() => { dataRef.current = data; });
    // The node's own selection, sent as its view's: a pick or a brush of
    // autk-map's or autk-plot's, in the view that made it, or a pick a Map
    // Editor node's overlay makes on the node's first map. A node of one
    // view sends it under `autk_selection`; a node of several sends every
    // view's select it holds, as a Vega-Lite chart sends its params, each
    // under its view's key, the one made now at priority 1 and the others at
    // 0, oldest first (utils/autkSelects). Each is kept, so a draw that is
    // not an edit's says each selection is gone (below).
    // The sync whose rows light: the last asked, which reads the newest selections.
    const syncTurnRef = useRef(0);
    // What the node last asked a grammar to light on each view, by the view's
    // key (autkViews `lightViews`), for the grammar it asked.
    const litRef = useRef<{ grammar: any; lit: Map<string, string> }>({ grammar: null, lit: new Map() });
    const sendOwnSelection = useCallback((selection: SentSelection, view?: Pick<DrawnView, 'kind' | 'index'>) => {
        // autk-map lights a pick on the map that made it, and the grammar's
        // links carry a pick or a brush on to the views they join: what the
        // views light is no longer what the node last asked, so the next
        // selection it receives lights every view again.
        litRef.current = { grammar: null, lit: new Map() };
        const detail = selection[EDIT_SELECTION];
        const key = selectionKeyOf(panesRef.current, view);
        const held = heldSelectsRef.current;
        held.delete(key);
        if (detail) held.set(key, detail);
        const details = key === AUTK_SELECTION
            ? selection
            : Object.fromEntries([...held].map(([k, select]) => [k, { ...select, priority: k === key ? 1 : 0 }]));
        const d = dataRef.current;
        d.interactionsCallback?.(details, d.nodeId);
    }, []);
    // The document as written, its chips unresolved: what a run's record
    // holds, since the provenance drawer puts a run's code back in the editor.
    // Read as a run starts, so a run queued behind another reads its own.
    const writtenRef = useRef('');
    writtenRef.current = String((isEmptySpecBuffer(nodeState.code) ? data.defaultCode : nodeState.code) ?? '');

    // Memoizes the backend data load (a DuckDB artifact reference) keyed on the
    // authored data sources + upstream identity, so re-running the grammar after
    // an unrelated edit (e.g. tweaking map colors) does not re-load OSM/PBF in
    // the backend. The cached DuckDB artifact stays valid until the data section
    // or the upstream input changes.
    const dataCacheRef = useRef<{ key: string; ref: { path: string; dataType: string } } | null>(null);

    // The input, read once per input object and shared by the render path,
    // the compute path and the highlight sync (utils/autkInput).
    const inputReadRef = useRef<{ input: unknown; read: Promise<GrammarInput> } | null>(null);
    const readInput = (input: unknown): Promise<GrammarInput> => {
        if (inputReadRef.current?.input !== input) {
            const read = readAutkInput(input);
            inputReadRef.current = { input, read };
            // A failed read is not kept: the next run tries again.
            read.catch(() => {
                if (inputReadRef.current?.read === read) inputReadRef.current = null;
            });
        }
        return inputReadRef.current!.read;
    };
    // The inputs of the Map Editor nodes that feed the map, each read once
    // per input object, as the map's own is.
    const fedReadsRef = useRef(new Map<unknown, Promise<GrammarInput>>());
    const readFed = (input: unknown): Promise<GrammarInput> => {
        const reads = fedReadsRef.current;
        if (!reads.has(input)) {
            const read = readAutkInput(input);
            reads.set(input, read);
            read.catch(() => {
                if (reads.get(input) === read) reads.delete(input);
            });
        }
        return reads.get(input)!;
    };
    // How each loaded input table's positions map to the input's rows
    // (loadableSource), by key (tableKeyOf): a pick or a highlight goes
    // through it, so a position always names the row the Data Pool and the
    // other charts mean.
    const loadOrdersRef = useRef<Record<string, LoadOrder>>({});
    // Each input table's features as they came, by key: the rows a pick or a
    // brush reads the key columns of, when its view names them (selectFields).
    const inputFeaturesRef = useRef<Record<string, readonly any[]>>({});
    // What the last draw's maps were handed of each table, as autk-db exported
    // it, which can leave rows out and keep the others in an order of its own,
    // and the input row each position of its layer stands for (`drawnRows`):
    // read back the first time a pick or a highlight on that layer needs it,
    // by key. `tagged` holds the keys of the tables whose features carry their
    // input row. `reads` is the last read of the run's database, and
    // `enterWorkspace` autk-grammar's, which a read of a table in another
    // workspace than the default one enters it with.
    const drawnRef = useRef<{
        grammar: unknown;
        tagged: ReadonlySet<string>;
        features: Map<string, Promise<any[] | null>>;
        rows: Map<string, Promise<number[] | null>>;
        reads: Promise<unknown>;
        enterWorkspace?: (db: any, workspace?: string) => Promise<void>;
    } | null>(null);
    // A table's rows as autk-db exports them, which a map drew, or null when
    // they cannot be read. autk-grammar's `data` lists the tables of the
    // default workspace, and each a pass computed, under its key; a table of
    // another workspace is read from the run's database in that workspace.
    // The reads go one at a time, and one in another workspace puts the
    // database back in the default one, where `data` reads.
    const exportedTable = (grammar: any, workspace: string | undefined, table: string): Promise<any> | null => {
        const drawn = drawnRef.current;
        const exports = grammar?.data;
        if (!drawn || drawn.grammar !== grammar || !exports || typeof exports !== 'object') return null;
        const key = autkTableKey(workspace, table);
        const db = grammar?.grammarEngine?.context;
        const enter = drawn.enterWorkspace;
        let read: () => Promise<any>;
        if (key in exports) read = () => Promise.resolve(exports[key]);
        else if (workspace !== undefined && typeof db?.getLayer === 'function' && typeof enter === 'function') {
            read = async () => {
                await enter(db, workspace);
                try {
                    return await db.getLayer(table);
                } finally {
                    await enter(db);
                }
            };
        } else return null;
        const next = drawn.reads.then(read, read);
        drawn.reads = next.catch(() => undefined);
        return next;
    };
    const drawnFeaturesOf = (grammar: any, workspace: string | undefined, table: string): Promise<any[] | null> | null => {
        const drawn = drawnRef.current;
        const key = autkTableKey(workspace, table);
        // Each read of a table exports it again: once per draw.
        if (drawn && drawn.grammar === grammar && !drawn.features.has(key)) {
            const exported = exportedTable(grammar, workspace, table);
            if (!exported) return null;
            drawn.features.set(key, exported.then(drawnFeatures, () => null));
        }
        return drawn && drawn.grammar === grammar ? drawn.features.get(key) ?? null : null;
    };
    // Null for a table whose order is known without it: one a document loads
    // itself, or none of this draw's maps drew.
    // Each table a pass of the last draw wrote from the input's, by key
    // (tableKeyOf): the input table whose rows it holds (writtenTables), by
    // name, followed through passes that write from one another, in the
    // pass's workspace. A pick on it names that table's rows, and a selection
    // of them lights it.
    const writtenFromRef = useRef<Record<string, string>>({});
    // The input table whose rows *table*, a table of *workspace*, holds, by
    // name: a pass's root is a table of the pass's own workspace.
    const rowsTableOf = (table: string | undefined, workspace?: string): string | undefined => {
        const root = table === undefined ? undefined : writtenFromRef.current[autkTableKey(workspace, table)];
        if (!root) return table;
        return workspace !== undefined && root.startsWith(`${workspace}/`) ? root.slice(workspace.length + 1) : root;
    };
    // The positions are those the layer of *table* drew on the map of index
    // *mapIndex* (autkViews), else on the last map that draws it.
    const drawnRowsOf = (
        grammar: any, workspace: string | undefined, table: string, mapIndex?: number,
    ): Promise<number[] | null> | null => {
        const drawn = drawnRef.current;
        const key = autkTableKey(workspace, table);
        const features = drawn?.tagged.has(key) ? drawnFeaturesOf(grammar, workspace, table) : null;
        if (!drawn || !features) return null;
        const rowsKey = mapIndex === undefined ? key : JSON.stringify([mapIndex, key]);
        if (!drawn.rows.has(rowsKey)) {
            drawn.rows.set(rowsKey, features.then((list) => drawnRows(list, mapLayerOf(grammar, table, mapIndex)?.components)));
        }
        return drawn.rows.get(rowsKey)!;
    };
    // The input row each row of a table a pass of this draw wrote stands for,
    // as a plot of it holds them: every feature the pass kept, in the order
    // autk-db stores them, read back from what it exported. Null for any
    // other table, whose rows a plot holds as Curio loads them.
    const writtenRowsOf = (grammar: any, table: string, workspace?: string): Promise<number[] | null> | null => {
        const drawn = drawnRef.current;
        const exports = grammar?.data;
        // autk-grammar's `data` lists a table a pass computed under its key.
        const key = autkTableKey(workspace, table);
        if (!drawn || drawn.grammar !== grammar || !writtenFromRef.current[key] || !drawn.tagged.has(key)
            || !exports || typeof exports !== 'object' || !(key in exports)) return null;
        const rowsKey = `written:${key}`;
        if (!drawn.rows.has(rowsKey)) {
            drawn.rows.set(rowsKey, Promise.resolve(exports[key]).then((fc: any) => drawnRows(fc?.features), () => null));
        }
        return drawn.rows.get(rowsKey)!;
    };

    // What the node knows about its input edge, asked the way the Vega-Lite
    // node asks (hook/useGrammarInputState).
    const { connected, upstreamErrored, upstreamRunning, upstreamStopped, upstreamDownloads } =
        useGrammarInputState(data.nodeId);
    // A fresh list each render: the notice changes with what it says.
    const downloadsSaid = upstreamDownloads.join('\n');
    // A failed node says so to the nodes it feeds, as a failed code node does.
    const { markNodeErrored, workflowNameRef, nodes: flowNodes, edges: flowEdges, dashboardOn } = useFlowContext() as {
        markNodeErrored?: (nodeId: string) => void;
        workflowNameRef?: React.MutableRefObject<string>;
        nodes?: any[];
        edges?: any[];
        dashboardOn?: boolean;
    };
    // Without WebGPU a dashboard raises no toast: a pinned map's tile says so
    // in its panel, and the tiles below a step the visitor cannot see name
    // that step (useDashboardRun). The canvas toasts, as the node is there.
    const showGpuToast = (message: string) => {
        if (!dashboardOn) showToast(message, 'error');
    };
    // The Map Editor nodes that feed this map on data edges (#662), each with
    // the edits its code holds: the map draws each one's input with its edits,
    // before Commit edits as after (utils/editFeatures/mapEditsPreview), and
    // keeps its view when it draws again. Only a map one feeds listens for
    // code edits, which a code put back or typed makes with no change of the
    // flow's state; every other map is as it was.
    const editFed = fedByInteraction(data.nodeId, flowNodes ?? [], flowEdges ?? []);
    useSyncExternalStore(editFed ? subscribeToCodeEdits : NO_CODE_EDITS, editFed ? codeEditRevision : NO_REVISION);
    const feeds = editFed ? editFeedsOf(data.nodeId, flowNodes ?? [], flowEdges ?? []) : [];
    const feedsRef = useRef<EditFeed[]>(feeds);
    feedsRef.current = feeds;
    const editFedRef = useRef(editFed);
    editFedRef.current = editFed;
    // The view a Map Editor node feeding the map edits: the one its interaction
    // edge names at this node's end (`in/out@<id>`); none, the node's first map.
    const editView = editFed ? editedMapView(data.nodeId, flowNodes ?? [], flowEdges ?? []) : null;
    const editViewRef = useRef(editView);
    editViewRef.current = editView;
    /** The index of the map the Map Editor node edits among *panes*: the map its edge names, else the first. */
    const editIndexOf = (panes: ViewPanes | null): number => Math.max(mapIndexOf(panes, editViewRef.current), 0);
    // A pick a Map Editor node's tools make on the map they lie over: the map
    // the node edits, whose select it is.
    const sendEditSelection = useCallback((selection: SentSelection) => {
        sendOwnSelection(selection, { kind: 'map', index: editIndexOf(panesRef.current) });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [sendOwnSelection]);

    // The dots of the node's views (contracts/interactionEdges `in/out@<id>`):
    // a node of several views has one per view with an `id`, beside its own,
    // in the order of their panes, read from the document as written, so an
    // edge saved on a view's dot finds it before the node runs. A document
    // that does not read, as while it is typed, keeps the dots it had. A dot
    // an edge still names stays while the edge does, though its view left the
    // document, so the edge shows and can be taken off.
    const documentDotsRef = useRef<{ dots: string[]; ids: string[] }>({ dots: [], ids: [] });
    const writtenDots = viewDotIds(writtenRef.current);
    if (writtenDots !== null) {
        documentDotsRef.current = {
            dots: writtenDots,
            ids: (documentViews(writtenRef.current) ?? []).flatMap((view) => (view.id ? [view.id] : [])),
        };
    }
    const { dots: documentDots, ids: documentIds } = documentDotsRef.current;
    const wiredDots = (flowEdges ?? []).flatMap((edge: any) => {
        if (!isInteractionEdge(edge)) return [];
        const view = edge.source === data.nodeId ? interactionHandleView(edge.sourceHandle)
            : edge.target === data.nodeId ? interactionHandleView(edge.targetHandle) : null;
        return view === null || documentDots.includes(view) ? [] : [view];
    });
    const dotIds = [...documentDots, ...wiredDots.filter((view, at) => wiredDots.indexOf(view) === at)];
    const dotsKey = JSON.stringify([dotIds, documentIds]);
    const dynamicHandles = useMemo<HandleDef[] | undefined>(() => (dotIds.length === 0 ? undefined : viewDots(
        dotIds,
        (view) => (documentIds.includes(view)
            ? `interaction · ${view}`
            : `interaction · ${view} (no view of this node has this id)`),
    )),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dotsKey]);
    // The input a draw reads: the map's own, with each fed circle drawn from
    // its node's input and edits; read once per input and edits.
    const drawnReadRef = useRef<{ input: unknown; version: string; read: Promise<GrammarInput> } | null>(null);
    const readDrawnInput = (input: unknown): Promise<GrammarInput> => {
        const current = feedsRef.current;
        if (current.length === 0) return readInput(input);
        const version = feedsVersion(current);
        if (drawnReadRef.current?.input !== input || drawnReadRef.current?.version !== version) {
            const kept = new Set(current.map((feed) => feed.input));
            for (const fed of [...fedReadsRef.current.keys()]) if (!kept.has(fed)) fedReadsRef.current.delete(fed);
            const read = readInput(input).then((own) => drawnInput(own, current, readFed));
            drawnReadRef.current = { input, version, read };
            read.catch(() => {
                if (drawnReadRef.current?.read === read) drawnReadRef.current = null;
            });
        }
        return drawnReadRef.current!.read;
    };
    // What was set on each layer through the map's menu, kept across that draw too.
    const savedLayersRef = useRef<MapLayerState | null>(null);
    // What the Map Editor node feeding the map asks of it: the table shown
    // alone, and the table an action works on; and each layer's own state
    // before it asked.
    const soloRef = useRef<(EditsView & { before: MapLayerState | null }) | null>(null);
    // Whether the document colors *table* by a value (its layer names getFnv).
    const colorMapped = (table: string): boolean => {
        const maps = specRef.current?.map ? (Array.isArray(specRef.current.map) ? specRef.current.map : [specRef.current.map]) : [];
        return maps.some((m: any) => (m?.layerRefs ?? []).some((lr: any) => lr?.dataRef === table && !!lr?.getFnv));
    };
    // *map*, drawn from *spec*, as that node asks now, after what it asked
    // before (*was*), by tables: by the ids its layers go by (autkMapState
    // showForEdits).
    const showAsEditsAsk = (map: any, spec: any, was: EditsView | null, before: MapLayerState | null) => {
        const now = soloRef.current;
        const ids = (view: EditsView): EditsView => ({
            solo: view.solo === null ? null : layerIdFor(spec, view.solo),
            picking: view.picking === null ? null : layerIdFor(spec, view.picking),
        });
        showForEdits(map, was && ids(was), ids(now ?? { solo: null, picking: null }), before, !!now?.solo && colorMapped(now.solo));
    };
    // The pane of the map a Map Editor node edits, when the node draws several
    // views: the tools lie over that map's pane alone. With one view they lie
    // over the node's body, which the map fills.
    const [editPane, setEditPane] = useState<HTMLElement | null>(null);
    /**
     * Hand the Map Editor node feeding the map the map it edits, as *grammar*
     * drew *spec*, its views in *panes*: the map its interaction edge names,
     * else the first. The overlay on that map reads its camera, its layers'
     * ids, and where the draw put a feature's rows, read back from what autk-db
     * exported, which the layer skips while the drawing tools draw the feature
     * reshaped or moved.
     */
    const registerEditedMap = (grammar: any, spec: any, panes: ViewPanes | null) => {
        const index = editIndexOf(panes);
        const entry = mapEntries(spec)[index];
        const workspace = autkWorkspaceOf(entry);
        const inputFeatures = inputFeaturesRef.current;
        const loadOrders = loadOrdersRef.current;
        registerEditMap(
            data.nodeId,
            grammarMaps(grammar)[index] ?? null,
            (table) => layerIdFor({ map: entry }, table),
            async (table, key, id) => featurePositions(
                inputFeatures[autkTableKey(workspace, table)] ?? [],
                (await drawnRowsOf(grammar, workspace, table, index))
                    ?? loadOrders[autkTableKey(workspace, table)]?.map,
                key,
                id,
            ),
        );
        setEditPane((panes ?? []).length > 1
            ? wrapperRef.current?.querySelector<HTMLElement>(`[data-curio-autk-pane="map-${index}"]`) ?? null
            : null);
    };
    // Where each run is listed, under the node's id, as every node's are (#860).
    const { nodeExecProv } = useProvenanceContext();
    // Whether a run has been tried, whether one is under way, and what the last
    // one could not read from its input: the pre-run notice reads these.
    const hasRunRef = useRef(false);
    const runningRef = useRef(false);
    const pendingSpecRef = useRef<{ spec: string; preview: boolean } | null>(null);
    const inputProblemRef = useRef<{ reason: NodeEmptyReason; detail?: string } | null>(null);
    // The notice the body should show now, kept so a container that mounts
    // later (the editor remounting its output pane) gets it too.
    const noticeRef = useRef<{
        reason: NodeEmptyReason;
        words: { title?: string; hint?: string; progress?: readonly string[] };
    } | null>(null);
    const writeNotice = () => {
        const host = wrapperRef.current;
        if (!host || runningRef.current || grammarRef.current != null) return;
        const notice = noticeRef.current;
        if (notice) {
            writeEmptyState(host, notice.reason, notice.words);
        } else if (host.hasAttribute('data-curio-node-empty')) {
            // A notice that no longer applies is not left behind.
            host.replaceChildren();
            clearEmptyState(host);
        }
    };
    const attachWrapper = useCallback((el: HTMLDivElement | null) => {
        wrapperRef.current = el;
        if (el) writeNotice();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    // A run that ends on an input it cannot draw names it in the body at once,
    // as the Vega-Lite node does when it prepares its input.
    const showInputProblem = (kind: AutkSpecKind) => {
        const problem = inputProblemRef.current;
        if (!problem) return;
        noticeRef.current = {
            reason: problem.reason,
            words: emptyStateWords(problem.reason, kind, problem.detail),
        };
        writeEmptyState(wrapperRef.current, problem.reason, noticeRef.current.words);
    };

    // The node's status set from outside its own run (UniversalNode): a step of
    // a run on the server among them (`serverOutput`). A document that only
    // loads data runs there as its run here posts it, so its result says what
    // it loaded, as a run here says it, rather than "not run yet" under Done.
    const setOutputFromOutside = (output: NodeOutput) => {
        const code = isEmptySpecBuffer(nodeState.code) ? data.defaultCode : nodeState.code;
        const loadsData = classifyAutkSpecString(code) === 'data';
        const ran = output?.code === 'exec' || output?.code === 'success' || output?.code === 'error';
        // A run tried, as applyGrammar marks one: no "not run yet" after it.
        if (loadsData && ran) hasRunRef.current = true;
        nodeState.setOutput(output);
        if (!loadsData || !ran) return;
        if (output.code !== 'success') {
            setRunSummary(null);
            return;
        }
        // The notice before a run goes, as a run here empties the body.
        noticeRef.current = null;
        const host = wrapperRef.current;
        if (host?.hasAttribute('data-curio-node-empty')) {
            host.replaceChildren();
            clearEmptyState(host);
        }
        // The document as the node holds it: a chip standing on its own holds
        // its place, as it does where the document's kind is read.
        setRunSummary(describeAutkRun('Loaded', 'table', sectionTablesHandedOn(JSON.parse(withChipPlaceholders(code as string)).data)));
    };

    const runGrammar = async (
        specString: string,
        emit: (o: { code: string; content: string }) => void,
        // A draw of the map again, for an edit a Map Editor node feeding it
        // made: it draws, and hands nothing on.
        preview = false,
    ) => {
        const handOnRun = (output: unknown) => {
            if (!preview) handOn(output);
        };
        let spec: any;
        try {
            spec = typeof specString === 'string' ? JSON.parse(specString) : { ...(specString as any) };
        } catch {
            emit({ code: 'error', content: 'Invalid JSON grammar spec.' });
            return;
        }
        setSpecKind(classifyAutkSpec(spec));
        setRunSummary(null);

        // Views autk-grammar refuses (an id two views share, two plots known
        // by one name, a link that names no view or layer) are refused before
        // anything runs, in the grammar's words, which the agents' document
        // check says too (contracts/autkGrammar autkViewProblem).
        const viewProblem = autkViewProblem(spec);
        if (viewProblem) {
            emit({ code: 'error', content: viewProblem });
            showToast(viewProblem, 'error');
            return;
        }
        // A key autk-grammar 5 renamed, or one a node does not run yet, is
        // refused the same way, naming the key and where it is written.
        const unrunKey = autkKeyProblem(spec);
        if (unrunKey) {
            emit({ code: 'error', content: unrunKey });
            showToast(unrunKey, 'error');
            return;
        }
        // A list of one map or one plot is that view.
        for (const view of ['map', 'plot'] as const) {
            if (Array.isArray(spec?.[view]) && spec[view].length === 1) {
                spec = { ...spec, [view]: spec[view][0] };
            }
        }

        // Ask whether this browser can run Autark at all, BEFORE any canvas or
        // DOM work (#201). Upstream of the dynamic import, the compute path and
        // the canvas creation, so a refusal leaves no orphaned canvas and no
        // window listeners behind. The library swallows its own init failure and
        // only throws much later, inside `createShaders()`, where the stack says
        // nothing about WebGPU.
        const needsGpu =
            spec.map != null ||
            spec.plot != null ||
            (Array.isArray(spec.compute) && spec.compute.length > 0);
        if (needsGpu) {
            const support = await detectWebGpuSupport();
            if (!support.supported) {
                const message =
                    support.reason ??
                    'Autark nodes need WebGPU, which this browser does not provide.';
                setGpuBlocked(message);
                emit({ code: 'error', content: message });
                showGpuToast(message);
                return;
            }
        }
        setGpuBlocked(null);

        const nodeId = data.nodeId;
        const hasMaps = spec.map != null;
        const hasPlot = spec.plot != null;

        // A document that draws loads the grammar, whose arrangeViews gives
        // each view its pane, as every host of the grammar arranges a
        // document's views: by its `layout`, stacked without one. A layout
        // the grammar cannot arrange is refused in its words.
        const grammarModule = hasMaps || hasPlot ? await import('@urban-toolkit/autk-grammar') : null;
        // A node that left the page while the grammar loaded has no canvas
        // to draw on: its run ends here (see mountedRef).
        if (leftPage()) return;
        let arrangement: ViewArrangement | null = null;
        if (grammarModule) {
            try {
                arrangement = grammarModule.arrangeViews(spec);
            } catch (err) {
                const message = describeError(err);
                emit({ code: 'error', content: message });
                showToast(message, 'error');
                return;
            }
            setViewRows(Math.max(arrangement.rows, 1));
        }

        // Each run draws on canvases of its own. The previous run's maps are
        // destroyed with theirs, their view taken first where the next draw
        // keeps it, each by its map's key in the document it was drawn from.
        const keepView = keepsView || editFedRef.current;
        if (keepView && grammarRef.current) keptViewsRef.current = mapViews(grammarRef.current, panesRef.current);
        destroyLastMaps();
        const wrapper = wrapperRef.current;
        // The element each view draws in, in its pane (autkViews layOutPanes).
        let laidOut: LaidOutViews | null = null;
        if (wrapper) {
            // Dispose the previous run's canvas pointer listeners (they live on
            // window, so they'd leak and fire for the now-stale canvas otherwise).
            pickFixCleanupRef.current?.();
            pickFixCleanupRef.current = null;
            while (wrapper.firstChild) wrapper.removeChild(wrapper.firstChild);
            clearEmptyState(wrapper);
            if (arrangement) {
                laidOut = layOutPanes(wrapper, nodeId, arrangement);
                // A drag that only passes over a map, begun on a handle, a
                // node or the pane, leaves the map's view (autkMapPressGuard).
                const disposers = laidOut.canvases.flatMap((canvas) => [
                    attachMapInteractionZoomFix(canvas),
                    attachMapPressGuard(canvas),
                ]);
                if (disposers.length > 0) pickFixCleanupRef.current = () => disposers.forEach((dispose) => dispose());
            }
        }

        // The authored data sources (osm / pbf / csv / json / geojson-from-URL)
        // are the heavy "data component": they run in the backend sandbox via
        // autk-db. Capture them before we touch spec.data.
        const specDataSources: any[] = Array.isArray(spec.data) ? spec.data : [];

        // The tables of the node's input its data section's heatmaps, joins,
        // updates and drops read (sectionInputTables): none for a section that
        // reads only what its own sources load. Of them, those a join writes
        // its columns onto or an update changes (sectionChangedTables), which
        // the section's load hands back as its own.
        const sectionInputs = sectionInputTables(specDataSources);
        const changedTables = new Set(sectionChangedTables(specDataSources));
        const joinedInputs = new Set(sectionInputs
            .map((table) => autkTableKey(table.workspace, table.name))
            .filter((key) => changedTables.has(key)));
        // The document's workspaces, which both loaders set up before the
        // first source, and the OpenStreetMap tables of its own a view reads
        // as OpenStreetMap elements, which both loaders read so.
        const loadOptions = {
            workspaces: Array.isArray(spec.workspaces) ? spec.workspaces : undefined,
            elements: osmElementTables(spec),
        };

        // The input as the tables the document reads (utils/autkInput): each
        // input is `input_<k>`, the layers an input carries keep their own
        // names, and `input_<k>` also names an input of one named layer when
        // the document names it. Upstream geojson
        // is data the browser already holds, so it stays client-side and is NOT
        // sent to the backend. A data-only document reads it only when its data
        // section reads tables of it, which its load then reads in the sandbox.
        let upstreamSources: any[] = [];
        // Those whose features carry their input row, for a document that draws a map.
        let taggedTables: string[] = [];
        // The input's rasters, loaded into the grammar's database by
        // loadGeoTiff (adapters/node/autkRasters), for a document that draws.
        let rasterSources: CurioRasterSource[] = [];
        let preparedInput: PreparedAutkInput | null = null;
        // The input table each table a pass writes holds the rows of (writtenFromRef).
        const writtenFrom: Record<string, string> = {};
        const readsInput = hasMaps || hasPlot || specDataSources.length === 0 || sectionInputs.length > 0;
        if (data.input && readsInput) {
            try {
                // A map draws each circle a Map Editor node feeds from that
                // node's input with its edits (mapEditsPreview); a compute
                // step, which draws nothing, reads what it was fed.
                let prepared = autkSourcesFrom(await ((hasMaps || hasPlot) ? readDrawnInput(data.input) : readInput(data.input)), spec);
                // The new layers a Map Editor node feeding the map makes are
                // drawn on top of its first map, once they have features.
                const made = newLayerTables(feedsRef.current).filter((table) =>
                    prepared.sources.some((source) => source.outputTableName === table && hasFeatures(source.geojsonObject)));
                const firstMap = mapEntries(spec)[0];
                if (made.length > 0 && firstMap) {
                    const refs: any[] = Array.isArray(firstMap.layerRefs) ? firstMap.layerRefs : [];
                    const missing = made.filter((table) => !refs.some((r: any) => r?.dataRef === table));
                    const drawn = { ...firstMap, layerRefs: [...refs, ...missing.map((table) => ({ dataRef: table }))] };
                    spec = { ...spec, map: Array.isArray(spec.map) ? [drawn, ...spec.map.slice(1)] : drawn };
                }
                if ((hasMaps || hasPlot) && prepared.rasters.length > 0) {
                    const resolved = await resolveRasterInputs(prepared.rasters);
                    rasterSources = resolved.sources;
                    if (resolved.problems.length > 0) {
                        prepared = {
                            ...prepared,
                            unusable: [...prepared.unusable, ...resolved.unusable],
                            inputProblem: [prepared.inputProblem, ...resolved.problems].filter(Boolean).join(' '),
                            ...(prepared.sources.length === 0 && rasterSources.length === 0
                                ? { emptyReason: 'input-type-rejected' as NodeEmptyReason, detail: resolved.problems[0] }
                                : {}),
                        };
                    }
                }
                preparedInput = prepared;
                if (prepared.emptyReason && prepared.sources.length === 0 && rasterSources.length === 0) {
                    inputProblemRef.current = { reason: prepared.emptyReason, detail: prepared.detail };
                }
                // An input table a join of the data section writes its columns
                // onto comes back from the section's load as the join made it,
                // a table of the node's own: the input's is not drawn beside it.
                const drawnFromInput = prepared.sources.filter((source) => !joinedInputs.has(tableKeyOf(source)));
                // A table a pass writes from one of the input's holds that
                // table's rows, as autk-db stores them (writtenTables); a
                // render pass's building windows hold none of them. Both by
                // key: a pass reads and writes tables of its own workspace.
                const inputTables = new Set(drawnFromInput.map(tableKeyOf));
                for (const { name, from, holdsRows, workspace } of writtenTables(spec)) {
                    const fromKey = autkTableKey(workspace, from);
                    const root = writtenFrom[fromKey] ?? fromKey;
                    if (holdsRows && inputTables.has(root)) writtenFrom[autkTableKey(workspace, name)] = root;
                }
                const passRoots = new Set(Object.values(writtenFrom));
                const orders: Record<string, LoadOrder> = {};
                const features: Record<string, readonly any[]> = {};
                upstreamSources = drawnFromInput.map((source) => {
                    // Each feature a map draws, and each a pass computes over,
                    // carries its input row, read back from what autk-db exported.
                    const loadable = loadableSource(source, { tagRows: hasMaps || passRoots.has(tableKeyOf(source)) });
                    orders[tableKeyOf(source)] = loadable.order;
                    features[tableKeyOf(source)] = (source.geojsonObject as any)?.features ?? [];
                    return loadable.source;
                });
                taggedTables = drawnFromInput.map(tableKeyOf)
                    .filter((table) => hasMaps || passRoots.has(table));
                for (const [name, root] of Object.entries(writtenFrom)) {
                    // A pass's result keeps the rows in the order autk-db
                    // stores them, which a map draws and a plot of it holds.
                    orders[name] = { load: orders[root].map, map: orders[root].map };
                    features[name] = features[root];
                    taggedTables.push(name);
                }
                loadOrdersRef.current = orders;
                inputFeaturesRef.current = features;
            } catch (e) {
                // What the render then cannot find is what gets reported.
                console.warn('[autk-grammar] reading the input failed:', e);
            }
        }

        // Tear down any listeners from the previous run before creating a new
        // grammar instance, so we never hold stale references.
        interactionOffRef.current.forEach(f => f());
        interactionOffRef.current = [];

        // Key columns a pick or a brush cannot read (utils/autkInput
        // selectFieldsProblem) fail the run before anything is loaded or
        // drawn, as a document with more than one view does.
        const keyProblem = selectFieldsProblem(spec, preparedInput?.sources ?? []);
        if (keyProblem) {
            grammarRef.current = null;
            specRef.current = null;
            emit({ code: 'error', content: keyProblem });
            showToast(keyProblem, 'error');
            return;
        }
        // So does a compute pass over a raster the input brings, as one over a
        // raster of the document's own data is refused above (autkKeyProblem):
        // a pass cannot compute over a raster cell by cell
        // (contracts/autkGrammar autkRasterPassProblem). Each raster is in
        // the workspace it came in, which a pass reads it in.
        const rasterPass = autkRasterPassProblem(
            spec,
            (preparedInput?.rasters ?? []).map((raster) => ({ name: raster.outputTableName, workspace: raster.workspace })),
        );
        if (rasterPass) {
            grammarRef.current = null;
            specRef.current = null;
            emit({ code: 'error', content: rasterPass });
            showToast(rasterPass, 'error');
            return;
        }
        // The tables of the input its data section's heatmaps and joins read
        // are found among the input's, by key, before anything loads. With no
        // input, or with an input that names one it cannot give (a frame with
        // no geometry), nothing arrived to read, and the upstream is what must
        // change, as for a compute step fed nothing. A table the input does
        // not carry fails the run with the words both loaders say.
        if (sectionInputs.length > 0) {
            const carried = new Set((preparedInput?.sources ?? []).map(tableKeyOf));
            const unusable = new Set(preparedInput?.unusable ?? []);
            const absent = sectionInputs.find((table) => !carried.has(autkTableKey(table.workspace, table.name)));
            const nothingArrived = data.input == null || data.input === ''
                || (absent !== undefined && unusable.has(autkTableKey(absent.workspace, absent.name)));
            const refusal = nothingArrived
                ? renderOutcome({ rowsIn: 0, ...(preparedInput?.inputProblem ? { inputProblem: preparedInput.inputProblem } : {}) })
                : null;
            if (refusal || absent) {
                grammarRef.current = null;
                specRef.current = null;
                if (refusal) showInputProblem(classifyAutkSpec(spec));
                const message = refusal ? refusal.message : absent!.missing;
                emit({ code: 'error', content: message, ...(refusal ? { kind: emptyRenderKind(refusal.cause) } : {}) } as any);
                showToast(message, 'error');
                return;
            }
        }

        emit({ code: 'exec', content: '' });
        let summary: string | null = null;
        // What a data or compute run can count about itself, read by the
        // empty-render gate below. Null when the run made no count at all.
        let runCounts: RenderCounts | null = null;
        // Whether `summary` lists what the run produced. An empty list reads
        // "the spec names no tables", which must not follow an empty-render
        // verdict that already said what went wrong.
        let summaryListsItems = false;
        try {
            // ── Data section → backend sandbox ──────────────────────────────
            // The authored data sources are compiled to autk-db JavaScript and
            // executed in the Node.js sandbox, where the layer array is persisted
            // in DuckDB. The browser only renders. backendRef is the DuckDB
            // artifact reference; backendLayers is set only by the in-browser
            // fallback (sandbox unreachable / source can't run server-side).
            let backendRef: { path: string; dataType: string } | null = null;
            let backendLayers: AutkLayer[] | null = null;

            // The tables of the input the data section reads, as the node
            // reads its input, for the in-browser loader.
            const inputTables = sectionInputs.length > 0 ? preparedInput?.sources ?? [] : [];
            if (specDataSources.length > 0) {
                const resolvedForBackend = resolveDataSourceUrls({ data: specDataSources }, true).data;
                // The load the sandbox runs is the authored data sources, with
                // the document's workspaces and the tables its views read as
                // OpenStreetMap elements, and, for a section that reads tables
                // of the node's input, that input, which the sandbox reads by
                // reference: the DuckDB artifact is a pure function of them, so
                // they are its key. A section that reads none is keyed on its
                // sources alone, and an upstream that runs again reloads only
                // the section that reads it.
                const sentInput = sectionInputs.length > 0 ? data.input : '';
                const cacheKey = sectionInputs.length > 0
                    ? JSON.stringify([resolvedForBackend, loadOptions, executionInputRef(sentInput)])
                    : JSON.stringify([resolvedForBackend, loadOptions]);

                if (dataCacheRef.current && dataCacheRef.current.key === cacheKey) {
                    backendRef = dataCacheRef.current.ref;
                } else {
                    try {
                        if (!data.jsInterpreter) throw new Error('No JS interpreter available for backend data load.');
                        const code = compileDataSpecToAutkDbJs(resolvedForBackend, loadOptions);
                        backendRef = await runDataInBackend(data.jsInterpreter, code, data.nodeId, sentInput);
                        dataCacheRef.current = { key: cacheKey, ref: backendRef };
                    } catch (e: any) {
                        // Graceful fallback: load the data in-browser (the original
                        // path) so the node still works if the sandbox is down.
                        const backendReason = e?.message ?? String(e);
                        console.warn('[autk-grammar] backend data load failed; falling back to in-browser AutkDb:', backendReason);
                        const resolvedForFrontend = resolveDataSourceUrls({ data: specDataSources }, false).data;
                        dataCacheRef.current = null;
                        try {
                            backendLayers = await loadSpecLayers(
                                { data: resolvedForFrontend, workspaces: loadOptions.workspaces }, inputTables,
                                { elements: loadOptions.elements },
                            );
                        } catch (fe: any) {
                            // Both paths failed. Surface BOTH reasons: the backend
                            // failure is otherwise swallowed here, and the e2e log
                            // capture keeps only console.error/pageerror entries
                            // (never warns), so a recurrence would otherwise show
                            // up as the in-browser loader's opaque error with no
                            // hint at the real (backend) cause.
                            const fallbackReason = fe?.message ?? String(fe);
                            const combined =
                                `autk data load failed — backend: ${backendReason}; `
                                + `in-browser fallback: ${fallbackReason}`;
                            console.error('[autk-grammar]', combined);
                            throw new Error(combined);
                        }
                    }
                }
            }

            // The layers the data section loaded, in the browser: read back from
            // the sandbox's artifact, or those the in-browser fallback loaded.
            // Self-heal: if the backend ref produced no usable layers (artifact
            // evicted, session changed, or a serialization mismatch), drop the
            // cache and load in-browser so the node draws and computes instead of
            // silently working on nothing. Only applies to the backend-ref path
            // (backendLayers == null means we did not already fall back). Each
            // layer keeps the workspace it was loaded into. A buildings layer
            // holds its heights where autk-map and a pass read them, as one of
            // the input does (withReadableHeights); a building with no height
            // holds none, and is as tall as the document uses it (a map's
            // heightsAtUse, a compute step's applyComputeBlocks).
            const loadedLayers = async (): Promise<AutkLayer[]> => {
                let layers: AutkLayer[] = [];
                try {
                    layers = await materializeBackendLayers(backendLayers, backendRef);
                } catch {
                    layers = [];
                }
                if (layers.length === 0 && backendLayers == null) {
                    console.warn('[autk-grammar] backend layers empty/unresolvable; falling back to in-browser AutkDb');
                    dataCacheRef.current = null;
                    const resolvedForFrontend = resolveDataSourceUrls({ data: specDataSources }, false).data;
                    layers = await loadSpecLayers(
                        { data: resolvedForFrontend, workspaces: loadOptions.workspaces }, inputTables,
                        { elements: loadOptions.elements },
                    );
                }
                return layers.map((layer) => (layer.type === 'buildings'
                    ? { ...layer, geojson: withReadableHeights(layer.geojson) }
                    : layer));
            };

            if (hasMaps || hasPlot) {
                // Render node: feed the backend-loaded data in as inline geojson
                // sources (so the grammar engine never re-loads from URL), then run
                // compute/map/plot in the browser. Backend layers are already
                // projected to the workspace CRS (EPSG:3395).
                let dataSectionSources: any[] = [...rasterSources, ...upstreamSources];
                // The sources this node's own data section loaded, as opposed to
                // what arrived from upstream: an empty one is the document's fault.
                let ownSources: any[] = [];
                if (specDataSources.length > 0) {
                    const layers = await loadedLayers();
                    // coordinateFormat must reflect the coordinates as loaded
                    // (autk-db returns layers in the workspace CRS, EPSG:3395
                    // meters): the layers carry a crs stamp set by the loader,
                    // which detectCoordinateFormat reads (falling back to the
                    // coordinate-magnitude heuristic). Each goes back into the
                    // workspace it was loaded into, where the grammar's data
                    // adapter loads it.
                    const backendAsSources = layers.filter((l) => l.type !== RASTER_TABLE).map((l) => ({
                        type: 'geojson',
                        geojsonObject: l.geojson,
                        outputTableName: l.name,
                        coordinateFormat: detectCoordinateFormat(l.geojson as any),
                        ...(l.type && l.type !== 'polygons' ? { layerType: l.type } : {}),
                        ...(l.workspace ? { workspace: l.workspace } : {}),
                    }));
                    // The raster tables the data section made (a heatmap, a
                    // GeoTIFF), drawn as every raster is (adapters/node/autkRasters),
                    // each in the workspace it was made in. A GeoTIFF too large to
                    // draw is made smaller by its source, known by its key.
                    const geotiffs = new Set(specDataSources
                        .filter((source) => source?.type === 'geotiff')
                        .map((source) => autkTableKey(autkWorkspaceOf(source), source.outputTableName)));
                    const ownRasters = layers.filter((l) => l.type === RASTER_TABLE).map((l) => {
                        const madeBy = geotiffs.has(autkTableKey(l.workspace, l.name)) ? 'geotiff' : 'node';
                        const source = rasterSourceOf(l.name, l.geojson, madeBy);
                        if ('refused' in source) throw new Error(source.refused);
                        return l.workspace ? { ...source, workspace: l.workspace } : source;
                    });
                    ownSources = [...ownRasters, ...backendAsSources];
                    dataSectionSources = [...rasterSources, ...ownRasters, ...upstreamSources, ...backendAsSources];
                }
                // What the document can draw from, counted BEFORE any source is
                // dropped: an empty table still exists, so a ref to it is not a
                // ref to data the dataflow does not produce (that would be rule
                // 1, `no-layers`, blaming the wrong thing). `rows` is undefined
                // when the collection could not be counted. Tables are known by
                // key (tableKeyOf), since two workspaces can hold tables of one
                // name, and each view names a table of its own workspace.
                const tableRows = new Map<string, { rows: number | undefined; own: boolean }>();
                for (const s of dataSectionSources) {
                    if (typeof s?.outputTableName !== 'string' || !s.outputTableName) continue;
                    tableRows.set(tableKeyOf(s), {
                        // A raster's rows are its cells.
                        rows: isCurioRasterSource(s) ? s.cells : featureCount(s.geojsonObject),
                        own: ownSources.includes(s),
                    });
                }
                // Tables the document reads from its input that the input could
                // not provide (a DataFrame with no geometry column, a refused
                // input type) are known zeros from upstream: the verdict blames
                // the upstream and says why, instead of calling the ref one to
                // data the dataflow does not produce.
                if (preparedInput?.inputProblem) {
                    const own = new Set(ownTableNames(spec));
                    const unusable = new Set(preparedInput.unusable);
                    const refused = preparedInput.sources.length === 0;
                    for (const ref of documentTableRefs(spec)) {
                        if (tableRows.has(ref) || own.has(ref)) continue;
                        if (refused || unusable.has(ref)) tableRows.set(ref, { rows: 0, own: false });
                    }
                }
                // A table a compute pass of the document writes is a table this
                // node has: it holds the rows of the table the pass computes
                // over, and is this node's own when that one is. In pass order,
                // so one written from another's holds its rows too. By key:
                // a pass reads and writes tables of its own workspace. A
                // render pass's building windows are counted as the buildings'
                // rows: there are none when there are no buildings.
                const written = writtenTables(spec);
                for (const { name, from, workspace } of written) {
                    const source = tableRows.get(autkTableKey(workspace, from));
                    if (source) tableRows.set(autkTableKey(workspace, name), { ...source });
                }
                // autk-db's loadGeojson throws on an empty FeatureCollection. Two
                // consequences for sparse data (e.g. a PBF area with no parks, or a
                // join that empties a layer):
                //   1. an empty geojson source must be dropped before grammar.run,
                //   2. a map/plot ref to a table that is empty — or that an upstream
                //      node already dropped, so it never arrives here — dangles and
                //      fails grammar.run with "Table <name> not found".
                // Drop empty sources, then keep only refs that point at a table this
                // node can actually create: layers with data render; empty/absent
                // ones contribute nothing. Each drop is
                // logged, since a silently stripped layer otherwise reads as a
                // blank map. A collection that cannot be counted cannot be loaded
                // either, so it is dropped too; its count above stays unknown.
                const emptySources = dataSectionSources.filter(
                    (s: any) => s?.type === 'geojson' && !hasFeatures(s?.geojsonObject),
                );
                if (emptySources.length > 0) {
                    console.warn(
                        '[autk-grammar] dropping empty geojson source(s): '
                        + emptySources.map((s: any) => s?.outputTableName ?? '(unnamed)').join(', '),
                    );
                    dataSectionSources = dataSectionSources.filter(
                        (s: any) => !emptySources.includes(s),
                    );
                }
                // What autk-db loads (utils/autkInput tablesToLoad): of the
                // input's tables, those the document names, and every table
                // its own data section loaded; first, the surface of each OSM
                // load a table it names is a layer of (#886). The counts above
                // cover every table at hand, so the verdict below tells a
                // misnamed table apart from data the input does not bring.
                const handed = tablesToLoad(dataSectionSources, spec, ownSources);
                // A building with no height is as tall as the document uses
                // it: the default height above its base in a table a map layer
                // draws or a pass reads, none in one a layer with
                // buildingsZeroHeight draws, which autk-map raises at random,
                // and as it came in a table only a plot reads (utils/autkInput
                // heightsAtUse). On a 1 cm grid, so autk-db's second clip of
                // these already clipped layers holds (see utils/geoPrecision).
                const uses = heightUses(spec);
                spec = { ...spec, data: handed.map((source) => snapSourceToGrid(heightsAtUse(source, uses))) };
                if (dataSectionSources.length === 0 && (hasMaps || hasPlot)) {
                    console.warn(
                        '[autk-grammar] render node has no data sources left — the '
                        + 'grammar engine will produce no data context and the '
                        + 'map/plot will render blank. Check the upstream nodes.',
                    );
                }
                // dev/136: what this render ASKED for, before any resolution
                // drops a thing. A dropped layerRef used to leave a
                // console.warn as its only trace, so a map whose every ref was
                // dropped rendered a grey canvas under a green "Done". Each is
                // a table of its own map's or plot's workspace, by key. Each
                // view is known by its place in the document as written, which
                // names the element it draws in (autkViews viewTargets).
                let maps = mapEntries(spec).map((entry, index) => ({ index, entry }));
                let plots = plotEntries(spec).map((entry, index) => ({ index, entry }));
                const refsOf = (entry: any): any[] => (Array.isArray(entry?.layerRefs) ? entry.layerRefs : []);
                const mapRefKey = (entry: any, r: any) => autkTableKey(autkWorkspaceOf(entry), r.dataRef);
                const plotTableKey = (entry: any, table: string) => autkTableKey(autkWorkspaceOf(entry), table);
                const requestedRefs: string[] = [
                    ...maps.flatMap(({ entry }) => refsOf(entry)
                        .filter((r: any) => typeof r?.dataRef === 'string' && !!r.dataRef)
                        .map((r: any) => mapRefKey(entry, r))),
                    ...plots.filter(({ entry }) => entry?.dataRef)
                        .map(({ entry }) => plotTableKey(entry, String(entry.dataRef))),
                ];
                // Every table this node holds, empty ones included, is what the
                // document could have named; only the non-empty ones can be
                // handed to the grammar.
                const knownNames = new Set<string>(tableRows.keys());
                const availableRefs: string[] = [...knownNames];
                if (knownNames.size > 0) {
                    const availableNames = new Set<string>(
                        dataSectionSources
                            .filter((s: any) => s?.outputTableName)
                            .map(tableKeyOf),
                    );
                    // The grammar's run reads each table a pass names from
                    // autk-db, which holds none without rows: a pass over one
                    // does not run, and a render layer of one, which would
                    // draw nothing, is left out of its pass (passesAtHand). A
                    // pass that runs writes its table, in its own workspace.
                    if (Array.isArray(spec.compute)) {
                        const passes = passesAtHand(spec.compute, knownNames, availableNames);
                        for (const { name, workspace } of writtenTables({ compute: passes })) {
                            availableNames.add(autkTableKey(workspace, name));
                        }
                        spec = { ...spec, compute: passes };
                    }
                    maps = maps.map(({ index, entry }) => {
                        if (!Array.isArray(entry?.layerRefs)) return { index, entry };
                        const dangling = entry.layerRefs.filter(
                            (r: any) => r?.dataRef && !knownNames.has(mapRefKey(entry, r)),
                        );
                        const empty = entry.layerRefs.filter(
                            (r: any) => r?.dataRef && knownNames.has(mapRefKey(entry, r))
                                && !availableNames.has(mapRefKey(entry, r)),
                        );
                        if (dangling.length > 0) {
                            console.warn(
                                '[autk-grammar] dropping map layerRef(s) to unavailable table(s): '
                                + dangling.map((r: any) => mapRefKey(entry, r)).join(', ')
                                + ' - available: ' + [...availableNames].join(', '),
                            );
                        }
                        if (empty.length > 0) {
                            console.warn(
                                '[autk-grammar] dropping map layerRef(s) to empty table(s): '
                                + empty.map((r: any) => mapRefKey(entry, r)).join(', '),
                            );
                        }
                        if (dangling.length === 0 && empty.length === 0) return { index, entry };
                        return {
                            index,
                            entry: {
                                ...entry,
                                layerRefs: entry.layerRefs.filter((r: any) => !dangling.includes(r) && !empty.includes(r)),
                            },
                        };
                    });
                    // A plot bound to an unavailable layer has nothing to draw:
                    // drop it rather than fail resolving the missing table.
                    plots = plots.filter(({ entry }) => {
                        const unavailable = (entry.dataRef && !availableNames.has(plotTableKey(entry, entry.dataRef)))
                            || (entry.mapRef && !availableNames.has(plotTableKey(entry, entry.mapRef)));
                        if (unavailable) {
                            console.warn(
                                '[autk-grammar] dropping plot bound to unavailable table: '
                                + plotTableKey(entry, entry.dataRef ?? entry.mapRef)
                                + ' - available: ' + [...availableNames].join(', '),
                            );
                        }
                        return !unavailable;
                    });
                }
                // A map left with no layer to draw draws nothing: it is left
                // out, as a plot of no table is, and its pane stays empty.
                maps = maps.filter(({ entry }) => refsOf(entry).length > 0);
                // The document the grammar runs holds the views it draws, one
                // object for one view of a kind, and the links between them:
                // a link to a view or a layer left out is left out too, which
                // the grammar would refuse (autkViews linksAtHand).
                const asWritten = (views: Array<{ entry: any }>) =>
                    (views.length === 0 ? undefined : views.length === 1 ? views[0].entry : views.map(({ entry }) => entry));
                {
                    const { map: _map, plot: _plot, links: _links, ...rest } = spec;
                    const drawn: any = { ...rest };
                    if (maps.length > 0) drawn.map = asWritten(maps);
                    if (plots.length > 0) drawn.plot = asWritten(plots);
                    const links = linksAtHand({ ...drawn, links: spec.links });
                    if (Array.isArray(spec.links) && links.length < spec.links.length) {
                        console.warn('[autk-grammar] dropping link(s) to a view or layer left out: '
                            + JSON.stringify(spec.links.filter((link: any) => !links.includes(link))));
                    }
                    if (links.length > 0) drawn.links = links;
                    spec = drawn;
                }
                // The refs that name a table this node holds, whether or not it
                // had rows: what the document resolved against, and what its
                // row counts are read from.
                const resolvedRefs = [...new Set(requestedRefs)].filter((r) => knownNames.has(r));
                const resolvedRows = resolvedRefs.map((r) => tableRows.get(r)!);
                const ownRows = resolvedRows.filter((t) => t.own);

                // dev/136: did this map/plot actually draw? The layers that
                // resolved are what there was to draw FROM, so an empty set is
                // an empty render, reported rather than warned about. A ref to
                // an EMPTY table resolved; its zero rows are what `rowsIn` and
                // `sourceRows` report instead. The layers handed to the grammar
                // are what it drew, and the gap is what the partial note names.
                // autk-grammar's run() returns nothing, so there is no
                // drawn-mark count, and nothing here depends on the run: an empty
                // verdict is reached before it, so the grammar is never handed a
                // plot with no data context to fail on.
                const layersResolved = requestedRefs.filter((r) => knownNames.has(r)).length
                    + plots.filter(({ entry }) => !entry?.dataRef).length;
                const layersDrawn = maps.reduce((sum, { entry }) => sum + refsOf(entry).length, 0) + plots.length;
                const emptyRefs = requestedRefs.filter((r) => {
                    const table = tableRows.get(r);
                    return !!table && !(typeof table.rows === 'number' && table.rows > 0);
                });
                const renderCounts: RenderCounts = {
                    layersRequested: requestedRefs.length,
                    layersResolved,
                    layersDrawn,
                    requestedRefs,
                    availableRefs,
                    emptyRefs,
                    // A table named while none is at hand is a known zero:
                    // nothing arrived and nothing was loaded. Otherwise no
                    // claim when the document names no table to count.
                    rowsIn: knownNames.size === 0 && requestedRefs.length > 0
                        ? 0
                        : resolvedRows.length > 0
                            ? totalCount(resolvedRows.map((t) => t.rows))
                            : undefined,
                    sourceRows: ownRows.length > 0
                        ? totalCount(ownRows.map((t) => t.rows))
                        : undefined,
                    ...(preparedInput?.inputProblem ? { inputProblem: preparedInput.inputProblem } : {}),
                };
                const outcome = renderOutcome(renderCounts);
                if (outcome.empty) {
                    grammarRef.current = null;
                    specRef.current = null;
                    showInputProblem('render');
                    emit({ code: 'error', content: outcome.message,
                           kind: emptyRenderKind(outcome.cause) } as any);
                    showToast(outcome.message, 'error');
                    return;
                }

                // Each plot the document did not size fills its own pane (see
                // utils/autkPlotSizing), measured now because the node can be
                // resized while its data loads.
                const plotPanes = plots.map(({ index }) => laidOut?.element('plot', index) ?? null);
                if (plots.length > 0) {
                    const fitted = plotEntries(spec).map((plot, at) => {
                        const pane = plotPanes[at];
                        return pane ? fitPlotToPane(plot, { width: pane.clientWidth, height: pane.clientHeight }) : plot;
                    });
                    spec = { ...spec, plot: fitted.length === 1 ? fitted[0] : fitted };
                }
                // Each view the run keeps draws in its element, named by its
                // place in the document as written: one of a kind by its id,
                // several by a list in the grammar's order.
                const targets = viewTargets(nodeId, {
                    maps: maps.map(({ index }) => index),
                    plots: plots.map(({ index }) => index),
                });

                // The map draws its layers as the document writes them: a layer
                // in its scenario's color writes that box's color through its
                // chip, resolved before the run (utils/references/codeReferences).
                // Every raster draws each cell that has a value opaque, and a
                // base-map layer the map lists after a raster draws over it.
                spec = withLayersOverRasters(withOpaqueRasters(spec));

                const { AutkGrammar, applyCamera, arrangeViews, enterWorkspace, playCameraMotion } = grammarModule!;
                // A node that left the page while its data loaded has no
                // canvas to draw on: its run ends here (see mountedRef).
                if (leftPage()) return;
                // A fresh grammar per attempt: it builds its own AutkDb, and a
                // DuckDB worker that failed to fetch the spatial extension keeps
                // that state, so only a new one can succeed (#318).
                const drawsRasters = (spec.data as any[]).some(isCurioRasterSource);
                const computes = Array.isArray(spec.compute) && spec.compute.length > 0;
                const grammar = await withExtensionRetry(async () => {
                    const g = new AutkGrammar(targets);
                    // A raster enters its workspace when the document keeps
                    // tables in more than the default one (autkUsesWorkspaces).
                    if (drawsRasters) withRasterSources(g, newAutkDb, autkUsesWorkspaces(spec) ? enterWorkspace : undefined);
                    // Each pass the run computes is checked on the GPU's
                    // device, as a compute step's is (autkComputeScopes). It
                    // runs on the run's own database, and reads a fromFeature
                    // table as the GeoJSON the node handed the run, from the
                    // cache of the grammar's own data adapter, of the same
                    // entry as its compute adapter.
                    if (computes) withCheckedPasses(g);
                    try {
                        await g.run(spec);
                    } catch (err) {
                        // A failed attempt ends its own database (autkDbClose),
                        // then the maps it made, which no node keeps.
                        closeGrammarDb(g);
                        destroyFailedGrammar(g);
                        throw err;
                    }
                    return g;
                });
                // The node keeps the grammar's maps, handed over first, so they
                // are destroyed with the next run or the node even if a step
                // below fails, and with them the database the run drew from.
                const destroyMaps = trackMaps(grammar);
                destroyMapsRef.current = () => {
                    destroyMaps();
                    closeGrammarDb(grammar);
                };
                // A node that left the page while they were made destroys them
                // now, and its run ends there.
                if (leftPage()) {
                    destroyLastMaps();
                    return;
                }
                // The key the grammar knows each view it drew by, from the
                // panes of the document it ran.
                const panes = arrangeViews(spec).panes;
                bleedRasterEdges(grammar, spec);
                // Each map is framed on its layers, then turned by the camera
                // its own entry writes, through the grammar's applyCamera,
                // and plays its camera's tour from there, through the
                // grammar's playCameraMotion (autkMapView).
                attachSpecCameras(grammar, spec, applyCamera, playCameraMotion);
                if (keepView && keptViewsRef.current) keepMapViews(grammar, keptViewsRef.current, panes);
                else frameMaps(grammar);
                if (editFedRef.current) {
                    // What was set on each layer through the map's menu, the
                    // layer a Map Editor node shows alone and the layer its
                    // action works on, kept across the draw, on the map the
                    // Map Editor node edits: the map its edge names, else the
                    // node's first (registerEditedMap).
                    const editIndex = editIndexOf(panes);
                    const shownMap = grammarMaps(grammar)[editIndex];
                    restoreMapLayers(shownMap, savedLayersRef.current);
                    if (soloRef.current) showAsEditsAsk(shownMap, { map: mapEntries(spec)[editIndex] }, null, soloRef.current.before);
                    registerEditedMap(grammar, spec, panes);
                }
                savedLayersRef.current = null;
                // autk-plot's SVG is inline, so it sits on a line of text whose
                // descender space overflows a pane the plot exactly fills, and
                // brings the scrollbars back. As a block it fits.
                for (const pane of plotPanes) {
                    for (const child of Array.from(pane?.children ?? [])) {
                        if (child.tagName.toLowerCase() === 'svg') (child as SVGElement).style.display = 'block';
                    }
                }

                // Store for interaction effects
                grammarRef.current = grammar;
                specRef.current    = spec;
                panesRef.current   = panes;
                drawnRef.current   = {
                    grammar, tagged: new Set(taggedTables), features: new Map(), rows: new Map(),
                    reads: Promise.resolve(), enterWorkspace,
                };
                writtenFromRef.current = writtenFrom;

                // Grammar → Curio: forward map-picking and plot-selection events to
                // the Curio interaction bus so connected nodes (data-pool, Vega) react.
                // Guard against older package versions that pre-date the interactions API.
                if (grammar.interactions) {
                    // Each pick or brush is read in the view that made it,
                    // which autk-grammar names (`mapId`, `plotId`; autkViews):
                    // the layer it is on, so a downstream Data Pool can target
                    // the right layer in a multi-layer wrapper (otherwise the
                    // pool's legacy path operates on data[0] and a brush on,
                    // say, roads ends up marking surface features), the
                    // workspace of that layer's table, and the key columns the
                    // view names its rows by, if any (selectFields). A picked
                    // map layer is the one that picks on that map when the pick
                    // is made, else the map's first with isPick:true; a plot's
                    // source is its dataRef.
                    const keysOf = (layerRef: string | undefined, view: DrawnView) => view.kind === 'map'
                        ? selectFieldsOf((Array.isArray(view.entry?.layerRefs) ? view.entry.layerRefs : [])
                            .find((l: any) => l?.dataRef === layerRef))
                        : selectFieldsOf(view.entry);

                    const sendInteraction = (
                        selection: number[],
                        layerRef: string | undefined,
                        view: DrawnView,
                        order: number[] | null | undefined,
                    ) => {
                        // Rows of the input, not positions in what was drawn.
                        const rows = selection.map((position) => inputRow(position, order));
                        // A view that names its key columns sends their values,
                        // as a Vega-Lite point select over fields does (#847), so
                        // a chart over other rows finds the ones they name. A
                        // pick on rows that hold none selects nothing.
                        const fields = keysOf(layerRef, view);
                        const workspace = autkWorkspaceOf(view.entry);
                        const data = fields && layerRef
                            ? keyValues(rows, inputFeaturesRef.current[autkTableKey(workspace, layerRef)] ?? [], fields)
                            : rows;
                        sendOwnSelection({
                            [EDIT_SELECTION]: {
                                type: data.length > 0 ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
                                data,
                                priority: 1,
                                source: NodeType.AUTK_GRAMMAR,
                                // A table a pass wrote holds the rows of the
                                // input table it is computed from: named so.
                                layerRef: rowsTableOf(layerRef, workspace),
                            },
                        }, view);
                    };
                    const emitInteraction = (
                        selection: number[],
                        layerRef: string | undefined,
                        view: DrawnView,
                    ) => {
                        // A pick names positions in the layer as its map drew
                        // it, and a brush positions in the table the plot holds,
                        // which for a table a pass wrote is what the pass kept,
                        // each a table of the view's workspace.
                        const workspace = autkWorkspaceOf(view.entry);
                        const loaded = layerRef
                            ? loadOrdersRef.current[autkTableKey(workspace, layerRef)]?.[view.kind === 'map' ? 'map' : 'load']
                            : null;
                        const drawn = !layerRef ? null
                            : view.kind === 'map' ? drawnRowsOf(grammar, workspace, layerRef, view.index)
                                : writtenRowsOf(grammar, layerRef, workspace);
                        if (!drawn) {
                            sendInteraction(selection, layerRef, view, loaded);
                            return;
                        }
                        void drawn.then((order) => {
                            // A view drawn again since shows none of this selection.
                            if (grammarRef.current !== grammar) return;
                            sendInteraction(selection, layerRef, view, order ?? loaded);
                        });
                    };

                    // A pick is on the layer that picks now on the map it was
                    // made on, which can be another than the map's first
                    // `isPick` layer: autk-grammar 5 names the map by `mapId`,
                    // and the layer picked by its title, else its table
                    // (autkMapState `pickOn`). A brush is the plot's its
                    // `plotId` names; one that names none is the first plot's.
                    const off1 = grammar.interactions.on('map:picking', ({ mapId, layerId, selection }) => {
                        const picked = pickOn(grammar, spec, mapId, layerId, panes);
                        if (picked) emitInteraction(selection, picked.table, { kind: 'map', index: picked.index, entry: picked.entry });
                    });
                    const off2 = grammar.interactions.on('plot:selection', ({ plotId, selection }) => {
                        const brushed = plotId === undefined
                            ? (plotEntries(spec).length > 0 ? { index: 0, entry: plotEntries(spec)[0] } : null)
                            : plotEntryOf(spec, panes, plotId);
                        if (brushed) emitInteraction(selection, brushed.entry?.dataRef, { kind: 'plot', ...brushed });
                    });
                    interactionOffRef.current = [off1, off2];
                }

                // The map or plot drawn again shows none of the pick or brush
                // this node sent before: it says so, as a Vega chart does when
                // it compiles (hook/useVega.ts), so the views linked to it stop
                // showing that selection too. A draw for a Map Editor node's
                // edit keeps it: the pick stays to edit again, and lights up
                // on the new map below.
                // Each view's: every select that held a selection is sent
                // empty, under the key it was sent under.
                const lost = preview ? [] : [...heldSelectsRef.current].filter(([, select]) => holdsSelection(select));
                if (!preview) heldSelectsRef.current = new Map();
                if (lost.length > 0) {
                    const d = dataRef.current;
                    d.interactionsCallback?.(Object.fromEntries(lost.map(([key, select]) => [key, {
                        type: VisInteractionType.UNDETERMINED,
                        data: [],
                        priority: 1,
                        source: NodeType.AUTK_GRAMMAR,
                        layerRef: select.layerRef,
                    }])), d.nodeId);
                }

                // What the map was fed, as it came: the edits a Map Editor
                // node feeding it made, as its last run made them.
                handOnRun(data.input ?? null);
                // A selection still active from before this draw lights up
                // the new map too, as a Vega chart re-applies its own.
                syncHighlightsNow();
                // A partial drop still drew something; say what it lost rather
                // than leaving the console as the only record. It rides as the
                // success output, since a render node's body is its map.
                const note = partialRenderNote(renderCounts);
                if (note) summary = note;
            } else {
                grammarRef.current = null;
                specRef.current    = null;
                const passes: any[] = Array.isArray(spec.compute) ? spec.compute : [];
                if (specDataSources.length > 0 && passes.length === 0) {
                    // Data-only node: emit the data downstream.
                    // Backend-loaded data lives in DuckDB; pass the artifact
                    // reference downstream (matches main's AUTK_DB) so the next node
                    // loads it straight from the DB. The in-browser fallback holds
                    // bare layers, which a downstream Data Pool cannot read: it sat
                    // on "No data yet" under this node's green Done (#248). So the
                    // fallback hands over the same shape the compute-only branch
                    // below does.
                    const out = backendRef
                        ?? (backendLayers
                            ? (await toPoolOutput(backendLayers, data.jsInterpreter, data.nodeId)) ?? backendLayers
                            : null);
                    handOnRun(out);
                    // The backend path hands back an artifact ref, not the
                    // tables, so name what the spec asked autk-db to create,
                    // and each input table a join wrote its columns onto -
                    // a short load has already failed above, so these exist.
                    // Their rows are unknown there, so no emptiness is claimed;
                    // only layers in hand are counted.
                    const tables = backendLayers
                        ? backendLayers.map((l) => countedItem(
                            autkTableKey(l.workspace, l.name), loadedRows(l), l.type === RASTER_TABLE ? 'cells' : 'features',
                        ))
                        : sectionTablesHandedOn(specDataSources);
                    summary = describeAutkRun('Loaded', 'table', tables);
                    summaryListsItems = tables.length > 0;
                    runCounts = {
                        sourceRows: backendLayers
                            ? totalCount(backendLayers.map((l) => loadedRows(l)))
                            : undefined,
                    };
                } else {
                    // Compute step: its passes run over the layers it holds, those
                    // its input brings and those its own data section loaded, and
                    // it hands every one on, each pass's result where autk-grammar
                    // writes it (applyComputeBlocks). A step with a data section
                    // reads its input only when it names a table neither that
                    // section nor a pass makes (autkNeedsInput). Skip the extra
                    // AutkDb round-trip: upstream layers (from backend, or the
                    // in-browser fallback) are already normalized and exploded, and
                    // re-loading them through DuckDB + the buildings clusterer can
                    // strip custom per-feature properties. Apply WGSL blocks
                    // directly so the outputs (feature.properties.compute.<col>)
                    // reach downstream untouched.
                    const readsItsInput = specDataSources.length === 0 || autkNeedsInput(spec);
                    let computeInput = data.input && readsItsInput
                        ? autkSourcesFrom(await readInput(data.input), spec, { alias: false })
                        : null;
                    // Compute blocks run over layers' features; a raster has none.
                    if (computeInput && computeInput.rasters.length > 0) {
                        const note = 'Left out: the raster '
                            + computeInput.rasters.map((r) => r.outputTableName).join(', ')
                            + ', since a compute step works on layers. Draw it on a map instead.';
                        computeInput = {
                            ...computeInput,
                            inputProblem: [computeInput.inputProblem, note].filter(Boolean).join(' '),
                        };
                    }
                    if (computeInput?.emptyReason && computeInput.sources.length === 0) {
                        inputProblemRef.current = { reason: computeInput.emptyReason, detail: computeInput.detail };
                    }
                    // Each layer keeps the workspace it came in, which a pass
                    // names to read it and which it is handed on in.
                    const upstream = (computeInput?.sources ?? []).map((source) => ({
                        name: source.outputTableName,
                        type: source.layerType ?? 'polygons',
                        geojson: source.geojsonObject,
                        ...(source.workspace ? { workspace: source.workspace } : {}),
                    }));
                    // The layers its data section loaded, which a layer of the
                    // input of the same name and workspace gives way to, as on a map.
                    const own = specDataSources.length > 0
                        ? (await loadedLayers()).map((l) => ({
                            name: l.name, type: l.type ?? 'polygons', geojson: l.geojson,
                            ...(l.workspace ? { workspace: l.workspace } : {}),
                        }))
                        : [];
                    const layerKey = (l: { name: string; workspace?: string }) => autkTableKey(l.workspace, l.name);
                    const ownKeys = new Set(own.map(layerKey));
                    let layers = [...upstream.filter((l) => !ownKeys.has(layerKey(l))), ...own];
                    // The rows at hand, counted before the empty-layer drop
                    // below hides them, and of those the ones its data section
                    // loaded; a raster's rows are its cells (loadedRows), as a
                    // node that only loads data counts them. No layer at all
                    // (nothing connected, or an input this node cannot read)
                    // is no claim, not zero.
                    const rowsIn = layers.length > 0
                        ? totalCount(layers.map((l) => loadedRows(l)))
                        : computeInput?.inputProblem ? 0 : undefined;
                    const sourceRows = specDataSources.length > 0
                        ? totalCount(own.map((l) => loadedRows(l)))
                        : undefined;
                    // Drop empty layers (autk-db throws on an empty
                    // FeatureCollection, and an empty layer would surface as a
                    // blank tab in the downstream Data Pool); the compute below
                    // then only runs on layers that have features.
                    const held = new Set([
                        ...layers.map(layerKey),
                        ...writtenTables(spec).map((t) => autkTableKey(t.workspace, t.name)),
                    ]);
                    const emptyLayers = layers.filter((l) => !hasFeatures(l.geojson));
                    if (emptyLayers.length > 0) {
                        console.warn(
                            '[autk-grammar] compute node dropping empty layer(s): '
                            + emptyLayers.map((l) => l.name).join(', '),
                        );
                        layers = layers.filter((l) => !emptyLayers.includes(l));
                    }
                    if (passes.length > 0) {
                        const computeFailures: string[] = [];
                        // The passes run over the layers that have features, as
                        // a map node's do (passesAtHand): one over a dropped
                        // layer does not run, and a render layer of one is left
                        // out of its pass. Each by key, in its workspace.
                        const runs = passesAtHand(passes, held, new Set(layers.map(layerKey)));
                        layers = await applyComputeBlocks(
                            layers, runs, computeFailures,
                        );
                        if (computeFailures.length > 0) {
                            // Emitting here would hand downstream nodes the
                            // untouched input under a green "Done" badge.
                            const message =
                                'Compute failed: ' + computeFailures.join('; ');
                            emit({ code: 'error', content: message });
                            showToast(message, 'error');
                            return;
                        }
                    }
                    summary = describeAutkRun(
                        'Computed',
                        'layer',
                        layers.map((l) => countedItem(
                            autkTableKey(l.workspace, l.name), loadedRows(l), l.type === RASTER_TABLE ? 'cells' : 'rows',
                        )),
                    );
                    summaryListsItems = layers.length > 0;
                    runCounts = {
                        rowsIn,
                        ...(sourceRows !== undefined ? { sourceRows } : {}),
                        drawn: totalCount(layers.map((l) => loadedRows(l))),
                        ...(computeInput?.inputProblem ? { inputProblem: computeInput.inputProblem } : {}),
                    };
                    // An empty result is not passed on: downstream would get
                    // nothing under this node's error. The verdict below says why.
                    if (!renderOutcome(runCounts).empty) {
                        const out = await toPoolOutput(layers, data.jsInterpreter, data.nodeId);
                        handOnRun(out ?? layers);
                    }
                }
            }

            // dev/136: a data or compute run that produced only EMPTY tables
            // produced nothing. The counts ride as data, so the same rules
            // that judge a map decide who is at fault: a data node's own
            // sources loading nothing is `empty-source`, a compute node fed
            // nothing is `no-input-rows`.
            const outcome = runCounts ? renderOutcome(runCounts) : null;
            if (outcome?.empty) {
                showInputProblem(classifyAutkSpec(spec));
                const message = summary && summaryListsItems
                    ? `${outcome.message} ${summary.replace(/\.+$/, '')}.`
                    : outcome.message;
                emit({ code: 'error', content: message,
                       kind: emptyRenderKind(outcome.cause) } as any);
                showToast(message, 'error');
                return;
            }
            // A render node reports through its map/plot; a data or compute
            // node has only this line to show that it did something (#282).
            setRunSummary(summary);
            emit({ code: 'success', content: summary ?? '' });
        } catch (err: any) {
            const msg = describeError(err);
            logFailure(msg);
            emit({ code: 'error', content: msg });
            showToast(msg, 'error');
        }
    };

    /**
     * List a run among the node's runs in the provenance drawer, under its id, as every node
     * lists its runs (#448, #860) and as the Vega-Lite node files its draws
     * (hook/useVega): its times and its document as written. A failed run is
     * listed too, as a code node's is, with "error" as what it made.
     */
    const recordRun = (run: { startedAt: Date; code: string }, outcome: string) => {
        if (!recordsProvenance) return;
        const type = (data.input as any)?.dataType;
        const typesIn: string[] = type == null ? [] : Array.isArray(type) ? type : [type];
        nodeExecProv(
            formatDate(run.startedAt),
            formatDate(new Date()),
            workflowNameRef?.current ?? '',
            data.nodeId,
            mapTypes(typesIn),
            mapTypes(outcome === 'error' ? ['error'] : typesIn),
            run.code,
        );
    };

    /**
     * Run the spec, and always leave the "exec" state (#271).
     *
     * The runner (FlowProvider's Run All) has no promise to await: it waits
     * for this node's output to flip to success or error, and until then the
     * whole run - and every later Run / Run All click - is held. runGrammar
     * has several early returns and awaits a WebGPU probe, a dynamic import
     * and the library's own async init, any of which can throw or hang in
     * ways its inner try/catch never sees. So the terminal output is
     * guaranteed here, in a finally, rather than hoped for in the body.
     *
     * With *preview*, the map is drawn again for an edit a Map Editor node
     * feeding it made: a draw and nothing else. No run is filed, the node's
     * state stays as its last run left it, and nothing is handed on.
     */
    const drawGrammar = async (specString: string, preview = false): Promise<void> => {
        // A node that has left the page starts no run: a draw asked for as
        // it left, or a run queued behind the one under way (see mountedRef).
        if (leftPage()) return;
        const text = typeof specString === 'string' ? specString : JSON.stringify(specString);
        if (runningRef.current) {
            // A run is under way (a redraw on new input, or a Play): run once
            // more when it ends, with the latest document, rather than two runs
            // racing for the same canvas. A run asked for wins over a redraw.
            const queued = pendingSpecRef.current;
            pendingSpecRef.current = { spec: text, preview: preview && (queued?.preview ?? true) };
            return;
        }
        lastSpecRef.current = text;
        hasRunRef.current = true;
        runningRef.current = true;
        inputProblemRef.current = null;
        let settled = false;
        // The run as the provenance drawer lists it, once, as it ends (#860). A
        // dropped run is not listed, and neither is a redraw.
        const run = { startedAt: new Date(), code: writtenRef.current, listed: false };
        const emit = (o: { code: string; content: string }) => {
            // A dropped run says nothing (see mountedRef).
            if (leftPage()) return;
            if (o.code === 'success' || o.code === 'error') settled = true;
            if (preview) return;
            if (o.code === 'error' && marksNodeErrored) markNodeErrored?.(data.nodeId);
            nodeState.setOutput(o);
            if (settled && !run.listed) {
                run.listed = true;
                recordRun(run, o.code);
            }
        };
        // The net itself lives in autkRunSettlement so it can be tested; see the
        // note there for why it is unreachable through this hook.
        try {
            await runAndAlwaysSettle(() => runGrammar(specString, emit, preview), {
                settled: () => settled,
                onError: (msg) => {
                    logFailure(msg);
                    emit({ code: 'error', content: msg });
                    showToast(msg, 'error');
                },
                onUnreported: () => {
                    emit({ code: 'error', content: UNREPORTED_MESSAGE });
                },
            });
        } finally {
            runningRef.current = false;
        }
        const next = pendingSpecRef.current;
        pendingSpecRef.current = null;
        if (next != null) await drawGrammarRef.current(next.spec, next.preview);
    };
    const applyGrammar = (specString: string): Promise<void> => drawGrammar(specString);
    // The run queued behind the one under way goes through the latest render's
    // drawGrammar, so it reads the node's input as it is when it starts, not
    // as it was when the run under way began.
    const drawGrammarRef = useRef(drawGrammar);
    drawGrammarRef.current = drawGrammar;

    // An edit made in a Map Editor node feeding this map, or an edit's code
    // put back: the map, once drawn, draws again once the edits stop coming,
    // keeping its view and what was set on its layers. A redraw only: no run.
    const editVersion = feedsVersion(feeds);
    const editVersionRef = useRef(editVersion);
    useEffect(() => {
        if (editVersionRef.current === editVersion) return;
        editVersionRef.current = editVersion;
        if (!hasRunRef.current || lastSpecRef.current == null || grammarRef.current == null) return;
        const timer = setTimeout(() => {
            savedLayersRef.current = snapshotMapLayers(grammarRef.current, editIndexOf(panesRef.current));
            if (lastSpecRef.current != null) void drawGrammarRef.current(lastSpecRef.current, true);
        }, 120);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editVersion]);
    useEffect(() => () => {
        if (editFedRef.current) registerEditMap(data.nodeId, null);
    }, [data.nodeId]);
    // The Map Editor node's interaction edge moved to another view of the
    // node, once it is drawn: the node edits the map the edge names now.
    useEffect(() => {
        if (!editFedRef.current || !grammarRef.current) return;
        registerEditedMap(grammarRef.current, specRef.current, panesRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editView]);

    // As the Map Editor node feeding the map asks: Show only this layer hides
    // the map's other layers, and the layer an action works on, or the one
    // shown alone, is the one that picks, so the map lights the node's pick
    // and a rule's matches there. Each layer is back as it was when the node
    // stops asking.
    useEffect(() => {
        if (!editFed) return;
        const apply = () => {
            const session = mapSession(data.nodeId);
            const solo = session?.solo ?? null;
            const picking = session?.active?.table ?? solo;
            const current = soloRef.current;
            if ((current?.solo ?? null) === solo && (current?.picking ?? null) === picking) return;
            // On the map the node edits.
            const index = editIndexOf(panesRef.current);
            const before = current?.before
                ?? (solo !== null || picking !== null ? snapshotBeforeSolo(grammarRef.current, index) : null);
            soloRef.current = solo !== null || picking !== null ? { solo, picking, before } : null;
            showAsEditsAsk(grammarMaps(grammarRef.current)[index], { map: mapEntries(specRef.current)[index] }, current, before);
        };
        apply();
        return onMapSession(data.nodeId, apply);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data.nodeId, editFed]);

    /** Re-probe WebGPU and, if it is there now, run the last spec (#272). */
    const checkGpuAgain = async () => {
        setGpuChecking(true);
        try {
            const support = await reprobeWebGpuSupport();
            if (support.supported) {
                setGpuBlocked(null);
                if (lastSpecRef.current != null) await applyGrammar(lastSpecRef.current);
            } else {
                const message = support.reason ?? 'Autark nodes need WebGPU, which this browser does not provide.';
                setGpuBlocked(message);
                showGpuToast(message);
            }
        } finally {
            setGpuChecking(false);
        }
    };

    // Curio → grammar: which rows to highlight, from two places. A Data Pool
    // marks each feature interacted:'1'/'0' and re-emits its rows, so the input
    // carries the flags. A chart joined to this one by a direct interaction edge
    // sends its selection as `data.interactions`, matched against this node's
    // own rows the way the pool matches (utils/selectionMatch). A row is
    // highlighted when either says so; nothing is redrawn for it.
    //
    // Per layer: a multi-layer wrapper carries flags on the layer the brush was
    // for, and an Autark pick names its layer, so a roads-only brush lights up
    // roads alone. A selection that names no layer (a Vega chart's) lands on the
    // first, as the Data Pool does.
    //
    // Per view: a selection delivered on the node's own dot reaches every view,
    // each lighting the rows it draws of the table the selection lands on. One
    // delivered on a view's dot (`toView`, providers/flow/interactionRoutes)
    // reaches that view alone, on the table it names when the view draws it,
    // else on the view's own: a map's picking layer, a plot's table. The view
    // then acts as if the selection were made in it: the grammar's call for it
    // carries it on to the views the node's `links` join it to. So the grammar
    // is asked only for the views whose rows changed, every clear before any
    // light (autkViews `lightViews`).
    const syncHighlights = async () => {
        const grammar = grammarRef.current;
        const spec    = specRef.current;
        const current = dataRef.current;
        if (!grammar || !spec || !current.input) return;
        // A later sync lights instead of this one: it reads newer selections.
        const turn = ++syncTurnRef.current;

        // The layers as the map drew them, a Map Editor node's edits made. A
        // map drawn again meanwhile lights them itself.
        const layers = autkSourcesFrom(await readDrawnInput(current.input), spec).sources;
        if (layers.length === 0 || grammarRef.current !== grammar) return;

        const incoming: Array<IncomingSelection & { toView?: string }> = Array.isArray((current as any).interactions)
            ? (current as any).interactions
            : [];
        const { whole, byView } = receivedByView(incoming, panesRef.current);
        // Each layer by key (tableKeyOf): a selection that names its layer
        // lands on the first layer of that name, and an Autark node of
        // several views sends a select per view, each on its own layer
        // (utils/autkSelects).
        const direct = new Map<string, IncomingSelection[]>();
        for (const { layer: named, selection } of byAutkLayer(whole)) {
            const target = tableKeyOf(layers.find((l) => l.outputTableName === named) ?? layers[0]);
            direct.set(target, [...(direct.get(target) ?? []), selection]);
        }
        // The rows a view receives alone, by the key of the table they land
        // on, matched against the input table that holds that table's rows.
        const featuresOf = (key: string) =>
            layers.find((l) => tableKeyOf(l) === (writtenFromRef.current[key] ?? key))?.geojsonObject;
        const receivedRows = (pane: string, tables: Array<{ name: string; key: string }>, own: string | undefined) => {
            const lands = new Map<string, IncomingSelection[]>();
            for (const { layer: named, selection } of byAutkLayer(byView.get(pane) ?? [])) {
                const key = tables.find((table) => table.name === named)?.key ?? own;
                if (key !== undefined) lands.set(key, [...(lands.get(key) ?? []), selection]);
            }
            const rows = new Map<string, number[]>();
            for (const [key, selections] of lands) {
                const fc = featuresOf(key);
                if (fc) rows.set(key, matchSelections(selections, featureRows(fc)));
            }
            return rows;
        };
        const joined = (a: readonly number[] | undefined, b: readonly number[] | undefined) =>
            [...new Set([...(a ?? []), ...(b ?? [])])];

        // Input rows per layer; each target turns them into its own positions.
        const rowsByLayer = new Map<string, number[]>();
        for (const layer of layers) {
            const fc = layer.geojsonObject;
            const key = tableKeyOf(layer);
            const flagged = ((fc.features ?? []) as any[]).reduce<number[]>((acc, f, i) => {
                if (f.properties?.interacted === '1') acc.push(i);
                return acc;
            }, []);
            const selected = direct.has(key) ? matchSelections(direct.get(key)!, featureRows(fc)) : [];
            rowsByLayer.set(key, [...new Set([...flagged, ...selected])]);
        }
        // A table a pass wrote lights the rows of the table it holds the rows
        // of, both by key.
        for (const [key, root] of Object.entries(writtenFromRef.current)) {
            rowsByLayer.set(key, rowsByLayer.get(root) ?? []);
        }
        // A map layer names the rows it lights by the positions its map drew
        // them at, read back once a draw (`drawnRowsOf`), in its map's
        // workspace, and lights them on its own map alone, so two maps of one
        // table light only their own rows: the rows every view gets, and those
        // its map receives alone.
        const mapRefs = mapLayerRefs(spec).map(({ index, entry, ref }) => ({
            index, ref, workspace: autkWorkspaceOf(entry), key: autkTableKey(autkWorkspaceOf(entry), ref.dataRef),
        }));
        const mapReceived = mapEntries(spec).map((entry, index) => {
            const workspace = autkWorkspaceOf(entry);
            const own = pickLayerOf(entry);
            return receivedRows(
                `map:${index}`,
                mapRefs.filter((ref) => ref.index === index).map(({ ref, key }) => ({ name: ref.dataRef, key })),
                own === undefined ? undefined : autkTableKey(workspace, own),
            );
        });
        const mapRows = mapRefs.map(({ index, key }) => joined(rowsByLayer.get(key), mapReceived[index]?.get(key)));
        const drawnOrders = await Promise.all(mapRefs.map(({ index, ref, workspace }, at) =>
            (mapRows[at].length > 0 ? drawnRowsOf(grammar, workspace, ref.dataRef, index) : null)));
        if (grammarRef.current !== grammar) return;
        const views: LitView[] = mapRefs.map(({ index, ref, key }, at) => {
            const positions = tablePositions(mapRows[at], drawnOrders[at] ?? loadOrdersRef.current[key]?.map);
            // With nothing coming in, from the node's input or along an edge
            // to this view, a layer keeps the features its document picks
            // (`pickedComps`), which the grammar's run lit as it drew it, as
            // a plot keeps its `selection` below: they are already positions
            // among the features the layer draws.
            const picked: number[] = Array.isArray(ref.pickedComps) ? ref.pickedComps.filter(Number.isInteger) : [];
            return { kind: 'map' as const, index, table: ref.dataRef, positions: positions.length > 0 ? positions : picked };
        });
        for (const [index, plotSpec] of plotEntries(spec).entries()) {
            // A plot of a table a pass wrote holds the rows the pass kept.
            const plotTable = autkTableKey(autkWorkspaceOf(plotSpec), plotSpec.dataRef);
            const rows = joined(
                rowsByLayer.get(plotTable),
                receivedRows(`plot:${index}`, [{ name: plotSpec.dataRef, key: plotTable }], plotTable).get(plotTable),
            );
            const written = writtenRowsOf(grammar, plotSpec.dataRef, autkWorkspaceOf(plotSpec));
            const kept = written ? await written : null;
            if (grammarRef.current !== grammar) return;
            const sel = tablePositions(rows, kept ?? loadOrdersRef.current[plotTable]?.load);
            // With nothing coming in, from the node's input or along an edge
            // to this view, a plot keeps the selection its document writes
            // (`selection`), which the grammar's run applied as it drew it:
            // the plot selects those rows again, and the layers it is linked
            // to light them, as a selection set in the plot does. Its
            // `selection` is already positions among the rows the plot draws.
            const own: number[] = Array.isArray(plotSpec.selection) ? plotSpec.selection : [];
            views.push({
                kind: 'plot',
                // The grammar knows a plot by its id, else by its table (plotKey).
                plot: plotKey(panesRef.current, index) ?? plotSpec.dataRef,
                positions: sel.length > 0 ? sel : own,
            });
        }
        if (syncTurnRef.current !== turn) return;
        // What this grammar's views light, kept for the next sync; a draw makes
        // a new grammar, whose views light nothing yet.
        if (litRef.current.grammar !== grammar) litRef.current = { grammar, lit: new Map() };
        lightViews(grammar, views, litRef.current.lit);
    };
    const syncHighlightsNow = () => {
        syncHighlights().catch((err) => {
            // Same reason as GrammarEditor's: an escaped rejection here
            // surfaces as the dev-server overlay rather than as a node error.
            console.error("[autk-grammar] interaction sync failed:", err);
        });
    };
    // A selection this node made, back through a Data Pool, is what it already
    // shows. A plot's brush IS its selection, so putting it back replaces the
    // brush, and an empty one (a press between two bars) erases the brush the
    // pointer is still drawing. A redraw and a direct selection still apply it.
    useEffect(() => {
        if (selectionEchoSource(data.input) === data.nodeId) return;
        syncHighlightsNow();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data.input]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    useEffect(syncHighlightsNow, [(data as any).interactions]);

    // What this node's map draws and lights, as autk-map and autk-db hold it,
    // for the e2e tests.
    useEffect(() => {
        // The map *view* names, else the first: its index among the maps the
        // last draw made, its entry, and its layers, each a table of the
        // map's workspace.
        const mapOf = (view: string | number | undefined) => {
            const index = view === undefined ? 0 : mapIndexOf(panesRef.current, view);
            const entry = index < 0 ? undefined : mapEntries(specRef.current)[index];
            const workspace = autkWorkspaceOf(entry);
            const drawn: DrawnTables = {
                features: (table) => drawnFeaturesOf(grammarRef.current, workspace, table),
                rows: (table) => drawnRowsOf(grammarRef.current, workspace, table, view === undefined ? undefined : index),
            };
            return { index, entry, drawn };
        };
        mapStateReaders.set(data.nodeId, {
            state: (view) => {
                const { index, entry, drawn } = mapOf(view);
                if (index < 0) return Promise.resolve(null);
                return view === undefined
                    ? mapStateOf(grammarRef.current, specRef.current, drawn)
                    : mapStateOf(grammarRef.current, { map: entry }, drawn, index);
            },
            featureAt: async (table, position, view) => {
                const { index, drawn } = mapOf(view);
                if (index < 0) return null;
                return drawnFeatureAt(grammarRef.current, table, await drawn.features(table), position,
                    view === undefined ? undefined : index);
            },
            views: () => mapViews(grammarRef.current),
            showFramed: () => showFramedViews(grammarRef.current),
            drawing: (view) => {
                const { index } = mapOf(view);
                return index < 0 ? null : mapDrawingOf(grammarRef.current, index);
            },
            // The tour the map plays, or last played: the grammar keeps the
            // last one played on each map of its run (its `tours`).
            tourEnded: async (view) => {
                const { index } = mapOf(view);
                const tour = index < 0 ? undefined : (grammarRef.current as any)?.tours?.[index];
                if (!tour?.done) return false;
                await tour.done;
                return true;
            },
            handed: (table, view) => {
                const { index, entry } = mapOf(view);
                if (index < 0) return Promise.resolve(null);
                return handedFeaturesOf(grammarRef.current, autkTableKey(autkWorkspaceOf(entry), table));
            },
        });
        return () => {
            mapStateReaders.delete(data.nodeId);
            turnBack.delete(data.nodeId);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [data.nodeId]);

    // #662: a selection tag on this node reads the features of the layer its
    // pick or brush came from, the rows a direct selection is matched against
    // above (utils/references/viewSelections). A pick names their positions,
    // or their key values when the view names selectFields.
    useEffect(
        () =>
            provideViewRows(data.nodeId, async (layer) => {
                const spec = specRef.current;
                const input = dataRef.current.input;
                if (!spec || !input) return null;
                const sources = autkSourcesFrom(await readDrawnInput(input), spec).sources;
                // A view's tables are of its workspace: that of the views
                // that draw the layer, else of the first view.
                const layerName = layer ?? selectionLayerOf(spec);
                const workspace = workspaceOfLayer(spec, layerName);
                const named = rowsTableOf(layerName, workspace);
                const source = sources.find((s) => named !== undefined && tableKeyOf(s) === autkTableKey(workspace, named))
                    ?? sources[0];
                if (!source) return null;
                const fc = source.geojsonObject as { features?: any[] };
                const first = (fc.features ?? []).find((f) => f?.properties);
                return { rows: featureRows(fc), columns: Object.keys(first?.properties ?? {}) };
            }),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [data.nodeId],
    );

    // A starter document chosen from the arriving input, the way every grammar
    // node fills an empty editor (hook/useStarterSpec): once, only into an
    // empty editor, only after an input has arrived, never over a document
    // written in from outside nor for a node that opens with its package's
    // starter. A bundle is read the way the run reads it, so it downloads
    // once; a single frame needs only its preview.
    const starterSpec = useStarterSpec({
        input: data.input,
        buffer: nodeState.code,
        written: data.defaultCode,
        enabled: !opensWithPackageStarter(data.nodeType),
        read: (input) => {
            const type = (input as any)?.dataType;
            return type === 'list' || type === 'dict' || type === 'outputs'
                ? readInput(input)
                : readAutkInput(input, { preview: true });
        },
        choose: autkStarterText,
    });

    // The states before anything is drawn: nothing connected, an upstream that
    // has not run or failed, an input this node cannot read, an empty editor, a
    // document not run yet. Written into the container the map draws into, the
    // way the Vega-Lite node writes into its own (utils/writeEmptyState), so no
    // React state changes while someone types. A document that draws only what
    // it loads itself has nothing to say about an input. The editor counts as
    // holding the starter once one is chosen, as the Vega-Lite node counts it.
    const liveCode = isEmptySpecBuffer(nodeState.code) && starterSpec !== undefined
        ? starterSpec
        : nodeState.code;
    const liveKind = classifyAutkSpecString(liveCode);
    const hasSpec = !isEmptySpecBuffer(liveCode);
    const needsInput = (() => {
        if (!hasSpec) return true;
        try {
            // A chip standing on its own holds its place (utils/autkSpecKind).
            return autkReadsInput(JSON.parse(withChipPlaceholders(liveCode)));
        } catch {
            return true;
        }
    })();
    const hasInput = data.input != null && data.input !== '';
    useEffect(() => {
        if (runningRef.current || gpuBlocked) return;
        // A map, a plot or a run summary is what the body shows then.
        if (grammarRef.current != null || runSummary) {
            noticeRef.current = null;
            return;
        }
        const problem = inputProblemRef.current;
        const reason = resolveGrammarEmptyReason({
            connected,
            upstreamErrored,
            upstreamRunning,
            upstreamStopped,
            onDashboard: !!dashboardOn,
            hasInput,
            hasSpec,
            needsInput,
            hasRun: hasRunRef.current,
            inputProblem: problem?.reason ?? null,
        });
        const detail = reason === 'upstream-stopped' ? upstreamStopped ?? undefined : problem?.detail;
        // On a dashboard, while a step above the map downloads what it reads
        // on its first use, "Computing..." says how far on a line under it.
        const progress = reason === 'upstream-running' ? upstreamDownloads : undefined;
        noticeRef.current = reason == null
            ? null
            : { reason, words: { ...emptyStateWords(reason, liveKind, detail), progress } };
        writeNotice();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [connected, upstreamErrored, upstreamRunning, upstreamStopped, downloadsSaid, dashboardOn, hasInput, hasSpec, needsInput, liveKind, gpuBlocked, nodeState.output?.code, runSummary]);

    // Forward parent container resizes to AutkMap via a synthetic window.resize.
    // AutkMap binds only to window.resize (and exposes no per-instance resize API),
    // so node-handle drags are otherwise silent — but that dispatch is expensive and
    // fragile: each one makes *every* AutkMap on the page rebuild its WebGPU textures
    // and reconfigure its swapchain. Doing that every frame during a drag stalls the
    // canvas, and reconfiguring mid-render races AutkMap's render loop (its
    // getCurrentTexture() ends up invalidated) — which its render-error latch then
    // swallows, leaving the map blank/white.
    //
    // So: keep the *cheap* CSS sizing on every tick (the width/height:100% canvas
    // stretches to fill the node during the drag), but fire the *expensive*
    // window.resize only once the size has settled, and on a macrotask (setTimeout)
    // rather than rAF — outside AutkMap's render window — so the GPU rebuild happens
    // exactly once, cleanly, and the canvas snaps crisp.
    useEffect(() => {
        const wrapper = wrapperRef.current;
        const target = wrapper?.parentElement;
        if (!wrapper || !target || typeof ResizeObserver === 'undefined') return;

        let lastW = -1, lastH = -1;
        let timer: ReturnType<typeof setTimeout> | null = null;

        const commit = () => {
            timer = null;
            const w = target.clientWidth, h = target.clientHeight;
            if (w <= 0 || h <= 0) return;
            // No-op guard: a same-size commit would still rebuild every map's GPU
            // textures, so drop it.
            if (w === lastW && h === lastH) return;
            lastW = w; lastH = h;
            window.dispatchEvent(new Event('resize'));
        };

        const onResize = () => {
            // Cheap: track the parent every tick so the 100% canvas fills the node.
            const w = target.clientWidth, h = target.clientHeight;
            if (w > 0 && h > 0) { wrapper.style.width = w + 'px'; wrapper.style.height = h + 'px'; }
            // Hidden (a collapsed scenario's member, #662): shown again, even at
            // the size it had, the map gets its one GPU resize.
            else { lastW = -1; lastH = -1; }
            // Expensive: debounce the GPU rebuild until the drag settles.
            if (timer) clearTimeout(timer);
            timer = setTimeout(commit, 150);
        };

        // Mount: size immediately and do one initial GPU resize.
        const w0 = target.clientWidth, h0 = target.clientHeight;
        if (w0 > 0 && h0 > 0) { wrapper.style.width = w0 + 'px'; wrapper.style.height = h0 + 'px'; }
        commit();

        const ro = new ResizeObserver(onResize);
        ro.observe(target);
        return () => { ro.disconnect(); if (timer) clearTimeout(timer); };
    }, []);

    // On the page from the commit that mounts the node to the one that takes
    // it off, which removes its canvas too (see mountedRef). A passive
    // effect's cleanup runs later, and a run may go on in between.
    useLayoutEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    // Unsubscribe grammar event listeners and remove the map canvas's window
    // pointer listeners when the node is removed from the canvas (a deleted
    // node, a closed dataflow), and destroy its maps.
    useEffect(() => {
        return () => {
            interactionOffRef.current.forEach(f => f());
            pickFixCleanupRef.current?.();
            destroyLastMaps();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Stable JSX reference across incidental re-renders, but identity changes
    // on run completion so NodeEditor switches to the output tab automatically.
    const contentComponent = React.useMemo<React.ReactNode>(
        () =>
            gpuBlocked ? (
                // Styled after providers/BackendHealthBanner: an explanation the
                // user can act on, in the node, rather than an empty box. The red
                // "Error" chip on the node header comes for free from the output
                // code set alongside this.
                <div
                    role="alert"
                    className="nodrag nopan nowheel"
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 8,
                        padding: '14px 16px',
                        margin: 8,
                        border: '1px solid var(--curio-danger, #c0392b)',
                        borderRadius: 'var(--curio-radius-md, 6px)',
                        background: 'var(--curio-danger-bg, rgba(192, 57, 43, 0.08))',
                        color: 'var(--curio-danger-strong, #922b21)',
                        fontSize: 'var(--curio-font-size-md, 13px)',
                        lineHeight: 1.45,
                        overflow: 'auto',
                    }}
                >
                    <strong>WebGPU is not available</strong>
                    <span>{gpuBlocked}</span>
                    <button
                        type="button"
                        className="nodrag nopan"
                        aria-label="Check WebGPU again"
                        disabled={gpuChecking}
                        onClick={() => { void checkGpuAgain(); }}
                        style={{
                            alignSelf: 'flex-start',
                            padding: '4px 10px',
                            border: '1px solid currentColor',
                            borderRadius: 'var(--curio-radius-sm, 4px)',
                            background: 'transparent',
                            color: 'inherit',
                            cursor: gpuChecking ? 'progress' : 'pointer',
                        }}
                    >
                        {gpuChecking ? 'Checking…' : 'Check again'}
                    </button>
                </div>
            ) : (
                // The wrapper is always mounted - applyGrammar owns its
                // children (canvas / plot div) and empties it on every run - so
                // the data/compute feedback is a SIBLING React owns, not a child
                // the next run would wipe (#282). A map or plot fills the node
                // body, as a Vega-Lite chart does (#534): with a floor, the
                // drawing ran on under the node's footer. A data/compute node
                // has nothing to draw there, so the summary is the body.
                <div
                    className="nodrag nopan nowheel"
                    style={{
                        display: 'flex', flexDirection: 'column', width: '100%', height: '100%',
                        // The overlay of a Map Editor node feeding the map lies over it.
                        ...(editFed ? { position: 'relative' as const } : {}),
                    }}
                >
                    {specKind === 'data' || specKind === 'compute' ? (
                        runSummary ? (
                            <div
                                data-curio-autk-summary={specKind}
                                style={{
                                    padding: '10px 14px',
                                    fontSize: 'var(--curio-font-size-md, 13px)',
                                    lineHeight: 1.5,
                                    color: 'var(--curio-text-primary, #1E1F23)',
                                    whiteSpace: 'pre-wrap',
                                    overflow: 'auto',
                                    // Same reason as Simple View's text pane
                                    // (#267): the wrapper's `nodrag` frees the
                                    // gesture, but the inherited
                                    // `user-select: none` still has to be
                                    // undone where the text actually is.
                                    userSelect: 'text',
                                    cursor: 'text',
                                }}
                            >
                                {runSummary}
                            </div>
                        ) : null
                    ) : null}
                    <div
                        ref={attachWrapper}
                        style={{
                            position: 'relative',
                            width: '100%',
                            flex: 1,
                            minHeight: 0,
                            overflow: 'hidden',
                        }}
                    />
                    {/* What a Map Editor node feeding the map does on it (#662): over
                        the node's body, or over the pane of the map it edits when
                        the node draws several views. */}
                    {editFed && !editPane ? <MapEditOverlay mapId={data.nodeId} sendSelection={sendEditSelection} /> : null}
                    {editFed && editPane
                        ? createPortal(<MapEditOverlay mapId={data.nodeId} sendSelection={sendEditSelection} />, editPane)
                        : null}
                </div>
            ),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [nodeState.output, gpuBlocked, gpuChecking, runSummary, specKind, editFed, editPane],
    );

    return {
        applyGrammar,
        contentComponent,
        // The rows of panes its views are arranged in, which a notebook cell
        // gives a map's height each.
        viewRows,
        // A dot per view with an id, of a node of several views.
        ...(dynamicHandles ? { dynamicHandles } : {}),
        // Only ever offered for an empty editor, so it cannot displace real
        // work, and it steps aside for a document written in from outside.
        defaultValueOverride: starterSpec,
        // And it is a starter, not the map's document, until someone edits it.
        ...(starterSpec !== undefined ? { defaultValueIsStarter: true } : {}),
        setOutputCallbackOverride: setOutputFromOutside,
    };
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// The spec classifier moved to ``utils/autkSpecKind`` so the dashboard's layout
// pass can ask what kind of step a node is without importing this module and
// with it the WebGPU renderer. Re-exported here because every existing caller,
// including the behaviour tests, imports it from this file.
export type { AutkSpecKind } from '../../utils/autkSpecKind';
export { classifyAutkSpec, classifyAutkSpecString } from '../../utils/autkSpecKind';

// Re-exported so existing importers keep this module as their entry point
// while the implementations live in autkDataCompile.
export { SANDBOX_BACKEND_URL_TOKEN, requestedLayerTables };

// Browser-side wrapper: picks the base URL, then defers to the shared resolver.
function resolveDataSourceUrls(spec: any, forBackend = false): any {
    const base = forBackend
        ? SANDBOX_BACKEND_URL_TOKEN
        : (backendUrl() || 'http://localhost:5002');
    return resolveDataSourceUrlsWithBase(spec, base);
}
