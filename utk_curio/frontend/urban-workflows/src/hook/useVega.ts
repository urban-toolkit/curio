import React, { useEffect, useState } from "react";
import { NodeType, VisInteractionType } from "../constants";
import { useProvenanceContext } from "../providers/ProvenanceProvider";

import { formatDate, mapTypes } from "../utils/formatters";
import { useFlowContext } from "../providers/FlowProvider";
import { useToastContext } from "../providers/ToastProvider";
import { applyContainerSizing } from "../utils/vegaSpecSizing";
import type { RenderCounts } from "../utils/renderOutcome";
import { prepareVegaInput } from "../utils/vegaInput";
import { usableCounts } from "../utils/vegaUsableRows";
import type { NodeEmptyReason } from "../utils/nodeEmptyState";
import { NODE_EMPTY_COPY, resolveGrammarEmptyReason } from "../utils/nodeEmptyState";
// The same stylesheet NodeEmptyState uses, so a blank Vega node looks exactly
// like a blank Data Pool or Simple View rather than merely similar.
import emptyStyles from "../components/nodes/NodeEmptyState.module.css";

// const schema = require('./vega-schema.json');
const vega = require("vega");
const lite = require("vega-lite");

if (typeof window !== 'undefined') {
  (window as any).__curio_vega = vega;
  (window as any).__curio_vegaLite = lite;
}

export const useVega = ({
  data,
  code,
  connected = true,
  hasSpec = true,
}: {
  data: any;
  code: string;
  /** Is anything wired into this node's input? */
  connected?: boolean;
  /** Does the editor hold a spec to compile? */
  hasSpec?: boolean;
}) => {
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

  // Why the node body is blank, when it is. Persistent, unlike a toast.
  const [emptyReason, setEmptyReason] = useState<NodeEmptyReason | null>(null);
  const [emptyDetail, setEmptyDetail] = useState<string | null>(null);
  const hasRunRef = React.useRef(false);

  const setEmptyState = (prepared: { emptyReason?: NodeEmptyReason; detail?: string }) => {
    setEmptyReason(prepared.emptyReason ?? null);
    setEmptyDetail(prepared.detail ?? null);
    renderEmptyState(prepared.emptyReason ?? null, prepared.detail ?? null);
  };

  /**
   * Write the empty state into the same div vega renders into.
   *
   * That div is addressed by DOM id and filled imperatively by vega, so there
   * is no React subtree to put a component in -- NodeEditor renders either the
   * output container or a `contentComponent`, never both. Writing the copy here
   * keeps it in the node body where it persists, which is the whole point: the
   * predecessor of this was a toast that vanished after a few seconds and left
   * an unexplained blank node behind (#224).
   *
   * The copy itself still comes from NODE_EMPTY_COPY, so it cannot drift from
   * what Data Pool and Simple View say for the shared states.
   */
  const renderEmptyState = (reason: NodeEmptyReason | null, detail: string | null) => {
    const host = document.getElementById("vega" + data.nodeId);
    if (!host) return;
    if (reason == null) return;

    const copy = NODE_EMPTY_COPY[reason];
    host.replaceChildren();
    host.setAttribute("data-curio-node-empty", reason);

    const wrapper = document.createElement("div");
    wrapper.className = emptyStyles.root;

    const title = document.createElement("span");
    title.className = emptyStyles.title;
    title.textContent = copy.title;
    wrapper.appendChild(title);

    const hint = document.createElement("span");
    hint.className = emptyStyles.hint;
    hint.textContent = detail ?? copy.hint;
    wrapper.appendChild(hint);

    host.appendChild(wrapper);
  };

  // Build a tupleid → original-index map by traversing the scene graph.
  // vega-lite derives intermediate datasets (e.g. for sorting) whose items have
  // different tuple IDs from the source "data" items, so we must read IDs from
  // the actual rendered items. Each item's datum carries __row_index__ (injected
  // before handing values to Vega) which propagates to derived items via rederive.
  const buildVgsidMap = (view: any): Map<number, number> => {
    const map = new Map<number, number>();
    const traverse = (node: any) => {
      if (!node) return;
      if (node.items) {
        for (const item of node.items) {
          if (item.datum?.__row_index__ !== undefined) {
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
    const prepared = await prepareVegaInput(data.input, lastSpecRef.current);
    setEmptyState(prepared);
    const values = prepared.values;

    let changeset = vega
      .changeset()
      .remove(() => true)
      .insert(values);

    const prevView = currentViewRef.current;
    if (prevView) {
      prevView.change("data", changeset).runAsync().then(() => {
        const map = buildVgsidMap(prevView);
        if (map.size > 0) vgsidToIndexRef.current = map;
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


  // The states that exist *before* anything compiles: nothing connected, an
  // upstream that has not run, an empty editor. Nothing else would report these
  // -- `prepareVegaInput` only runs on a compile or an input change -- so the
  // node body would just sit blank, which is the complaint #224 was filed
  // about, still true of the most-used visualisation node.
  useEffect(() => {
    if (currentViewRef.current != null) return;
    const reason = resolveGrammarEmptyReason({
      connected,
      hasInput: data.input != null && data.input !== "",
      hasSpec,
      hasRun: hasRunRef.current,
      inputProblem: emptyReason,
    });
    if (reason != null) renderEmptyState(reason, emptyDetail);
  }, [connected, hasSpec, data.input, emptyReason, emptyDetail]);

  useEffect(() => {
    const ro = new ResizeObserver(() => {
      if (currentViewRef.current != null) {
        currentViewRef.current.resize().runAsync();
      }
    });

    const el = document.getElementById("vega" + data.nodeId);
    if (el) ro.observe(el);
    return () => ro.disconnect();
  }, []);



  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const { workflowNameRef } = useFlowContext();
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
      NodeType.VIS_VEGA + "-" + data.nodeId,
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
    const prepared = await prepareVegaInput(data.input, specObj);
    setEmptyState(prepared);
    const values = prepared.values;
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
      // the verdict carries that same explanation.
      return { rowsIn, drawn: 0, usableRows, usableFields, explanation: prepared.detail };
    }

    specObj["data"] = { values: values, name: "data" };
    // Multi-view specs keep their authored size (vega-lite discards a
    // "container" injection there anyway) and the output pane scrolls; unit
    // and layer specs fill the node, unless the author sized them (#202).
    applyContainerSizing(specObj);

    let vegaspec = lite.compile(specObj).spec;

    // vega replaces the container's contents, but the marker attribute is ours
    // and would otherwise outlive the message it described.
    const host = document.getElementById("vega" + data.nodeId);
    host?.removeAttribute("data-curio-node-empty");
    hasRunRef.current = true;

    let view = new vega.View(vega.parse(vegaspec))
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
      // before the user can interact.
      return view.resize().runAsync();
    }).then(() => {
      const map = buildVgsidMap(view);
      if (map.size > 0) vgsidToIndexRef.current = map;
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

