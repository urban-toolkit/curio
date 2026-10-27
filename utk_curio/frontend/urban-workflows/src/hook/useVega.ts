import React, { useEffect, useState } from "react";
import { NodeType, VisInteractionType } from "../constants";
import { useProvenanceContext } from "../providers/ProvenanceProvider";

import { formatDate, mapTypes } from "../utils/formatters";
import { useFlowContext } from "../providers/FlowProvider";
import { useToastContext } from "../providers/ToastProvider";
import { applyContainerSizing, createFlipGuard, fitsItsContainer, refitToContainer, settleFit } from "../utils/vegaSpecSizing";
import type { RenderCounts } from "../utils/renderOutcome";
import { injectInputs, prepareVegaInputs, usesNamedDatasets, type VegaDataset } from "../utils/vegaInput";
import { DEFAULT_INPUT_DATASET } from "../utils/vegaGeoSpec";
import { INPUTS_DATASET } from "../utils/vegaDatasets";
import { inputTableName } from "../contracts/autkGrammar";
import { usableCounts } from "../utils/vegaUsableRows";
import { matchSelections, objectRows, type PointValue } from "../utils/selectionMatch";
import { columnsOfRows, provideViewRows } from "../utils/references/viewSelections";
import { rowsHeldBy, selectionSize, tagsOnView } from "../utils/references/selectionTags";
import {
  carriedSelections,
  isPointSelection,
  pointStoreOf,
  pointStoreTuples,
  pointValues,
  viewSelects,
  withMovedIds,
  type PointStore,
  type SelectType,
} from "../utils/vegaSelects";
import { echoedCircle } from "../utils/selectionEcho";
import type { ScenarioLabel } from "../utils/scenarios/scenarioColors";
import type { NodeEmptyReason } from "../utils/nodeEmptyState";
import { resolveGrammarEmptyReason } from "../utils/nodeEmptyState";
import { clearEmptyState, writeEmptyState } from "../utils/writeEmptyState";
import { reachVegaTooltips, vegaTooltipHandler } from "../components/tooltip/vegaTooltip";

// const schema = require('./vega-schema.json');
const vega = require("vega");
const lite = require("vega-lite");

/** How vega's error begins for a dataset a view does not hold. */
const UNRECOGNIZED_DATASET = "Unrecognized data set";

if (typeof window !== 'undefined') {
  (window as any).__curio_vega = vega;
  (window as any).__curio_vegaLite = lite;
}

/**
 * A view that cannot fetch anything.
 *
 * Only the TOP-LEVEL `data` is replaced with the rows Curio resolved, so a
 * reference nested inside a layer, a lookup transform, a `datasets` block or a
 * topojson source survives compilation and vega's default loader fetches it
 * while the chart renders. On a dashboard that is wrong twice over: the page is
 * served complete and must reach nothing, and it is opened by whoever holds the
 * link, so a URL in somebody's saved spec would be fetched by every viewer.
 *
 * Refusing is better than ignoring. The chart shows vega's own error for the
 * reference it could not load, which says which one it was, rather than drawing
 * a layer short and looking merely wrong.
 *
 * Built on first use rather than at import: several suites mock `vega` down to
 * the handful of members they need, and a module-level `vega.loader(...)` call
 * makes importing this file throw in every one of them.
 */
let offlineViewOptions: { loader: unknown } | undefined;

function offlineViewOptionsOnce() {
  if (!offlineViewOptions) {
    offlineViewOptions = {
      loader: vega.loader({
        load: (uri: string) =>
          Promise.reject(
            new Error(
              `This dashboard cannot load ${uri}: a published dashboard draws only `
              + `from the data saved with it.`,
            ),
          ),
      }),
    };
  }
  return offlineViewOptions;
}

