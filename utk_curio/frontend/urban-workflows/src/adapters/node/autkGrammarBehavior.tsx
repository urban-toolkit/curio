import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Feature } from 'geojson';
import { NodeBehaviorHook } from '../../registry/types';
import { detectWebGpuSupport, reprobeWebGpuSupport } from '../../utils/webgpuSupport';
import { useToastContext } from '../../providers/ToastProvider';
import { VisInteractionType, NodeType } from '../../constants';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { useStarterSpec } from '../../hook/useStarterSpec';
import { autkStarterText } from '../../utils/autkDefaultSpec';
import { useFlowContext } from '../../providers/FlowProvider';
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
import { AutkSpecKind, classifyAutkSpec, classifyAutkSpecString } from '../../utils/autkSpecKind';
import { AUTK_UPSTREAM_LAYER } from '../../generated/autkGrammar';
import {
    autkNeedsInput, autkSourcesFrom, documentTableRefs, inputRow, loadableSource, ownTableNames,
    readAutkInput, tablePositions, type LoadOrder, type PreparedAutkInput,
} from '../../utils/autkInput';
import { type GrammarInput } from '../../utils/grammarInput';
import { featureRows, matchSelections, type IncomingSelection } from '../../utils/selectionMatch';
import { selectionEchoSource } from '../../utils/selectionEcho';
import {
    SANDBOX_BACKEND_URL_TOKEN,
    compileDataSpecToAutkDbJs,
    requestedLayerTables,
    resolveDataSourceUrls as resolveDataSourceUrlsWithBase,
} from './autkDataCompile';
import { attachMapInteractionZoomFix } from './autkMapZoom';
import {
    countedItem, describeAutkRun, emptyStateWords, featureCount, hasFeatures, totalCount,
} from './autkRunDescriptions';
import { loadSpecLayers, materializeBackendLayers, runDataInBackend, toPoolOutput } from './autkLayerMaterialize';
import { applyComputeBlocks } from './autkComputeBlocks';

