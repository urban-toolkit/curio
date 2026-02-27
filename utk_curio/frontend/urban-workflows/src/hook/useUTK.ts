import React, { useEffect, useRef, useState } from "react";

import { BoxType, ResolutionTypeUTK, VisInteractionType } from "../constants";
import { Environment, GrammarInterpreter } from "utk";

import { get_camera } from "../utils/parsing";
import { fetchData } from "../services/api";
import { formatDate, getType, mapTypes } from "../utils/formatters";

import { ICodeData } from '../types';
import { useFlowContext } from "../providers/FlowProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";

export function useUTK({ data, code }: { data: any, code: string }) {
  const [output, setOutput] = useState<ICodeData>({ code: '', content: '' });
  const { workflowNameRef } = useFlowContext();

  const [inputData, setInputData] = useState();

  const [defaultGrammar, setDefaultGrammar] = useState<string>("{}");

  const [resolutionMode, _setResolutionMode] = useState<ResolutionTypeUTK>(
    ResolutionTypeUTK.NONE
  );
  const resolutionModeRef = React.useRef(resolutionMode);
  const setResolutionMode = (data: any) => {
    resolutionModeRef.current = data;
    _setResolutionMode(data);
  };

  const [interactions, _setInteractions] = useState<any>({}); // {[layerId]: {type: point, data: [indices]}} // for UTK we are only going to use type point
  const interactionsRef = React.useRef(interactions);
  const setInteractions = (data: any) => {
    interactionsRef.current = data;
    _setInteractions(data);
  };

  const [interactionArrays, setInteractionArrays] = useState<any>({}); // {[layerId] -> []}
  const [grammarInterpreterObj, setGrammarInterpreterObj] = useState<any>(null);
  const [grammarMapObj, _setGrammarMapObj] = useState<any>({});
  const grammarMapObjRef = React.useRef(grammarMapObj);
  const setGrammarMapObj = (data: any) => {
    grammarMapObjRef.current = data;
    _setGrammarMapObj(data);
  };

  const [interactionCallback, setInteractionCallbacks] = useState<
    { knotId: string; callback: any }[]
  >([]);
  const [serverlessLayers, setServerlessLayers] = useState<any>([]);
  const [serverlessJoinedJsons, setServerlessJoinedJsons] = useState<any>([]);
  const [serverlessComponents, setServerlessComponents] = useState<any>([]);

  const [isProcessing, setIsProcessing] = useState<boolean>(false);
  const [sendCode, setSendCode] = useState<Function>(undefined);

  const setSendCodeCallback = (_sendCode: any) => {
    setSendCode(() => (codeArg: string) => {
        _sendCode(codeArg);
    });
  };


  const setToLayers = async (geojsons: any) => {
    const toLayersResponse = await fetch(
      process.env.BACKEND_URL + "/toLayers",
      {
        method: "POST",
        body: JSON.stringify({
          geojsons: geojsons,
        }),
        headers: {
          "Content-type": "application/json; charset=UTF-8",
        },
      }
    );
    const json: any = await toLayersResponse.json();

    let generatedGrammar: any = {};

    generatedGrammar["components"] = [
      {
        id: "grammar_map",
        position: {
          width: [1, 12],
          height: [1, 4],
        },
      },
    ];

    generatedGrammar["knots"] = [];
    generatedGrammar["ex_knots"] = [];

    let allCoordinates: number[] = [];

    for (let i = 0; i < json.layers.length; i++) {
      for (const geometry of json.layers[i].data) {
        allCoordinates = allCoordinates.concat(geometry.geometry.coordinates);
      }

      let layer = json.layers[i];
      let added = false;

      for (const joinedJson of json.joinedJsons) {
        if (joinedJson.id == layer.id) {
          for (let j = 0; j < joinedJson.incomingId.length; j++) {
            let in_name = joinedJson.incomingId[j];

            added = true;
            generatedGrammar["ex_knots"].push({
              // joined layers
              id: layer.id + j,
              out_name: layer.id,
              in_name: in_name,
            });
          }
        }
      }

      if (!added) {
        generatedGrammar["ex_knots"].push({
          // pure layer
          id: layer.id + "0",
          out_name: layer.id,
        });
      }
    }

    generatedGrammar["grid"] = {
      width: 12,
      height: 4,
    };

    generatedGrammar["grammar"] = false;

    setDefaultGrammar(JSON.stringify(generatedGrammar, null, 4));

    let camera = get_camera(allCoordinates);

    // temp
    let components = [
      {
        id: "grammar_map",
        json: {
          camera: camera,
          knots: generatedGrammar["ex_knots"].map((ex_knot: any) => {
            return ex_knot.id;
          }),
          interactions: generatedGrammar["ex_knots"].map((_: any) => {
            return resolutionModeRef.current;
          }),
          widgets: [
            {
              type: "TOGGLE_KNOT",
            },
          ],
          grammar_type: "MAP",
        },
      },
    ];

    setGrammarMapObj(components[0].json);

    let knotToLayerDict: any = {};

    let knotsIds = generatedGrammar["ex_knots"].map((ex_knot: any) => {
      knotToLayerDict[ex_knot.id] = ex_knot.out_name;
      return ex_knot.id;
    });

    let interactionCallbacks: any = [];

    for (const knotId of knotsIds) {
      interactionCallbacks.push({
        knotId: knotId,
        callback: (interacted: number[], coordsPerGeom: number[]) => {
          if (resolutionModeRef.current != ResolutionTypeUTK.NONE) {
            let startingIndex = 0;
            let interactionPerGeom: number[] = [];

            for (let j = 0; j < coordsPerGeom.length; j++) {
              let nCoords = coordsPerGeom[j];

              if (resolutionModeRef.current == ResolutionTypeUTK.PICKING) {
                let objectInteracted = true;

                for (let i = startingIndex; i < startingIndex + nCoords; i++) {
                  let value = interacted[i];

                  if (value == 0) {
                    // in picking all coordinates of an object must be selected
                    objectInteracted = false;
                    break;
                  }
                }

                if (objectInteracted) {
                  console.log("interacted with", j);
                  interactionPerGeom.push(j);
                }
              } else if (
                resolutionModeRef.current == ResolutionTypeUTK.BRUSHING
              ) {
                let objectInteracted = false;

                for (let i = startingIndex; i < startingIndex + nCoords; i++) {
                  let value = interacted[i];

                  if (value == 1) {
                    // in brushing only one coordinate needs to be selected for the object to be considered interacted with
                    objectInteracted = true;
                    break;
                  }
                }

                if (objectInteracted) interactionPerGeom.push(j);
              }

              startingIndex += nCoords;
            }

            let interactionsKeys = Object.keys(interactionsRef.current);

            let newObj: any = {};
            for (const interactionKey of interactionsKeys) {
              newObj[interactionKey] = {
                type: interactionsRef.current[interactionKey].type,
                data: interactionsRef.current[interactionKey].data,
                priority: 0,
                source: BoxType.VIS_UTK,
              };
            }

            newObj[knotToLayerDict[knotId]] = {
              type: VisInteractionType.POINT,
              data: interactionPerGeom,
              priority: 1,
              source: BoxType.VIS_UTK,
            };

            setInteractions(newObj);
          }
        },
      });

      if (grammarInterpreterObj != null) {
        grammarInterpreterObj.setServerlessApi(
          [],
          [],
          [],
          interactionCallbacks
        );
      }

      setInteractionCallbacks(interactionCallbacks);

      // ServerlessApi.addInteractionCallback(knotId, (interacted: number[], coordsPerGeom: number[]) => {
      //     if(resolutionModeRef.current != ResolutionTypeUTK.NONE){
      //         let startingIndex = 0;
      //         let interactionPerGeom: number[] = [];

      //         for(let j = 0; j < coordsPerGeom.length; j++){
      //             let nCoords = coordsPerGeom[j];

      //             if(resolutionModeRef.current == ResolutionTypeUTK.PICKING){
      //                 let objectInteracted = true;

      //                 for(let i = startingIndex; i < startingIndex+nCoords; i++){
      //                     let value = interacted[i];

      //                     if(value == 0){ // in picking all coordinates of an object must be selected
      //                         objectInteracted = false;
      //                         break;
      //                     }
      //                 }

      //                 if(objectInteracted)
      //                     interactionPerGeom.push(j);
      //             }else if(resolutionModeRef.current == ResolutionTypeUTK.BRUSHING){
      //                 let objectInteracted = false;

      //                 for(let i = startingIndex; i < startingIndex+nCoords; i++){
      //                     let value = interacted[i];

      //                     if(value == 1){ // in brushing only one coordinate needs to be selected for the object to be considered interacted with
      //                         objectInteracted = true;
      //                         break;
      //                     }
      //                 }

      //                 if(objectInteracted)
      //                     interactionPerGeom.push(j);
      //             }

      //             startingIndex += nCoords;
      //         }

      //         let interactionsKeys = Object.keys(interactionsRef.current);

      //         let newObj: any = {};
      //         for(const interactionKey of interactionsKeys){
      //             newObj[interactionKey] = {type: interactionsRef.current[interactionKey].type, data: interactionsRef.current[interactionKey].data, priority: 0, source: BoxType.VIS_UTK};
      //         }

      //         newObj[knotToLayerDict[knotId]] = {type: VisInteractionType.POINT, data: interactionPerGeom, priority: 1, source: BoxType.VIS_UTK}

      //         setInteractions(newObj);
      //     }
      // });
    }

    setServerlessLayers(json.layers);
    setServerlessJoinedJsons(json.joinedJsons);
    setServerlessComponents(components);

    if (grammarInterpreterObj != null) {
      for (let i = 0; i < geojsons.length; i++) {
        // let parsedGeojson = JSON.parse(geojsons[i]);
        let parsedGeojson = geojsons[i];
        // console.log(parsedGeojson);

        let interactedValues = parsedGeojson.features.map((feature: any) => {
          if (feature.properties.interacted != undefined) {
            if (feature.properties.building_id != undefined)
              // it is a building layer
              return {
                interacted: parseInt(feature.properties.interacted),
                building_id: feature.properties.building_id,
              };
            else return parseInt(feature.properties.interacted);
          } else {
            if (feature.properties.building_id != undefined)
              // it is a building layer
              return {
                interacted: 0,
                building_id: feature.properties.building_id,
              };
            else return 0;
          }
        });
        // let interactedValues = [];
        // for (let i = 0; i < parsedGeojson.interacted.length; i++) {
        //   let interacted = parsedGeojson.interacted[i];
        //   let property = parsedGeojson.properties[i];

        //   if (interacted !== undefined) {
        //     interacted = parseInt(interacted);
        //   }

        //   if (property.building_id !== undefined) {
        //     interactedValues.push({
        //       interacted,
        //       building_id: property.building_id,
        //     });
        //   } else {
        //     interactedValues.push(interacted);
        //   }
        // }

        let layerName = "layer" + i;

        if (
          parsedGeojson.metadata != undefined &&
          parsedGeojson.metadata.name != undefined
        ) {
          layerName = parsedGeojson.metadata.name;
        }

        setInteractionArrays({
          ...interactionArrays,
          [layerName]: interactedValues,
        });
      }
    }

    return { generatedGrammar, json, components, interactionCallbacks };
  };

  const { boxExecProv } = useProvenanceContext();

  Environment.serverless = true;
  const handleCompileGrammar = async (spec: string) => {
    let startTime = formatDate(new Date());

    compileGrammar(spec);

    let endTime = formatDate(new Date());

    let typesInput: string[] = [];

    if (data.input != "") typesInput = getType([data.input]);

    let typesOuput: string[] = [...typesInput];

    let dfIN = [];
    let dfOUT = "";

    if (data.input && data.input.data && data.input.data.features) {
      // Remove geometry key
      data.input.data.features.forEach(({ geometry, ...rest }: any) => {
        dfIN.push(JSON.stringify(rest));
      });
    }

    setInputData(dfIN);

    boxExecProv(
      startTime,
      endTime,
      workflowNameRef.current,
      BoxType.VIS_UTK + "-" + data.nodeId,
      mapTypes(typesInput),
      mapTypes(typesOuput),
      code,
      JSON.stringify(dfIN),
      dfOUT
    );

    fetch(`${process.env.BACKEND_URL}/insert_visualization`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        data: {
          activity_name: BoxType.VIS_UTK + "-" + data.nodeId,
        },
      }),
    });
  };

  const compileGrammar = (
    spec: string,
    overrideLayers?: any[],
    overrideJoinedJsons?: any[],
    overrideComponents?: any[],
    overrideCallbacks?: any[]
  ) => {
    const outerMainDiv = document.getElementById("utk" + data.nodeId + "outer") as HTMLElement;
    if (!outerMainDiv) {
      console.warn("UTK output container not found, skipping compilation");
      return;
    }
    outerMainDiv.innerHTML = "";
    outerMainDiv.style.width = "100%";
    outerMainDiv.style.height = "100%";
    let mainDiv = document.createElement("div") as HTMLElement;
    mainDiv.style.width = "100%";
    mainDiv.style.height = "100%";
    mainDiv.id = "utk" + data.nodeId;
    outerMainDiv.appendChild(mainDiv);

    if (spec != "" && spec != "{}") {
      const parsed = JSON.parse(spec);

      // Guard: grammar must have required fields before compilation
      if (!parsed.grid || !parsed.components || !parsed.knots) {
        console.warn("Grammar not ready yet, missing required fields (grid/components/knots)");
        return;
      }

      const grammarInterpreter = new GrammarInterpreter(
        data.nodeId,
        parsed,
        mainDiv,
        overrideLayers || serverlessLayers,
        overrideJoinedJsons || serverlessJoinedJsons,
        overrideComponents || serverlessComponents,
        overrideCallbacks || interactionCallback
      );
      setGrammarInterpreterObj(grammarInterpreter);
    }

    // setOutput("success");
    data.outputCallback(data.nodeId, data.input);
  };

  //Interaction
  useEffect(() => {
    let dfIN: string[] = [];

    if (data.input.data) {
      console.log(data);
      data.input.data.features.forEach(({ geometry, ...rest }: any) => {
        dfIN.push(JSON.stringify(rest));
      });
    }

    const isEqual = JSON.stringify(inputData) === JSON.stringify(dfIN);

    if (!isEqual && inputData !== undefined) {
      fetch(`${process.env.BACKEND_URL}/insert_attribute_value_change`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          data: {
            activity_name: BoxType.VIS_UTK + "-" + data.nodeId,
          },
        }),
      });

      setInputData(dfIN);

      const endTime = formatDate(new Date());
      const startTime = formatDate(new Date());

      let typesInput: string[] = [];
      if (data.input !== "") {
        typesInput = getType([data.input]);
      }

      const typesOutput = [...typesInput];

      boxExecProv(
        startTime,
        endTime,
        workflowNameRef.current,
        BoxType.VIS_UTK + "-" + data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOutput),
        code,
        JSON.stringify(dfIN),
        "",
        true
      );

      fetch(`${process.env.BACKEND_URL}/insert_visualization`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          data: {
            activity_name: BoxType.VIS_UTK + "-" + data.nodeId,
          },
        }),
      });
    }
  }, [data]);

  const parseOutputData = () => {
    if (grammarInterpreterObj != null && data.input != "") {
      let layerIds = Object.keys(interactionArrays);

      for (const layerId of layerIds) {
        if (typeof interactionArrays[layerId][0] === "object") {
          // building layer

          let uniqueBuildingIndex = -1;
          let currentBuildingId = -1;

          let uniqueIdInteractionArray: number[] = [];

          for (const value of interactionArrays[layerId]) {
            if (currentBuildingId != value.building_id) {
              currentBuildingId = value.building_id;
              uniqueBuildingIndex += 1;
              uniqueIdInteractionArray.push(value.interacted);
            }
          }

          grammarInterpreterObj.overwriteSelectedElements(
            uniqueIdInteractionArray,
            layerId
          );
        } else {
          grammarInterpreterObj.overwriteSelectedElements(
            interactionArrays[layerId],
            layerId
          );
        }
      }
    }
  };

  useEffect(() => {
    if (data.input != "") {
      parseOutputData();
    }
  }, [interactionArrays]);

  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const parseInputData = async (input: any) => {
    let parsedInput = data.input; //JSON.parse(data.input);
    const errorMsg = "UTK box can only receive geodataframes";
    if (parsedInput == "") {
      throw new Error(errorMsg);
    }

    console.log("parsedInput.dataType", parsedInput.dataType);

    // validate input
    if (parsedInput.dataType == "outputs") {
      for (const elem of parsedInput.data) {
        if (elem.dataType != "geodataframe") {
          throw new Error(errorMsg);
        }
      }
    } else if (parsedInput.dataType != "geodataframe") {
      throw new Error(errorMsg);
    }

    // Parse geojsons to send data to UTK
    let geojsons;
    if (parsedInput.path) {
      geojsons = await fetchData(`${parsedInput.path}`);
    } else {
      geojsons = parsedInput;
    }

    // console.log(geojsons);
    // let geoJsons: any = [];

    if (geojsons.dataType == "outputs") {
      geojsons = geojsons.data.map((elem: any) => {
        return elem.data;
      });
    } else {
      geojsons = [geojsons.data];
    }

    for (const geojson of geojsons) {
      let parsedGeojson = geojson;

      if (typeof geojson == "string") parsedGeojson = JSON.parse(parsedGeojson);

      if (
        (parsedGeojson.metadata == undefined || parsedGeojson.metadata.name == undefined)
      ) {
        throw new Error("All geojson layers for UTK must be named");
      }

    }

    return geojsons;
  }

  const processData = async () => {
    setIsProcessing(true);

    let values;
    try {
      values = await parseInputData(data.input);
    } catch (error: any) {
      setOutput({ code: 'error', content: error.message, outputType: '' });
      setIsProcessing(false);
      alert(error.message);
    }

    const { generatedGrammar, json, components, interactionCallbacks } =
      await setToLayers(values);

    // Signal that grammar/data processing is complete
    setIsProcessing(false);
    // Refresh UTK
    setOutput({code: 'exec', content: ''});
    sendCode(code)

  };

  useEffect(() => {
    console.log('data.input')
    if (data.input == "") return;
    processData();
  }, [data.input]);

  const listenerSelection = (event: any) => {
    if (event.target != null) {
      let target = event.target as HTMLOptionElement;
      const selectedOption = target.value;

      if (Object.keys(grammarMapObjRef.current).length > 0) {
        let oldInteractions = [...grammarMapObjRef.current.interactions];

        let newGrammarMap = {
          ...grammarMapObjRef.current,
          interactions: oldInteractions.map(() => {
            return selectedOption;
          }),
        };

        setGrammarMapObj(newGrammarMap);

        if (grammarInterpreterObj != null) {
          grammarInterpreterObj.setServerlessApi(
            [],
            [],
            [{ id: "grammar_map", json: newGrammarMap }],
            {}
          );
        }

        setServerlessComponents([{ id: "grammar_map", json: newGrammarMap }]);
      }
      setResolutionMode(selectedOption);
    }
  };

  const customWidgetsCallback = (div: HTMLElement) => {
    const label = document.createElement("label");
    label.setAttribute("for", "interactionRes");
    label.textContent = "Interaction resolution: ";
    label.style.marginRight = "5px";

    const select = document.createElement("select");
    select.setAttribute("name", "interactionRes");
    select.setAttribute("id", data.nodeId + "_interactionRes");
    select.value = resolutionModeRef.current;
    select.addEventListener("change", listenerSelection);

    const optionNone = document.createElement("option");
    optionNone.setAttribute("value", "NONE");
    optionNone.textContent = "None";

    const optionPicking = document.createElement("option");
    optionPicking.setAttribute("value", "PICKING");
    optionPicking.textContent = "Picking";

    const optionBrushing = document.createElement("option");
    optionBrushing.setAttribute("value", "BRUSHING");
    optionBrushing.textContent = "Brushing";

    select.appendChild(optionNone);
    select.appendChild(optionPicking);
    select.appendChild(optionBrushing);

    div.appendChild(label);
    div.appendChild(select);
  };

  return {
    defaultGrammar,
    handleCompileGrammar,
    customWidgetsCallback,

    showLoading: isProcessing,
    sendCode,

    setSendCodeCallback,

    setOutput,
    output,
  };
}