export const useVega = ({
  data,
  code,
  connected = true,
  upstreamErrored = false,
  upstreamRunning = false,
  upstreamStopped = null,
  onDashboard = false,
  hasSpec = true,
  onRedraw,
  inputLabels,
}: {
  data: any;
  code: string;
  /** Is anything wired into this node's input? */
  connected?: boolean;
  /** Did the node feeding this one run and fail? */
  upstreamErrored?: boolean;
  /** On a dashboard, is a viewer's run making this chart's rows? */
  upstreamRunning?: boolean;
  /** On a dashboard, why the viewer's run stopped before this chart, if it did. */
  upstreamStopped?: string | null;
  /** A dashboard's tile: it draws by itself, with no play for a visitor to press. */
  onDashboard?: boolean;
  /** Does the editor hold a spec to compile? */
  hasSpec?: boolean;
  /**
   * Hears what a redraw drew when new rows reach a chart that is already
   * compiled. That path never goes through `handleCompileGrammar`, so without
   * it a chart first compiled over zero rows kept saying so after its rows
   * arrived and it drew them.
   */
  onRedraw?: (counts: RenderCounts) => void;
  /**
   * Each input's label, in circle order: the scenario box its node is in
   * (utils/scenarios/inputScenarios). A spec that reads `inputs` names their
   * rows by these, read as each compile and each new input stacks them.
   */
  inputLabels?: readonly ScenarioLabel[];
}) => {
  const onRedrawRef = React.useRef(onRedraw);
  onRedrawRef.current = onRedraw;
  const inputLabelsRef = React.useRef<readonly ScenarioLabel[]>(inputLabels ?? []);
  inputLabelsRef.current = inputLabels ?? [];
  const { showToast } = useToastContext();
  const [interactions, _setInteractions] = useState<any>({}); // {signal: {type: point/interval, data: }} // if type point data contains list of object ids. If type is interval data is an object where each key is an attribute with intervals or lists

  const [currentView, _setCurrentView] = useState<any>(null);
  const currentViewRef = React.useRef(currentView);
  const setCurrentView = (data: any) => {
    currentViewRef.current = data;
    _setCurrentView(data);
  };

  const interactionsRef = React.useRef(interactions);
  const setInteractions = (data: any) => {
    interactionsRef.current = data;
    _setInteractions(data);
  };

  const vgsidToIndexRef = React.useRef<Map<number, number>>(new Map());

  // The spec most recently compiled. `processData` needs it to prepare rows the
  // same way `compileGrammar` did -- hot reload never goes through the latter.
  const lastSpecRef = React.useRef<any>(null);
  // The same spec as it was handed in, before its inputs went into it: a view
  // built again for new inputs starts from this, not from the last datasets.
  const authoredSpecRef = React.useRef<string>("null");

  // The same spec after container sizing, which says whether the view's width
  // and height follow its mount (#496).
  const sizedSpecRef = React.useRef<Record<string, unknown> | null>(null);

  /** Fits *view* again until its plot holds still, when *spec* fits it to its
   * mount (utils/vegaSpecSizing's settleFit): Vega's one pass can leave the
   * plot laid out for other axis labels than the ones it draws. */
  const settleView = (view: any, spec: Record<string, unknown> | null): Promise<void> =>
    view != null && fitsItsContainer(spec) ? settleFit(view) : Promise.resolve();
  /** The chart as it stands, settled once the runs already asked of it are
   * queued: a mount or window resize also runs vega's own refit from the
   * mount's size (vega-lite's `container:resize` and `window:resize` signal
   * updates), which can undo a settle made before it. */
  const settleSoon = () => {
    window.setTimeout(() => {
      settleView(currentViewRef.current, sizedSpecRef.current).catch(() => undefined);
    }, 0);
  };

  // The rows the view holds, which a direct selection is matched against: the
  // first input's.
  const lastValuesRef = React.useRef<any[]>([]);
  // Every input's rows the view holds, and the input they came from, which
  // tells a selection coming back on one input from new data (#662).
  const heldDatasetsRef = React.useRef<VegaDataset[]>([]);
  const heldInputRef = React.useRef<any>(undefined);
  // Whether the view reads its inputs as named datasets (#662), which a new
  // input reaches by building the view again rather than by a hot swap.
  const datasetViewRef = React.useRef(false);
  const incomingSelectionRef = React.useRef<any>(data.interactions);
  incomingSelectionRef.current = data.interactions;
  // Whether a direct selection lit rows in the view, and the first input's
  // rows' own `interacted` flags, by row (a Data Pool's echo, or none): what
  // those rows go back to when the selection is taken away.
  const directAppliedRef = React.useRef(false);
  const inputFlagsRef = React.useRef<unknown[]>([]);
  const keepInputFlags = (rows: unknown) => {
    inputFlagsRef.current = Array.isArray(rows) ? rows.map((row: any) => row?.interacted) : [];
  };

  /**
   * Sets the `interacted` flag on the rows the view already holds of
   * *dataset*. The rows keep their `_vgsid_`, so a selection made in this
   * chart still finds its marks afterwards. vega-lite builds only the datasets
   * a spec reads, so a view drawing `inputs` alone holds no `input_0`: a
   * dataset the view lacks is skipped, where vega would throw.
   */
  const setInteracted = (view: any, flagOf: (t: any) => string, dataset: string = DEFAULT_INPUT_DATASET) => {
    try {
      view.change(dataset, vega.changeset().modify(() => true, "interacted", flagOf));
    } catch (error: any) {
      if (String(error?.message ?? "").startsWith(UNRECOGNIZED_DATASET)) return Promise.resolve(view);
      throw error;
    }
    return view.runAsync();
  };

  /**
   * A selection from a chart joined to this one by a direct interaction edge,
   * with no Data Pool between them. The rows it picks out are flagged
   * `interacted` in the view as it is, so the spec's `datum.interacted`
   * condition highlights them exactly as it does behind a pool. The chart is
   * never rebuilt for it. Also re-applied after new rows arrive, so a selection
   * that is still active survives an upstream run. It picks out rows of the
   * first input, which a spec reading `inputs` draws there too, under
   * `__input__` 0; the other inputs' rows there keep their flags. When the
   * edge goes, or the chart at its other end, the flow hands an empty list,
   * and the rows go back to the flags the chart's input carries.
   */
  const applyDirectSelection = (view: any) => {
    const incoming = incomingSelectionRef.current;
    if (!view || !Array.isArray(incoming)) return;
    let flagOf: (t: any) => string;
    if (incoming.length > 0) {
      const picked = new Set(matchSelections(incoming, objectRows(lastValuesRef.current)));
      flagOf = (t: any) => (picked.has(t.__row_index__) ? "1" : "0");
      directAppliedRef.current = true;
    } else if (directAppliedRef.current) {
      flagOf = (t: any) => String(inputFlagsRef.current[t.__row_index__] ?? "0");
      directAppliedRef.current = false;
    } else {
      return;
    }
    setInteracted(view, flagOf);
    if (heldDatasetsRef.current.some((d) => d.name === INPUTS_DATASET)) {
      setInteracted(view, (t: any) => ((t.__input__ ?? 0) === 0 ? flagOf(t) : t.interacted), INPUTS_DATASET);
    }
  };

  // Why the node body is blank, when it is. Persistent, unlike a toast.
  const [emptyReason, setEmptyReason] = useState<NodeEmptyReason | null>(null);
  const [emptyDetail, setEmptyDetail] = useState<string | null>(null);
  const hasRunRef = React.useRef(false);

  const setEmptyState = (prepared: { emptyReason?: NodeEmptyReason; detail?: string }) => {
    setEmptyReason(prepared.emptyReason ?? null);
    setEmptyDetail(prepared.detail ?? null);
    renderEmptyState(prepared.emptyReason ?? null, prepared.detail ?? null);
  };

  /** Write the empty state into the div vega renders into (utils/writeEmptyState). */
  const renderEmptyState = (reason: NodeEmptyReason | null, detail: string | null) => {
    writeEmptyState(document.getElementById("vega" + data.nodeId), reason, { hint: detail });
  };

  // Build a tupleid → original-index map by traversing the scene graph.
  // vega-lite derives intermediate datasets (e.g. for sorting) whose items have
  // different tuple IDs from the source "input_0" items, so we must read IDs from
  // the actual rendered items. Each item's datum carries __row_index__ (injected
  // before handing values to Vega) which propagates to derived items via rederive.
  // With several inputs only the first input's rows count: a selection reaches
  // a Data Pool as rows of the first input, and the others' indexes restart.
  const buildVgsidMap = (view: any): Map<number, number> => {
    const map = new Map<number, number>();
    const traverse = (node: any) => {
      if (!node) return;
      if (node.items) {
        for (const item of node.items) {
          if (item.datum?.__row_index__ !== undefined && (item.datum.__input__ ?? 0) === 0) {
            const id = item.datum['_vgsid_'];
            if (id !== undefined) map.set(id, item.datum.__row_index__);
          }
          traverse(item);
        }
      }
    };
    try { traverse(view.scenegraph().root); } catch (_) {}
    return map;
  };

  // dev/136: how many marks the view actually DREW. The same walk already
  // visits every scene item for the tupleid map; counting the leaf items whose
  // mark is a real mark type is what tells an empty plot from a drawn one, and
  // an empty plot was reported as `success` until now. Text and rule marks
  // count: an annotation-only chart is not an empty chart.
  const countDrawnMarks = (view: any): number | undefined => {
    let drawn = 0;
    let sawScenegraph = false;
    const MARKROLES = new Set([
      'symbol', 'rect', 'line', 'area', 'path', 'arc', 'text', 'rule', 'shape',
      'image', 'trail',
    ]);
    const traverse = (node: any) => {
      if (!node) return;
      if (typeof node.marktype === 'string' && MARKROLES.has(node.marktype)) {
        drawn += Array.isArray(node.items) ? node.items.length : 0;
      }
      if (Array.isArray(node.items)) {
        for (const item of node.items) traverse(item);
      }
    };
    try {
      traverse(view.scenegraph().root);
      sawScenegraph = true;
    } catch (_) {
      return undefined;   // could not count: no claim is made (dev/136)
    }
    return sawScenegraph ? drawn : undefined;
  };
  const processData = async () => {
    // hot reload visualizations with new incoming data
    if (currentView == null) {
      throw new Error("Current view is not initialized");
    }

    // let currentViewState = currentView.getState();

    // Must go through the same preparation as compileGrammar, against the same
    // spec. Hot reload bypasses compileGrammar entirely, so parsing the rows
    // any other way here would insert bare, un-rewound geometry into an
    // already-compiled view and break the map on the *second* upstream run
    // only -- which is a miserable thing to debug.
    const prepared = await prepareVegaInputs(data.input, lastSpecRef.current, inputLabelsRef.current);
    const prevView = currentViewRef.current;
    const previousInput = heldInputRef.current;
    heldInputRef.current = data.input;

    // A Data Pool sending a selection back: the same rows with new
    // `interacted` flags. Fresh rows would get fresh `_vgsid_` ids, and a
    // selection made in this chart (a hovered bar) would then match none of
    // them (#535), so only the flags change. The rows stay the view's own.
    // With several inputs only the input it came back on changes its flags.
    const echoed = echoedCircle(data.input, previousInput);
    const dataset = echoed === null ? null : inputTableName(echoed);
    const echoRows = prepared.datasets.find((d) => d.name === dataset)?.values;
    const heldRows = heldDatasetsRef.current.find((d) => d.name === dataset)?.values;
    if (prevView && dataset && Array.isArray(echoRows) && Array.isArray(heldRows) && echoRows.length === heldRows.length) {
      setEmptyState(prepared);
      if (echoed === 0) keepInputFlags(echoRows);
      const flagOf = (t: any) => echoRows[t.__row_index__]?.interacted ?? t.interacted;
      // A spec reading `inputs` draws that input's rows there too.
      const stacked = heldDatasetsRef.current.some((d) => d.name === INPUTS_DATASET);
      setInteracted(prevView, flagOf, dataset)
        .then(() => stacked
          ? setInteracted(prevView, (t: any) => (t.__input__ === echoed ? flagOf(t) : t.interacted), INPUTS_DATASET)
          : undefined)
        .then(() => applyDirectSelection(prevView));
      return;
    }

    // Several inputs, or a spec that reads its inputs by name: a hot swap
    // reaches one dataset only, so the view is built again from its spec.
    if (datasetViewRef.current || usesNamedDatasets(lastSpecRef.current, prepared.datasets.length)) {
      // A rebuild is a redraw too, and says what it drew. Built first, in its
      // own statement: `f?.(g())` never calls g when there is no f.
      const counts = await compileGrammar(JSON.parse(authoredSpecRef.current));
      onRedrawRef.current?.(counts);
      return;
    }
    setEmptyState(prepared);
    const values = prepared.datasets[0]?.values ?? [];
    lastValuesRef.current = values;
    keepInputFlags(values);
    heldDatasetsRef.current = prepared.datasets;

    let changeset = vega
      .changeset()
      .remove(() => true)
      .insert(values);

    // The same counts compileGrammar returns, so the node judges a redraw by
    // the rule it judged the first draw by (utils/renderOutcome).
    const rowsIn = Array.isArray(values) ? values.length : undefined;
    const { usableRows, usableFields } = usableCounts(values, lastSpecRef.current);

    if (prevView) {
      // Settled before it says what it drew, as a compile is (below): new rows
      // can bring axis labels of another width.
      const sizedSpec = sizedSpecRef.current;
      prevView.change(DEFAULT_INPUT_DATASET, changeset).runAsync().then(() => settleView(prevView, sizedSpec)).then(() => {
        const map = buildVgsidMap(prevView);
        if (map.size > 0) vgsidToIndexRef.current = map;
        applyDirectSelection(prevView);
        onRedrawRef.current?.(
          prepared.emptyReason != null
            ? {
              rowsIn, drawn: 0, usableRows, usableFields, explanation: prepared.detail,
              ...(prepared.emptyReason === "input-type-rejected" ? { inputProblem: prepared.detail } : {}),
            }
            : { rowsIn, drawn: countDrawnMarks(prevView), usableRows, usableFields },
        );
      });
    }

  };

  useEffect(() => {
    if (currentView == null) return;
    // `processData` is async: without the catch its rejection was unhandled and
    // the surrounding try/catch never saw it, so this error path reported
    // nothing at all.
    processData().catch((error: any) => {
      showToast(error.message, "error");
    });
  }, [data.input]);

  useEffect(() => {
    applyDirectSelection(currentViewRef.current);
  }, [data.interactions]);

  // #662: a selection tag on this chart reads the rows its selections are
  // matched against, the first input's, as a direct selection is
  // (utils/references/viewSelections). A point selection names their positions.
  useEffect(
    () =>
      provideViewRows(data.nodeId, () => {
        const values = lastValuesRef.current;
        return Array.isArray(values) && values.length > 0
          ? { rows: objectRows(values), columns: columnsOfRows(values) }
          : null;
      }),
    [data.nodeId],
  );


  // The states that exist *before* anything compiles: nothing connected, an
  // upstream that has not run, an empty editor. Nothing else would report these
  // -- `prepareVegaInput` only runs on a compile or an input change -- so the
  // node body would just sit blank, which is the complaint #224 was filed
  // about, still true of the most-used visualisation node.
  useEffect(() => {
    if (currentViewRef.current != null) return;
    const reason = resolveGrammarEmptyReason({
      connected,
      upstreamErrored,
      upstreamRunning,
      upstreamStopped,
      onDashboard,
      hasInput: data.input != null && data.input !== "",
      hasSpec,
      hasRun: hasRunRef.current,
      inputProblem: emptyReason,
    });
    if (reason != null) renderEmptyState(reason, reason === "upstream-stopped" ? upstreamStopped : emptyDetail);
  }, [connected, upstreamErrored, upstreamRunning, upstreamStopped, onDashboard, hasSpec, data.input, emptyReason, emptyDetail]);

  useEffect(() => {
    const el = document.getElementById("vega" + data.nodeId);
    const flipping = createFlipGuard();
    const ro = new ResizeObserver(() => {
      const view = currentViewRef.current;
      if (view != null && el) {
        // A node resized by hand kept its chart's old width: resize() alone
        // never re-reads the mount (#496). Not when the refit is only flipping
        // the mount's scrollbars, which would loop every frame.
        if (!flipping(`${el.clientWidth}x${el.clientHeight}`)) refitToContainer(view, el, sizedSpecRef.current);
        view.resize().runAsync();
        settleSoon();
      }
    });

    if (el) ro.observe(el);
    // vega-lite fits the chart again from its mount on every window resize,
    // with or without a new mount size.
    window.addEventListener("resize", settleSoon);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", settleSoon);
    };
  }, []);



  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const { workflowNameRef, dashboardOn, nodes: flowNodes, clearSelectionTagsOf } = useFlowContext();
  const { nodeExecProv } = useProvenanceContext();
  // #884: the tags that read this chart, and the flow's way to empty them, as
  // they are when the chart draws. A draw that ends after the node left the
  // page changes no tag: a node of the same id may be on the canvas by then.
  const flowNodesRef = React.useRef(flowNodes);
  flowNodesRef.current = flowNodes;
  const clearTagsRef = React.useRef(clearSelectionTagsOf);
  clearTagsRef.current = clearSelectionTagsOf;
  const mountedRef = React.useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const clearTags = () => {
    if (mountedRef.current) clearTagsRef.current?.(data.nodeId);
  };

  /**
   * #884: what a draw does with the selection the tags on the chart hold, when
   * one holds any. A chart puts it back with its point select, on the rows of
   * its first input that hold the tags' ids, as clicks on them would. It
   * cannot when it declares no point select, or an interval one too (a tag
   * does not say which select made its ids, and a brush cannot be drawn again
   * from ids), when the select's tuples are not in a form put back here
   * (`pointStoreOf`), or when none of its rows holds an id: then "clear".
   */
  const tagSelectionOf = (
    specObj: any,
    vegaspec: unknown,
    values: any[],
  ): { select: string; store: PointStore; rows: number[]; values: any[] } | "clear" | null => {
    const tags = tagsOnView(flowNodesRef.current ?? [], data.nodeId).filter((tag) => selectionSize(tag) > 0);
    if (tags.length === 0) return null;
    const declared = [...viewSelects(specObj, []).entries()];
    if (declared.some(([, type]) => type === "interval")) return "clear";
    const rows = rowsHeldBy(tags, objectRows(values));
    if (rows.length === 0) return "clear";
    for (const [select, type] of declared) {
      if (type !== "point") continue;
      const store = pointStoreOf(vegaspec, select);
      if (store) return { select, store, rows, values };
    }
    return "clear";
  };

  // The rows of the first input *view* draws a mark for. None when its marks
  // carry no row, as aggregates do.
  const drawnRows = (view: any): Set<number> => {
    const rows = new Set<number>();
    const traverse = (node: any) => {
      if (!node?.items) return;
      for (const item of node.items) {
        if (item.datum?.__row_index__ !== undefined && (item.datum.__input__ ?? 0) === 0) rows.add(item.datum.__row_index__);
        traverse(item);
      }
    };
    try { traverse(view.scenegraph().root); } catch (_) {}
    return rows;
  };

  /**
   * Sets the store of *restore*'s select, in *view* after its first run, to the
   * rows it names that the view draws, under the ids that view gives them;
   * says whether it picked any. A row the view draws no mark for, one its
   * transforms leave out, would be selected nowhere on the chart. A chart whose
   * marks are aggregates names no row, and takes every row.
   */
  const setStoreFromTags = async (
    view: any,
    restore: { select: string; store: PointStore; rows: number[]; values: any[] },
  ): Promise<boolean> => {
    const ids = buildVgsidMap(view);
    // The select reports the new view's ids, the moment it is told.
    if (ids.size > 0) vgsidToIndexRef.current = ids;
    const idOfRow = new Map<number, number>();
    for (const [id, row] of ids) idOfRow.set(row, id);
    const drawn = drawnRows(view);
    const rows = drawn.size > 0 ? restore.rows.filter((row) => drawn.has(row)) : restore.rows;
    const tuples = pointStoreTuples(restore.store, rows, restore.values, idOfRow);
    if (tuples.length === 0) return false;
    await view.setState({ data: { [`${restore.select}_store`]: tuples } }).runAsync();
    return true;
  };
  /**
   * Compiles *spec* and draws it. The compile is recorded in the node's
   * provenance, its code being the spec, and hands the node's input on as its
   * output, unless *how* says otherwise for this draw. With `keepsSelection`, a
   * selection made in the chart is put back in the new view and the flow goes
   * on holding it. A chart reading `inputs` is drawn again that way when a
   * scenario box is renamed or recolored (adapters/node/vegaBehavior), with no
   * version and no hand-off. Without it, the selection the chart's selection
   * tags hold is put back, or the tags are emptied (#884, `tagSelectionOf`).
   */
  const handleCompileGrammar = async (
    spec: string,
    how: { recordsProvenance?: boolean; forwardsInput?: boolean; keepsSelection?: boolean } = {},
  ): Promise<RenderCounts> => {
    let startTime = formatDate(new Date());

    const counts = await compileGrammar(JSON.parse(spec), {
      forwardsInput: how.forwardsInput ?? true,
      keepsSelection: how.keepsSelection ?? false,
    });

    // END COMPILE GRAMMAR
    let endTime = formatDate(new Date());

    if (how.recordsProvenance ?? true) {
      // A chart hands on the table it read, so it returned the kind it read.
      // The input names that kind by one `dataType`.
      const typesInput = data.input?.dataType;

      nodeExecProv(
        startTime,
        endTime,
        workflowNameRef.current,
        data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesInput),
        code
      );
    }

    // dev/136: the counts travel to the behavior, which decides whether this
    // was a render or an empty panel under a green badge.
    return counts;
  };

  const compileGrammar = async (
    specObj: any,
    how: { forwardsInput: boolean; keepsSelection: boolean } = { forwardsInput: true, keepsSelection: false },
  ) => {
    // Prepare before the spec is handed to vega-lite: resolving geometry can
    // inject `encoding.shape` and `projection` into `specObj`, and coerces the
    // row values those encodings will read.
    lastSpecRef.current = specObj;
    authoredSpecRef.current = JSON.stringify(specObj);
    const prepared = await prepareVegaInputs(data.input, specObj, inputLabelsRef.current);
    setEmptyState(prepared);
    const values = prepared.datasets[0]?.values ?? [];
    lastValuesRef.current = values;
    keepInputFlags(values);
    heldDatasetsRef.current = prepared.datasets;
    heldInputRef.current = data.input;
    // A spec that reads `inputs` draws every input's rows, named by their
    // scenarios: they are what arrived, not the first input's alone.
    const judged = prepared.stacked ?? values;
    const rowsIn = Array.isArray(judged) ? judged.length : undefined;
    // dev/137: judged over the fields the input carries; see vegaUsableRows.
    const { usableRows, usableFields } = usableCounts(judged, specObj);

    if (prepared.emptyReason != null) {
      // Nothing was injected and there is nothing sensible to draw. Compiling
      // anyway would replace the explanation with a blank canvas -- a geoshape
      // with no shape encoding still builds a projection, fits it to the raw
      // row array and renders NaN paths, silently.
      //
      // dev/136: still counts, and `drawn: 0` is the truth -- the badge must
      // not read green over the explanation this just put on the node, and
      // the verdict carries that same explanation. A refused input type is
      // the upstream's to fix, and its sentence says which type it was, as the
      // Autark node's refusal does.
      return {
        rowsIn, drawn: 0, usableRows, usableFields, explanation: prepared.detail,
        ...(prepared.emptyReason === "input-type-rejected" ? { inputProblem: prepared.detail } : {}),
      };
    }

    // Each input as the dataset its name says (`input_0`, `input_1`, ...): one
    // input as the spec's data, several as named datasets (utils/vegaInput).
    datasetViewRef.current = injectInputs(specObj, prepared.datasets);
    // Multi-view specs keep their authored size (vega-lite discards a
    // "container" injection there anyway) and the output pane scrolls; unit
    // and layer specs fill the node, unless the author sized them (#202).
    applyContainerSizing(specObj);
    sizedSpecRef.current = specObj;

    let vegaspec = lite.compile(specObj).spec;

    // vega replaces the container's contents, but the marker attribute is ours
    // and would otherwise outlive the message it described.
    clearEmptyState(document.getElementById("vega" + data.nodeId));
    hasRunRef.current = true;

    // A draw that keeps the chart's selections (keepsSelection) puts them back
    // in the view it builds: their state in the view it replaces, and the rows
    // that view's ids name.
    const carried = how.keepsSelection ? carriedSelections(currentViewRef.current, specObj) : null;
    const idsBefore = vgsidToIndexRef.current;
    // Any other draw builds a view that shows no selection, so the selection
    // the tags on the chart hold goes back in it, or the tags are emptied
    // (#884).
    const fromTags = how.keepsSelection ? null : tagSelectionOf(specObj, vegaspec, values);
    const restore = fromTags === "clear" ? null : fromTags;

    let view = new vega.View(vega.parse(vegaspec), dashboardOn ? offlineViewOptionsOnce() : undefined)
      .logLevel(vega.Warn) // set view logging level
      .renderer("canvas")
      // A mark's tooltip in the Curio tooltip, not the browser's title.
      .tooltip(vegaTooltipHandler)
      .initialize("#vega" + data.nodeId)
      .hover();
    // And the nearest mark's, near a line Vega answers only at its points.
    reachVegaTooltips(view);
    // Emptied once there is a view that shows none of it: a spec vega cannot
    // parse leaves them as they were.
    if (fromTags === "clear") clearTags();

    // React Flow's zoom scales the canvas with a CSS transform; vega maps a
    // pointer through that scale itself, so its events stay as the browser
    // sent them.
    const vegaEl = document.getElementById("vega" + data.nodeId);
    const vegaCanvas = vegaEl?.querySelector('canvas') as HTMLCanvasElement | null;
    if (vegaCanvas) {
      // The canvas is inline, so it sits on a line of text whose descender
      // space overflows a pane the chart exactly fills, and brings the
      // scrollbars back. As a block it fits, as autk-plot's SVG does.
      vegaCanvas.style.display = 'block';
      vegaCanvas.style.margin = '0 auto';
    }

    // The selections go back once the new view has numbered its rows, on its
    // first run, which also builds the scopes of its views. Until they are
    // back, what the view says of its selects is the empty selection it starts
    // on, then the one put back: neither is passed on. A carried selection is
    // the one the flow already holds; one put back from the tags is told to
    // the flow once it is back (below).
    let restoring = carried !== null || restore !== null;
    let restored = false;
    const firstRun: Promise<unknown> = carried
      ? view
          .runAsync()
          .then(() => view.setState(withMovedIds(carried, idsBefore, buildVgsidMap(view))).runAsync())
          .finally(() => {
            restoring = false;
          })
      : restore
        ? view
            .runAsync()
            .then(() => setStoreFromTags(view, restore))
            .then((done: boolean) => {
              restored = done;
            })
            .finally(() => {
              restoring = false;
            })
        : view.runAsync();

    // dev/136: the same chain, with its result kept — the marks can only be
    // counted once the first render has finished, and the caller needs that
    // count to tell a drawn chart from an empty one.
    const rendered: Promise<number | undefined> = firstRun.then(() => {
      const container = document.getElementById("vega" + data.nodeId);
      const parentContainer = container?.parentElement;
      if (parentContainer) {
        const hasBindings = container.querySelector(".vega-bind") !== null;
        parentContainer.style.paddingBottom = hasBindings ? "25px" : "";
      }
      // Canvas pixel dimensions are fixed at initialization time. If the node
      // hasn't finished layout by then the coordinates will be wrong. Resize
      // after the first render so the canvas matches the actual container size
      // before the user can interact. A tall chart's scrollbar only appears
      // with that first draw, so the width is read again here (#496).
      refitToContainer(view, container, specObj);
      return view.resize().runAsync();
    }).then(() => (
      // A fit from the mount's size can leave the plot laid out for other axis
      // labels than it draws: settled before the marks are counted, so the
      // node says it drew once the layout holds.
      settleView(view, specObj)
    )).then(() => {
      const map = buildVgsidMap(view);
      if (map.size > 0) vgsidToIndexRef.current = map;
      applyDirectSelection(view);
      return countDrawnMarks(view);
    }).catch(() => undefined);   // could not count: no claim (dev/136)

    setCurrentView(view);

    // What the select *select* holds now, *value* (its top-level signal's
    // value), told to the flow: as a click, a hover or a brush in the chart
    // tells it, and as a selection put back from the tags is told (#884).
    const report = (select: string, declared: SelectType | undefined, value: any) => {
      // detecting the type of interaction (point/hover or interval (brush))
      let signalAttributes = Object.keys(value);

      // what a point/hover selection names: the rows' positions, or (a
      // select over fields) the values it picked
      let interactedElementsPoint: Array<number | PointValue> = [];

      if (signalAttributes.length == 0) {
        // no interaction
        let previousValue = interactionsRef.current[select];

        let type = VisInteractionType.UNDETERMINED;
        let data: any = [];

        if (previousValue != undefined) {
          type = previousValue.type;
          if (type == VisInteractionType.INTERVAL) {
            data = {};
          }
        }

        let interactionsKeys = Object.keys(interactionsRef.current);

        let newObj: any = {};
        for (const interactionKey of interactionsKeys) {
          newObj[interactionKey] = {
            type: interactionsRef.current[interactionKey].type,
            data: interactionsRef.current[interactionKey].data,
            priority: 0,
            source: NodeType.VIS_VEGA,
          };
        }

        newObj[select] = {
          type: type,
          data: data,
          priority: 1,
          source: NodeType.VIS_VEGA,
        };

        setInteractions(newObj);
      } else if (isPointSelection(declared, value)) {
        // point/hover: the rows vega's tuple ids name, or the values a
        // select over fields picked, which every reader matches its own
        // rows against (#847)
        if (signalAttributes.includes("_vgsid_")) {
          for (const elem of value._vgsid_) {
            const idx = vgsidToIndexRef.current.get(elem);
            if (idx !== undefined) interactedElementsPoint.push(idx);
          }
        } else {
          interactedElementsPoint = pointValues(value);
        }

        let interactionsKeys = Object.keys(interactionsRef.current);

        let newObj: any = {};
        for (const interactionKey of interactionsKeys) {
          newObj[interactionKey] = {
            type: interactionsRef.current[interactionKey].type,
            data: interactionsRef.current[interactionKey].data,
            priority: 0,
          };
        }

        newObj[select] = {
          type: VisInteractionType.POINT,
          data: interactedElementsPoint,
          priority: 1,
          source: NodeType.VIS_VEGA,
        };

        setInteractions(newObj);
      } else {
        // interval

        let interactionsKeys = Object.keys(interactionsRef.current);

        let newObj: any = {};
        for (const interactionKey of interactionsKeys) {
          newObj[interactionKey] = {
            type: interactionsRef.current[interactionKey].type,
            data: interactionsRef.current[interactionKey].data,
            priority: 0,
          };
        }

        newObj[select] = {
          type: VisInteractionType.INTERVAL,
          data: { ...value },
          priority: 1,
          source: NodeType.VIS_VEGA,
        };

        setInteractions(newObj);
      }
    };

    // A listener on each select's top-level signal, `<name>`, which holds its
    // selection, whatever the name and wherever the spec declares it (#846).
    const selects = viewSelects(specObj, Object.keys(view.getState().signals ?? {}));
    const heard: Array<[string, SelectType | undefined]> = [];
    for (const [select, declared] of selects) {
      try {
        view.addSignalListener(select, (_name: any, value: any) => {
          if (restoring) return;
          report(select, declared, value);
        });
      } catch {
        // vega throws for a name that is not one of the view's top-level
        // signals, as a `<name>_modify` signal no select made can give.
        continue;
      }
      heard.push([select, declared]);
      // Put back in the view, a selection stays as the flow holds it.
      if (carried) continue;
      setInteractions({
        ...interactionsRef.current,
        [select]: {
          type: VisInteractionType.UNDETERMINED,
          data: [],
          source: NodeType.VIS_VEGA,
        },
      });
    }

    // #884: the selection put back from the tags, once it is back, told to the
    // flow as clicks on its rows would tell it. The tags are written again from
    // what the chart shows, which marks no node stale while they hold the same
    // ids, and a Data Pool linked to the chart sees it too. When the view draws
    // none of those rows, its selects are told empty, as its first run would
    // have told them, and the tags are emptied.
    if (restore) {
      void firstRun
        .then(() => {
          if (!mountedRef.current) return;
          if (restored) {
            if (heard.some(([select]) => select === restore.select)) {
              report(restore.select, "point", view.signal(restore.select));
            }
            return;
          }
          for (const [select, declared] of heard) report(select, declared, {});
          clearTags();
        })
        .catch(() => undefined);
    }

    // replicating input to the output
    if (how.forwardsInput) data.outputCallback(data.nodeId, data.input);

    // dev/136: what this render actually amounted to. Awaited last, so the
    // listeners above are attached exactly when they were before.
    // dev/137: plus what the DATA held in the fields this document plots.
    return { rowsIn, drawn: await rendered, usableRows, usableFields };
  };



  return { handleCompileGrammar, emptyReason, emptyDetail };
};

