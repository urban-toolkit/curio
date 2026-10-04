import React, { useEffect, useState } from "react";
import { NodeType, VisInteractionType } from "../constants";
import { useProvenanceContext } from "../providers/ProvenanceProvider";

import { formatDate, mapTypes } from "../utils/formatters";
import { useFlowContext } from "../providers/FlowProvider";
import { useToastContext } from "../providers/ToastProvider";
import { applyContainerSizing, createFlipGuard, refitToContainer } from "../utils/vegaSpecSizing";
import type { RenderCounts } from "../utils/renderOutcome";
import { injectInputs, prepareVegaInputs, usesNamedDatasets, type VegaDataset } from "../utils/vegaInput";
import { DEFAULT_INPUT_DATASET } from "../utils/vegaGeoSpec";
import { inputTableName } from "../generated/autkGrammar";
import { usableCounts } from "../utils/vegaUsableRows";
import { matchSelections, objectRows } from "../utils/selectionMatch";
import { echoedCircle } from "../utils/selectionEcho";
import type { NodeEmptyReason } from "../utils/nodeEmptyState";
import { resolveGrammarEmptyReason } from "../utils/nodeEmptyState";
import { clearEmptyState, writeEmptyState } from "../utils/writeEmptyState";

// const schema = require('./vega-schema.json');
const vega = require("vega");
const lite = require("vega-lite");

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
  hasSpec = true,
  onRedraw,
}: {
  data: any;
  code: string;
  /** Is anything wired into this node's input? */
  connected?: boolean;
  /** Did the node feeding this one run and fail? */
  upstreamErrored?: boolean;
  /** Does the editor hold a spec to compile? */
  hasSpec?: boolean;
  /**
   * Hears what a redraw drew when new rows reach a chart that is already
   * compiled. That path never goes through `handleCompileGrammar`, so without
   * it a chart first compiled over zero rows kept saying so after its rows
   * arrived and it drew them.
   */
  onRedraw?: (counts: RenderCounts) => void;
}) => {
  const onRedrawRef = React.useRef(onRedraw);
  onRedrawRef.current = onRedraw;
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

  /**
   * Sets the `interacted` flag on the rows the view already holds. The rows
   * keep their `_vgsid_`, so a selection made in this chart still finds its
   * marks afterwards.
   */
  const setInteracted = (view: any, flagOf: (t: any) => string, dataset: string = DEFAULT_INPUT_DATASET) =>
    view
      .change(dataset, vega.changeset().modify(() => true, "interacted", flagOf))
      .runAsync();

  /**
   * A selection from a chart joined to this one by a direct interaction edge,
   * with no Data Pool between them. The rows it picks out are flagged
   * `interacted` in the view as it is, so the spec's `datum.interacted`
   * condition highlights them exactly as it does behind a pool. The chart is
   * never rebuilt for it. Also re-applied after new rows arrive, so a selection
   * that is still active survives an upstream run.
   */
  const applyDirectSelection = (view: any) => {
    const incoming = incomingSelectionRef.current;
    if (!view || !Array.isArray(incoming) || incoming.length === 0) return;
    const picked = new Set(matchSelections(incoming, objectRows(lastValuesRef.current)));
    setInteracted(view, (t: any) => (picked.has(t.__row_index__) ? "1" : "0"));
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
    const prepared = await prepareVegaInputs(data.input, lastSpecRef.current);
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
      setInteracted(prevView, (t: any) => echoRows[t.__row_index__]?.interacted ?? t.interacted, dataset)
        .then(() => applyDirectSelection(prevView));
      return;
    }

    // Several inputs, or a spec that reads its inputs by name: a hot swap
    // reaches one dataset only, so the view is built again from its spec.
    if (datasetViewRef.current || usesNamedDatasets(lastSpecRef.current, prepared.datasets.length)) {
      // A rebuild is a redraw too, and says what it drew.
      onRedrawRef.current?.(await compileGrammar(JSON.parse(authoredSpecRef.current)));
      return;
    }
    setEmptyState(prepared);
    const values = prepared.datasets[0]?.values ?? [];
    lastValuesRef.current = values;
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
      prevView.change(DEFAULT_INPUT_DATASET, changeset).runAsync().then(() => {
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
      hasInput: data.input != null && data.input !== "",
      hasSpec,
      hasRun: hasRunRef.current,
      inputProblem: emptyReason,
    });
    if (reason != null) renderEmptyState(reason, emptyDetail);
  }, [connected, upstreamErrored, hasSpec, data.input, emptyReason, emptyDetail]);

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
      }
    });

    if (el) ro.observe(el);
    return () => ro.disconnect();
  }, []);



  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const { workflowNameRef, dashboardOn } = useFlowContext();
  const { nodeExecProv } = useProvenanceContext();
  const handleCompileGrammar = async (spec: string): Promise<RenderCounts> => {
    let startTime = formatDate(new Date());

    const counts = await compileGrammar(JSON.parse(spec));

    // END COMPILE GRAMMAR
    let endTime = formatDate(new Date());

    let typesInput: string[] = [];

    if (data.input != "") typesInput = data.input.dataType; // getType([data.input]);

    let typesOuput: string[] = [...typesInput];

    nodeExecProv(
      startTime,
      endTime,
      workflowNameRef.current,
      data.nodeId,
      mapTypes(typesInput),
      mapTypes(typesOuput),
      code
    );

    // dev/136: the counts travel to the behavior, which decides whether this
    // was a render or an empty panel under a green badge.
    return counts;
  };

  const compileGrammar = async (specObj: any) => {
    // Prepare before the spec is handed to vega-lite: resolving geometry can
    // inject `encoding.shape` and `projection` into `specObj`, and coerces the
    // row values those encodings will read.
    lastSpecRef.current = specObj;
    authoredSpecRef.current = JSON.stringify(specObj);
    const prepared = await prepareVegaInputs(data.input, specObj);
    setEmptyState(prepared);
    const values = prepared.datasets[0]?.values ?? [];
    lastValuesRef.current = values;
    heldDatasetsRef.current = prepared.datasets;
    heldInputRef.current = data.input;
    const rowsIn = Array.isArray(values) ? values.length : undefined;
    // dev/137: judged over the fields the input carries; see vegaUsableRows.
    const { usableRows, usableFields } = usableCounts(values, specObj);

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

    let view = new vega.View(vega.parse(vegaspec), dashboardOn ? offlineViewOptionsOnce() : undefined)
      .logLevel(vega.Warn) // set view logging level
      .renderer("canvas")
      .initialize("#vega" + data.nodeId)
      .hover();

    // Vega's point.js computes coordinates as `clientX - getBoundingClientRect().left`,
    // both in screen pixels. But ReactFlow applies a CSS zoom transform to its viewport,
    // so getBoundingClientRect() returns scaled (screen) dimensions while Vega's internal
    // coordinate system is in CSS pixels. event.offsetX gives the correct CSS-pixel
    // position within the canvas, ignoring parent transforms (per CSSOM spec).
    // Intercept events before Vega sees them and replace clientX/Y so that
    // Vega's subtraction gives offsetX — the correct CSS-pixel position.
    const vegaEl = document.getElementById("vega" + data.nodeId);
    const vegaCanvas = vegaEl?.querySelector('canvas') as HTMLCanvasElement | null;
    if (vegaCanvas) {
      // The canvas is inline, so it sits on a line of text whose descender
      // space overflows a pane the chart exactly fills, and brings the
      // scrollbars back. As a block it fits, as autk-plot's SVG does.
      vegaCanvas.style.display = 'block';
      vegaCanvas.style.margin = '0 auto';
      const FIXED = '__curio_coord_fixed';
      const PATCH_TYPES = [
        'mousemove', 'mousedown', 'mouseup', 'click',
        'pointermove', 'pointerdown', 'pointerup', 'pointerover', 'pointerout',
        'mouseover', 'mouseout',
      ];
      PATCH_TYPES.forEach(type => {
        vegaCanvas.addEventListener(type, (evt: Event) => {
          const me = evt as MouseEvent;
          if ((me as any)[FIXED]) return;
          me.stopImmediatePropagation();
          const rect = vegaCanvas.getBoundingClientRect();
          const synth = new MouseEvent(type, {
            bubbles: me.bubbles,
            cancelable: me.cancelable,
            view: me.view,
            detail: me.detail,
            clientX: rect.left + me.offsetX,
            clientY: rect.top + me.offsetY,
            screenX: me.screenX,
            screenY: me.screenY,
            ctrlKey: me.ctrlKey,
            shiftKey: me.shiftKey,
            altKey: me.altKey,
            metaKey: me.metaKey,
            button: me.button,
            buttons: me.buttons,
            relatedTarget: me.relatedTarget,
            movementX: me.movementX,
            movementY: me.movementY,
          });
          (synth as any)[FIXED] = true;
          vegaCanvas.dispatchEvent(synth);
        }, { capture: true });
      });
    }

    // dev/136: the same chain, with its result kept — the marks can only be
    // counted once the first render has finished, and the caller needs that
    // count to tell a drawn chart from an empty one.
    const rendered: Promise<number | undefined> = view.runAsync().then(() => {
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
    }).then(() => {
      const map = buildVgsidMap(view);
      if (map.size > 0) vgsidToIndexRef.current = map;
      applyDirectSelection(view);
      return countDrawnMarks(view);
    }).catch(() => undefined);   // could not count: no claim (dev/136)

    setCurrentView(view);

    // getting signals names
    let viewState = view.getState();
    let stateAttributes = Object.keys(viewState.signals);
    for (const stateAttribute of stateAttributes) {
      let parsedAttr = stateAttribute.split("_");

      // adding a signal listener for each signal
      if (parsedAttr.length > 1 && parsedAttr[1] == "modify") {
        setInteractions({
          ...interactionsRef.current,
          [parsedAttr[0]]: {
            type: VisInteractionType.UNDETERMINED,
            data: [],
            source: NodeType.VIS_VEGA,
          },
        });

        view.addSignalListener(parsedAttr[0], (name: any, value: any) => {
          // detecting the type of interaction (point/hover or interval (brush))
          let signalAttributes = Object.keys(value);

          let interactedElementsPoint: number[] = []; // id of the elements interacted with point/hover

          if (signalAttributes.length == 0) {
            // no interaction
            let previousValue = interactionsRef.current[parsedAttr[0]];

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

            newObj[parsedAttr[0]] = {
              type: type,
              data: data,
              priority: 1,
              source: NodeType.VIS_VEGA,
            };

            setInteractions(newObj);
          } else if (signalAttributes.includes("_vgsid_")) {
            // point/hover
            for (const elem of value._vgsid_) {
              const idx = vgsidToIndexRef.current.get(elem);
              if (idx !== undefined) interactedElementsPoint.push(idx);
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

            newObj[parsedAttr[0]] = {
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

            newObj[parsedAttr[0]] = {
              type: VisInteractionType.INTERVAL,
              data: { ...value },
              priority: 1,
              source: NodeType.VIS_VEGA,
            };

            setInteractions(newObj);
          }
        });
      }
    }

    // replicating input to the output
    data.outputCallback(data.nodeId, data.input);

    // dev/136: what this render actually amounted to. Awaited last, so the
    // listeners above are attached exactly when they were before.
    // dev/137: plus what the DATA held in the fields this document plots.
    return { rowsIn, drawn: await rendered, usableRows, usableFields };
  };



  return { handleCompileGrammar, emptyReason, emptyDetail };
};

