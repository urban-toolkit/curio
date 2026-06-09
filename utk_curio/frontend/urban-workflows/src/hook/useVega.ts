import React, { useEffect, useState } from "react";
import { NodeType, VisInteractionType } from "../constants";
import { useProvenanceContext } from "../providers/ProvenanceProvider";

import { fetchData } from "../services/api";
import { formatDate, mapTypes } from "../utils/formatters";
import { parseDataframe, parseGeoDataframe } from "../utils/parsing";
import { useFlowContext } from "../providers/FlowProvider";
import { useToastContext } from "../providers/ToastProvider";

// const schema = require('./vega-schema.json');
const vega = require("vega");
const lite = require("vega-lite");

if (typeof window !== 'undefined') {
  (window as any).__curio_vega = vega;
  (window as any).__curio_vegaLite = lite;
}

export const useVega = ({ data, code }: { data: any; code: string; }) => {
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

  const parseInputData = async (input: any) => {
    let values: any = [];
    let parsedInput = data.input; //JSON.parse(data.input);
    if (parsedInput == "" || parsedInput == null || parsedInput == undefined) {
      return [];
    }

    let inputType = parsedInput.dataType; // JSON.parse(data.input)["dataType"];

    if (inputType != "dataframe" && inputType !== "geodataframe") {
      throw new Error(inputType + " is not a valid input type for the 2D Plot (Vega-Lite)");
    }

    // if (parsedInput.dataType == "dataframe" || parsedInput.dataType == "geodataframe") {
    //   if(parsedInput.path) {
    //     values = await fetchData(`${parsedInput.path}`, true);
    //   }
    //   else {
    //     values = transformToVega(parsedInput);
    //   }
    // }

    const parserMap = {
      "dataframe": parseDataframe,
      "geodataframe": parseGeoDataframe,
    };

    const parser = parserMap[parsedInput.dataType as keyof typeof parserMap];

    if (parser) {
      if (parsedInput.path) {
        values = await fetchData(parsedInput.path);
        values = parser(values.data);
      } else {
        values = parser(parsedInput.data);
      }
    }

    values.forEach((v: any, i: number) => { v.__row_index__ = i; });
    return values;
  }
  const processData = async () => {
    // hot reload visualizations with new incoming data
    if (currentView == null) {
      throw new Error("Current view is not initialized");
    }

    // let currentViewState = currentView.getState();

    let values = await parseInputData(data.input);

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
    try {
      if (currentView == null) return;
      processData();
    } catch (error: any) {
      showToast(error.message, "error");
    }
  }, [data.input]);


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
  const handleCompileGrammar = async (spec: string) => {
    let startTime = formatDate(new Date());

    await compileGrammar(JSON.parse(spec));

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

  };

  const compileGrammar = async (specObj: any) => {
    let values: any = await parseInputData(data.input);

    specObj["data"] = { values: values, name: "data" };
    specObj["height"] = "container";
    specObj["width"] = "container";
    // specObj["autosize"] = {type: "fit", contains: "padding", resize: true};

    let vegaspec = lite.compile(specObj).spec;

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

    view.runAsync().then(() => {
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
    });

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
  };



  return { handleCompileGrammar };
};

