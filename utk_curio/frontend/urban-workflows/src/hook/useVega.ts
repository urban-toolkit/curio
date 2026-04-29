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

    setCurrentView((prevView: any) => {
      prevView.change("data", changeset).runAsync().then(() => {
        const map = buildVgsidMap(prevView);
        if (map.size > 0) vgsidToIndexRef.current = map;
      });

      return prevView;
    });

  };

  useEffect(() => {
    try {
      if (currentView == null) return;
      processData();
    } catch (error: any) {
      showToast(error.message, "error");
    }
  }, [data.input]);

  // Auto-initialize the Vega view when a collaborating user joins and already has
  // both a compiled grammar (code) and connected data (data.input), but hasn't
  // manually clicked "Apply" yet (so currentView is still null).
  useEffect(() => {
    if (currentView !== null) return;
    if (!code || code.trim() === '' || code.trim() === '{}') return;
    const hasInput = data.input && data.input !== '';
    if (!hasInput) return;
    try {
      compileGrammar(JSON.parse(code));
    } catch (e) {
      console.error('Vega auto-init compileGrammar error:', e);
    }
  }, [data.input, code]); // eslint-disable-line react-hooks/exhaustive-deps


  useEffect(() => {
    const ro = new ResizeObserver((entries) => {
      for (let entry of entries) {
        if (currentViewRef.current != undefined) {
          window.dispatchEvent(new Event("resize"));
        }
      }
    });

    ro.observe(document.getElementById("vega" + data.nodeId) as HTMLElement);
  }, []);


  useEffect(() => {
    if (typeof data.interactionsCallback !== 'function') return;
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

    let dfStringIN = "";
    let dfStringOUT = "";

    if (data.input !== "") {
      let parsedIncome = data.input;

      let df = parsedIncome["data"];
      dfStringIN = JSON.stringify(df);
    }

    if (data.output) {
      let parsedIncome = data.output;

      let df = parsedIncome["data"];
      dfStringOUT = JSON.stringify(df);
    }

    nodeExecProv(
      startTime,
      endTime,
      workflowNameRef.current,
      NodeType.VIS_VEGA + "-" + data.nodeId,
      mapTypes(typesInput),
      mapTypes(typesOuput),
      code,
      dfStringIN,
      dfStringOUT
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
      .renderer("svg")
      .initialize("#vega" + data.nodeId)
      .hover();

    view.runAsync().then(() => {
      const map = buildVgsidMap(view);
      if (map.size > 0) vgsidToIndexRef.current = map;

      const container = document.getElementById("vega" + data.nodeId);
      const parentContainer = container?.parentElement;
      if (parentContainer) {
        // Check if the container has any elements with the class 'vega-bind'
        const hasBindings = container.querySelector(".vega-bind") !== null;

        // Dynamically adjust the padding of the parent container based on the presence of bindings
        parentContainer.style.paddingBottom = hasBindings ? "25px" : "";
      }
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
    if (typeof data.outputCallback === 'function') {
      data.outputCallback(data.nodeId, data.input);
    }
  };



  return { handleCompileGrammar };
};