export const useAutkGrammarBehavior: NodeBehaviorHook = (data, nodeState) => {
    const { showToast } = useToastContext();
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
    // Unsubscribe functions returned by grammar.interactions.on(); cleared and
    // re-populated on every applyGrammar call and on unmount.
    const interactionOffRef = useRef<Array<() => void>>([]);
    // Disposer for the map interaction zoom-fix listeners (window-bound), cleared
    // and re-populated on each applyGrammar run with a map, and on unmount.
    const pickFixCleanupRef = useRef<(() => void) | null>(null);
    // Always-current ref to data so grammar event callbacks never close over a
    // stale data object (grammar subscriptions outlive individual renders).
    const dataRef = useRef(data);
    useEffect(() => { dataRef.current = data; });

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
    // How each loaded input table's positions map to the input's rows
    // (loadableSource), by name: a pick or a highlight goes through it, so a
    // position always names the row the Data Pool and the other charts mean.
    const loadOrdersRef = useRef<Record<string, LoadOrder>>({});

    // What the node knows about its input edge, asked the way the Vega-Lite
    // node asks (hook/useGrammarInputState).
    const { connected, upstreamErrored } = useGrammarInputState(data.nodeId);
    // A failed node says so to the nodes it feeds, as a failed code node does.
    const { markNodeErrored } = useFlowContext() as { markNodeErrored?: (nodeId: string) => void };
    // Whether a run has been tried, whether one is under way, and what the last
    // one could not read from its input: the pre-run notice reads these.
    const hasRunRef = useRef(false);
    const runningRef = useRef(false);
    const pendingSpecRef = useRef<string | null>(null);
    const inputProblemRef = useRef<{ reason: NodeEmptyReason; detail?: string } | null>(null);
    // The notice the body should show now, kept so a container that mounts
    // later (the editor remounting its output pane) gets it too.
    const noticeRef = useRef<{ reason: NodeEmptyReason; words: { title?: string; hint?: string } } | null>(null);
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

    const runGrammar = async (
        specString: string,
        emit: (o: { code: string; content: string }) => void,
    ) => {
        let spec: any;
        try {
            spec = typeof specString === 'string' ? JSON.parse(specString) : { ...(specString as any) };
        } catch {
            emit({ code: 'error', content: 'Invalid JSON grammar spec.' });
            return;
        }
        setSpecKind(classifyAutkSpec(spec));
        setRunSummary(null);

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
                showToast(message, 'error');
                return;
            }
        }
        setGpuBlocked(null);

        const nodeId = data.nodeId;
        const mapCanvasId = 'autk-grammar-map-' + nodeId;
        const plotDivId = 'autk-grammar-plot-' + nodeId;
        const hasMaps = spec.map != null;
        const hasPlot = spec.plot != null;

        // Reset container children before each run to release the old WebGPU
        // context. AutkGrammar has no destroy() — replacing the canvas element
        // is the only way to prevent context leaks across re-runs.
        const wrapper = wrapperRef.current;
        if (wrapper) {
            // Dispose the previous run's interaction-zoom-fix listeners (they live on
            // window, so they'd leak and fire for the now-stale canvas otherwise).
            pickFixCleanupRef.current?.();
            pickFixCleanupRef.current = null;
            while (wrapper.firstChild) wrapper.removeChild(wrapper.firstChild);
            clearEmptyState(wrapper);
            if (hasMaps) {
                const canvas = document.createElement('canvas');
                canvas.id = mapCanvasId;
                canvas.style.cssText = 'display:block;width:100%;height:100%;';
                wrapper.appendChild(canvas);
                pickFixCleanupRef.current = attachMapInteractionZoomFix(canvas);
            } else if (hasPlot) {
                const plotDiv = document.createElement('div');
                plotDiv.id = plotDivId;
                plotDiv.style.cssText = 'width:100%;height:100%;overflow:auto;';
                wrapper.appendChild(plotDiv);
            }
        }

        // The authored data sources (osm / pbf / csv / json / geojson-from-URL)
        // are the heavy "data component": they run in the backend sandbox via
        // autk-db. Capture them before we touch spec.data.
        const specDataSources: any[] = Array.isArray(spec.data) ? spec.data : [];

        // The input as the tables the document reads (utils/autkInput): a single
        // frame is `upstream`, a bundle's layers keep their own names, and
        // `upstream` is added only when the document names it. Upstream geojson
        // is data the browser already holds, so it stays client-side and is NOT
        // sent to the backend. A data-only document does not read it.
        let upstreamSources: any[] = [];
        let preparedInput: PreparedAutkInput | null = null;
        const readsInput = hasMaps || hasPlot || specDataSources.length === 0;
        if (data.input && readsInput) {
            try {
                const prepared = autkSourcesFrom(await readInput(data.input), spec);
                preparedInput = prepared;
                if (prepared.emptyReason && prepared.sources.length === 0) {
                    inputProblemRef.current = { reason: prepared.emptyReason, detail: prepared.detail };
                }
                const orders: Record<string, LoadOrder> = {};
                upstreamSources = prepared.sources.map((source) => {
                    const loadable = loadableSource(source);
                    orders[source.outputTableName] = loadable.order;
                    return loadable.source;
                });
                loadOrdersRef.current = orders;
            } catch (e) {
                // What the render then cannot find is what gets reported.
                console.warn('[autk-grammar] reading the input failed:', e);
            }
        }

        const targets: Record<string, string> = {};
        if (hasMaps) targets.map = mapCanvasId;
        if (hasPlot && !hasMaps) targets.plot = plotDivId;

        // Tear down any listeners from the previous run before creating a new
        // grammar instance, so we never hold stale references.
        interactionOffRef.current.forEach(f => f());
        interactionOffRef.current = [];

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
            let backendLayers: Array<{ name: string; type?: string; geojson: any }> | null = null;

            if (specDataSources.length > 0) {
                const resolvedForBackend = resolveDataSourceUrls({ data: specDataSources }, true).data;
                // Key only on the authored data sources: the backend load inlines
                // exactly these (upstream input stays client-side and never reaches the
                // sandbox), so the DuckDB artifact is a pure function of them.
                const cacheKey = JSON.stringify(resolvedForBackend);

                if (dataCacheRef.current && dataCacheRef.current.key === cacheKey) {
                    backendRef = dataCacheRef.current.ref;
                } else {
                    try {
                        if (!data.jsInterpreter) throw new Error('No JS interpreter available for backend data load.');
                        const code = compileDataSpecToAutkDbJs(resolvedForBackend);
                        backendRef = await runDataInBackend(data.jsInterpreter, code, data.nodeId);
                        dataCacheRef.current = { key: cacheKey, ref: backendRef };
                    } catch (e: any) {
                        // Graceful fallback: load the data in-browser (the original
                        // path) so the node still works if the sandbox is down.
                        const backendReason = e?.message ?? String(e);
                        console.warn('[autk-grammar] backend data load failed; falling back to in-browser AutkDb:', backendReason);
                        const resolvedForFrontend = resolveDataSourceUrls({ data: specDataSources }, false).data;
                        dataCacheRef.current = null;
                        try {
                            backendLayers = await loadSpecLayers({ data: resolvedForFrontend });
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

            if (hasMaps || hasPlot) {
                // Render node: feed the backend-loaded data in as inline geojson
                // sources (so the grammar engine never re-loads from URL), then run
                // compute/map/plot in the browser. Backend layers are already
                // projected to the workspace CRS (EPSG:3395).
                let dataSectionSources = upstreamSources;
                // The sources this node's own data section loaded, as opposed to
                // what arrived from upstream: an empty one is the document's fault.
                let ownSources: any[] = [];
                if (specDataSources.length > 0) {
                    let layers: Array<{ name: string; type?: string; geojson: any }> = [];
                    try {
                        layers = await materializeBackendLayers(backendLayers, backendRef);
                    } catch {
                        layers = [];
                    }
                    // Self-heal: if the backend ref produced no usable layers (artifact
                    // evicted, session changed, or a serialization mismatch), drop the
                    // cache and load in-browser so the node renders instead of silently
                    // showing an empty map/plot. Only applies to the backend-ref path
                    // (backendLayers == null means we did not already fall back).
                    if (layers.length === 0 && backendLayers == null) {
                        console.warn('[autk-grammar] backend layers empty/unresolvable; falling back to in-browser AutkDb');
                        dataCacheRef.current = null;
                        const resolvedForFrontend = resolveDataSourceUrls({ data: specDataSources }, false).data;
                        layers = await loadSpecLayers({ data: resolvedForFrontend });
                    }
                    // coordinateFormat must reflect the coordinates as loaded
                    // (autk-db returns layers in the workspace CRS, EPSG:3395
                    // meters): the layers carry a crs stamp set by the loader,
                    // which detectCoordinateFormat reads (falling back to the
                    // coordinate-magnitude heuristic).
                    const backendAsSources = layers.map((l) => ({
                        type: 'geojson',
                        geojsonObject: l.geojson,
                        outputTableName: l.name,
                        coordinateFormat: detectCoordinateFormat(l.geojson as any),
                        ...(l.type && l.type !== 'polygons' ? { layerType: l.type } : {}),
                    }));
                    ownSources = backendAsSources;
                    dataSectionSources = [...upstreamSources, ...backendAsSources];
                }
                // What the document can draw from, counted BEFORE any source is
                // dropped: an empty table still exists, so a ref to it is not a
                // ref to data the dataflow does not produce (that would be rule
                // 1, `no-layers`, blaming the wrong thing). `rows` is undefined
                // when the collection could not be counted.
                const tableRows = new Map<string, { rows: number | undefined; own: boolean }>();
                for (const s of dataSectionSources) {
                    if (typeof s?.outputTableName !== 'string' || !s.outputTableName) continue;
                    tableRows.set(s.outputTableName, {
                        rows: featureCount(s.geojsonObject),
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
                // On a 1 cm grid, so autk-db's second clip of these already
                // clipped layers holds (see utils/geoPrecision).
                spec = { ...spec, data: dataSectionSources.map(snapSourceToGrid) };
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
                // dropped rendered a grey canvas under a green "Done".
                const requestedRefs: string[] = [
                    ...(Array.isArray(spec.map?.layerRefs)
                        ? spec.map.layerRefs
                            .map((r: any) => r?.dataRef)
                            .filter((r: any): r is string => typeof r === 'string' && !!r)
                        : []),
                    ...(spec.plot?.dataRef ? [String(spec.plot.dataRef)] : []),
                ];
                // Every table this node holds, empty ones included, is what the
                // document could have named; only the non-empty ones can be
                // handed to the grammar.
                const knownNames = new Set<string>(tableRows.keys());
                const availableRefs: string[] = [...knownNames];
                if (knownNames.size > 0) {
                    const availableNames = new Set<string>(
                        dataSectionSources
                            .map((s: any) => s?.outputTableName)
                            .filter(Boolean),
                    );
                    if (spec.map && Array.isArray(spec.map.layerRefs)) {
                        const dangling = spec.map.layerRefs.filter(
                            (r: any) => r?.dataRef && !knownNames.has(r.dataRef),
                        );
                        const empty = spec.map.layerRefs.filter(
                            (r: any) => r?.dataRef && knownNames.has(r.dataRef)
                                && !availableNames.has(r.dataRef),
                        );
                        if (dangling.length > 0) {
                            console.warn(
                                '[autk-grammar] dropping map layerRef(s) to unavailable table(s): '
                                + dangling.map((r: any) => r.dataRef).join(', ')
                                + ' - available: ' + [...availableNames].join(', '),
                            );
                        }
                        if (empty.length > 0) {
                            console.warn(
                                '[autk-grammar] dropping map layerRef(s) to empty table(s): '
                                + empty.map((r: any) => r.dataRef).join(', '),
                            );
                        }
                        if (dangling.length > 0 || empty.length > 0) {
                            spec.map = {
                                ...spec.map,
                                layerRefs: spec.map.layerRefs.filter(
                                    (r: any) => !dangling.includes(r) && !empty.includes(r),
                                ),
                            };
                        }
                    }
                    // A plot bound to an unavailable layer has nothing to draw:
                    // drop it rather than fail resolving the missing table.
                    if (spec.plot && (
                        (spec.plot.dataRef && !availableNames.has(spec.plot.dataRef))
                        || (spec.plot.mapRef && !availableNames.has(spec.plot.mapRef))
                    )) {
                        console.warn(
                            '[autk-grammar] dropping plot bound to unavailable table: '
                            + (spec.plot.dataRef ?? spec.plot.mapRef)
                            + ' - available: ' + [...availableNames].join(', '),
                        );
                        const { plot, ...rest } = spec;
                        spec = rest;
                    }
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
                    + (spec.plot && !spec.plot.dataRef ? 1 : 0);
                const layersDrawn = (Array.isArray(spec.map?.layerRefs)
                    ? spec.map.layerRefs.length
                    : 0) + (spec.plot ? 1 : 0);
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

                // A plot the document did not size fills its pane (see
                // utils/autkPlotSizing), measured now because the node can be
                // resized while its data loads.
                const plotPane = targets.plot ? document.getElementById(targets.plot) : null;
                if (plotPane && spec.plot) {
                    spec = {
                        ...spec,
                        plot: fitPlotToPane(spec.plot, {
                            width: plotPane.clientWidth,
                            height: plotPane.clientHeight,
                        }),
                    };
                }

                const { AutkGrammar } = await import('@urban-toolkit/autk-grammar');
                // A fresh grammar per attempt: it builds its own AutkDb, and a
                // DuckDB worker that failed to fetch the spatial extension keeps
                // that state, so only a new one can succeed (#318).
                const grammar = await withExtensionRetry(async () => {
                    const g = new AutkGrammar(targets);
                    await g.run(spec);
                    return g;
                });
                // autk-plot's SVG is inline, so it sits on a line of text whose
                // descender space overflows a pane the plot exactly fills, and
                // brings the scrollbars back. As a block it fits.
                for (const child of Array.from(plotPane?.children ?? [])) {
                    if (child.tagName.toLowerCase() === 'svg') (child as SVGElement).style.display = 'block';
                }

                // Store for interaction effects
                grammarRef.current = grammar;
                specRef.current    = spec;

                // Grammar → Curio: forward map-picking and plot-selection events to
                // the Curio interaction bus so connected nodes (data-pool, Vega) react.
                // Guard against older package versions that pre-date the interactions API.
                if (grammar.interactions) {
                    // Capture which layer each interaction comes from so a downstream
                    // Data Pool can target the right layer in a multi-layer wrapper —
                    // otherwise the pool's legacy path operates on data[0] and a brush
                    // on (say) roads ends up marking surface features. The picked map
                    // layer is the one with isPick:true; the plot's source is its
                    // dataRef. Both are resolved once here and closed over below.
                    const pickedLayerRef: string | undefined =
                        spec.map?.layerRefs?.find?.((l: any) => l.isPick)?.dataRef
                        ?? spec.map?.layerRefs?.[0]?.dataRef;
                    const plotLayerRef: string | undefined = spec.plot?.dataRef;

                    const emitInteraction = (
                        selection: number[],
                        layerRef: string | undefined,
                        from: 'map' | 'plot',
                    ) => {
                        const d = dataRef.current;
                        // Rows of the input, not positions in what was drawn.
                        const order = layerRef ? loadOrdersRef.current[layerRef]?.[from === 'map' ? 'map' : 'load'] : null;
                        const rows = selection.map((position) => inputRow(position, order));
                        d.interactionsCallback?.({
                            autk_selection: {
                                type: rows.length > 0 ? VisInteractionType.POINT : VisInteractionType.UNDETERMINED,
                                data: rows,
                                priority: 1,
                                source: NodeType.AUTK_GRAMMAR,
                                layerRef,
                            },
                        }, d.nodeId);
                    };

                    const off1 = grammar.interactions.on('map:picking',    ({ selection }) => emitInteraction(selection, pickedLayerRef, 'map'));
                    const off2 = grammar.interactions.on('plot:selection', ({ selection }) => emitInteraction(selection, plotLayerRef, 'plot'));
                    interactionOffRef.current = [off1, off2];
                }

                if (data.outputCallback) {
                    data.outputCallback(data.nodeId, data.input ?? null);
                }
                // A selection still active from before this draw lights up
                // the new map too, as a Vega chart re-applies its own.
                syncHighlightsNow();
                // A partial drop still drew something; say what it lost rather
                // than leaving the console as the only record. It rides as the
                // success output, since a render node's body is its map.
                const note = partialRenderNote(renderCounts);
                if (note) summary = note;
            } else {
                // Data-only node: emit the data downstream.
                grammarRef.current = null;
                specRef.current    = null;
                if (specDataSources.length > 0) {
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
                    if (data.outputCallback) data.outputCallback(data.nodeId, out);
                    // The backend path hands back an artifact ref, not the
                    // tables, so name what the spec asked autk-db to create -
                    // a short load has already failed above, so these exist.
                    // Their rows are unknown there, so no emptiness is claimed;
                    // only layers in hand are counted.
                    const tables = backendLayers
                        ? backendLayers.map((l) => countedItem(l.name, featureCount(l.geojson), 'features'))
                        : requestedLayerTables(specDataSources);
                    summary = describeAutkRun('Loaded', 'table', tables);
                    summaryListsItems = tables.length > 0;
                    runCounts = {
                        sourceRows: backendLayers
                            ? totalCount(backendLayers.map((l) => featureCount(l.geojson)))
                            : undefined,
                    };
                } else {
                    // Compute-only node: skip the extra AutkDb round-trip — upstream layers
                    // (from backend, or the in-browser fallback) are already normalized and
                    // exploded. Re-loading them through DuckDB + the buildings clusterer can
                    // strip custom per-feature properties. Apply WGSL blocks directly so the
                    // outputs (feature.properties.compute.<col>) reach downstream untouched.
                    const computeInput = data.input
                        ? autkSourcesFrom(await readInput(data.input), spec, { alias: false })
                        : null;
                    if (computeInput?.emptyReason && computeInput.sources.length === 0) {
                        inputProblemRef.current = { reason: computeInput.emptyReason, detail: computeInput.detail };
                    }
                    const upstream = (computeInput?.sources ?? []).map((source) => ({
                        name: source.outputTableName,
                        fc: source.geojsonObject,
                        layerType: source.layerType,
                    }));
                    // The rows that arrived, counted before the empty-layer drop
                    // below hides them. No layer at all (nothing connected, or
                    // an input this node cannot read) is no claim, not zero.
                    const rowsIn = upstream.length > 0
                        ? totalCount(upstream.map((u) => featureCount(u.fc)))
                        : computeInput?.inputProblem ? 0 : undefined;
                    let layers = upstream.map((u) => ({
                        name: u.name,
                        type: u.layerType ?? 'polygons',
                        geojson: u.fc,
                    }));
                    // Drop empty layers (autk-db throws on an empty
                    // FeatureCollection, and an empty layer would surface as a
                    // blank tab in the downstream Data Pool); the compute below
                    // then only runs on layers that have features.
                    const emptyLayers = layers.filter((l) => !hasFeatures(l.geojson));
                    if (emptyLayers.length > 0) {
                        console.warn(
                            '[autk-grammar] compute node dropping empty upstream layer(s): '
                            + emptyLayers.map((l) => l.name).join(', '),
                        );
                        layers = layers.filter((l) => !emptyLayers.includes(l));
                    }
                    if (Array.isArray(spec.compute) && spec.compute.length > 0) {
                        const computeFailures: string[] = [];
                        layers = await applyComputeBlocks(
                            layers, spec.compute, computeFailures,
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
                        layers.map((l) => countedItem(l.name, featureCount(l.geojson), 'rows')),
                    );
                    summaryListsItems = layers.length > 0;
                    runCounts = {
                        rowsIn,
                        drawn: totalCount(layers.map((l) => featureCount(l.geojson))),
                        ...(computeInput?.inputProblem ? { inputProblem: computeInput.inputProblem } : {}),
                    };
                    // An empty result is not passed on: downstream would get
                    // nothing under this node's error. The verdict below says why.
                    if (!renderOutcome(runCounts).empty) {
                        const out = await toPoolOutput(layers, data.jsInterpreter, data.nodeId);
                        if (data.outputCallback) data.outputCallback(data.nodeId, out ?? layers);
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
            // The toast is transient and the node UI has no error tab, so
            // also log to console — it's the only durable place tooling
            // (and the e2e browser-log dump) can read the failure from.
            console.error('[autk-grammar] node error:', msg);
            emit({ code: 'error', content: msg });
            showToast(msg, 'error');
        }
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
     */
    const applyGrammar = async (specString: string): Promise<void> => {
        if (runningRef.current) {
            // A run is under way (a redraw on new input, or a Play): run once
            // more when it ends, with the latest document, rather than two runs
            // racing for the same canvas.
            pendingSpecRef.current = typeof specString === 'string' ? specString : JSON.stringify(specString);
            return;
        }
        lastSpecRef.current = typeof specString === 'string' ? specString : JSON.stringify(specString);
        hasRunRef.current = true;
        runningRef.current = true;
        inputProblemRef.current = null;
        let settled = false;
        const emit = (o: { code: string; content: string }) => {
            if (o.code === 'success' || o.code === 'error') settled = true;
            if (o.code === 'error') markNodeErrored?.(data.nodeId);
            nodeState.setOutput(o);
        };
        // The net itself lives in autkRunSettlement so it can be tested; see the
        // note there for why it is unreachable through this hook.
        try {
            await runAndAlwaysSettle(() => runGrammar(specString, emit), {
                settled: () => settled,
                onError: (msg) => {
                    // The toast is transient and the node UI has no error tab, so
                    // also log to console - the only durable place tooling (and the
                    // e2e browser-log dump) can read the failure from.
                    console.error('[autk-grammar] node error:', msg);
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
        if (next != null) await applyGrammar(next);
    };

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
                showToast(message, 'error');
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
    const syncHighlights = async () => {
        const grammar = grammarRef.current;
        const spec    = specRef.current;
        const current = dataRef.current;
        if (!grammar || !spec || !current.input) return;

        const layers = autkSourcesFrom(await readInput(current.input), spec).sources;
        if (layers.length === 0) return;

        const incoming: IncomingSelection[] = Array.isArray((current as any).interactions)
            ? (current as any).interactions
            : [];
        const direct = new Map<string, IncomingSelection[]>();
        for (const selection of incoming) {
            const named = (selection as any)?.details?.autk_selection?.layerRef;
            const target = layers.some((l) => l.outputTableName === named) ? named : layers[0].outputTableName;
            direct.set(target, [...(direct.get(target) ?? []), selection]);
        }

        // Input rows per layer; each target turns them into its own positions.
        const rowsByLayer = new Map<string, number[]>();
        for (const { outputTableName: name, geojsonObject: fc } of layers) {
            const flagged = ((fc.features ?? []) as any[]).reduce<number[]>((acc, f, i) => {
                if (f.properties?.interacted === '1') acc.push(i);
                return acc;
            }, []);
            const selected = direct.has(name) ? matchSelections(direct.get(name)!, featureRows(fc)) : [];
            rowsByLayer.set(name, [...new Set([...flagged, ...selected])]);
        }
        const positions = (name: string, from: 'map' | 'load') =>
            tablePositions(rowsByLayer.get(name) ?? [], loadOrdersRef.current[name]?.[from]);

        const maps  = spec.map  ? (Array.isArray(spec.map)  ? spec.map  : [spec.map])  : [];
        const plots = spec.plot ? (Array.isArray(spec.plot) ? spec.plot : [spec.plot]) : [];

        for (const mapSpec of maps) {
            for (const lr of mapSpec.layerRefs) {
                const sel = positions(lr.dataRef, 'map');
                sel.length === 0
                    ? grammar.clearHighlightOnMap?.(lr.dataRef)
                    : grammar.highlightOnMap?.(lr.dataRef, sel);
            }
        }
        for (const plotSpec of plots) {
            const sel = positions(plotSpec.dataRef, 'load');
            sel.length === 0
                ? grammar.clearHighlightOnPlot?.(plotSpec.dataRef)
                : grammar.setPlotSelection?.(plotSpec.dataRef, sel);
        }
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

    // A starter document chosen from the arriving input, the way every grammar
    // node fills an empty editor (hook/useStarterSpec): once, only into an
    // empty editor, only after an input has arrived, never over a document
    // written in from outside. A bundle is read the way the run reads it, so
    // it downloads once; a single frame needs only its preview.
    const starterSpec = useStarterSpec({
        input: data.input,
        buffer: nodeState.code,
        written: data.defaultCode,
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
            return autkNeedsInput(JSON.parse(liveCode));
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
            hasInput,
            hasSpec,
            needsInput,
            hasRun: hasRunRef.current,
            inputProblem: problem?.reason ?? null,
        });
        noticeRef.current = reason == null
            ? null
            : { reason, words: emptyStateWords(reason, liveKind, problem?.detail) };
        writeNotice();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [connected, upstreamErrored, hasInput, hasSpec, needsInput, liveKind, gpuBlocked, nodeState.output?.code, runSummary]);

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

    // Unsubscribe grammar event listeners and remove the interaction zoom-fix
    // window listeners when the node is removed from the canvas.
    useEffect(() => () => {
        interactionOffRef.current.forEach(f => f());
        pickFixCleanupRef.current?.();
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
                    style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}
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
                </div>
            ),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [nodeState.output, gpuBlocked, gpuChecking, runSummary, specKind],
    );

    return {
        applyGrammar,
        contentComponent,
        // Only ever offered for an empty editor, so it cannot displace real
        // work, and it steps aside for a document written in from outside.
        defaultValueOverride: starterSpec,
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
