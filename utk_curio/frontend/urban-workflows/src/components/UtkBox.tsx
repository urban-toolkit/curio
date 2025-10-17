import React, { useState, useEffect, createElement } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer, buttonStyle } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faCircleInfo } from "@fortawesome/free-solid-svg-icons";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType, ResolutionTypeUTK, VisInteractionType } from "../constants";

import { Environment, GrammarInterpreter } from "utk";
import DescriptionModal from "./DescriptionModal";
import TemplateModal from "./TemplateModal";
import { useUserContext } from "../providers/UserProvider";
import { useFlowContext } from "../providers/FlowProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";
import "./Box.css"

import { fetchData } from '../services/api';

function UtkBox({ data, isConnectable }) {
  const [output, setOutput] = useState<{ code: string; content: string, outputType: string }>({
      code: "",
      content: "",
      outputType: ""
  }); // stores the output produced by the last execution of this box
  const [defaultGrammar, setDefaultGrammar] = useState<string>("{}");

  const { boxExecProv } = useProvenanceContext();

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

  const [code, setCode] = useState<string>("");
  const [sendCode, setSendCode] = useState();
  const [templateData, setTemplateData] = useState<Template | any>({});

  const [newTemplateFlag, setNewTemplateFlag] = useState(false);

  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();
  const { workflowNameRef } = useFlowContext();

  const [disablePlay, setDisablePlay] = useState<boolean>(true);

  const [inputData, setInputData] = useState();

  useEffect(() => {
    data.code = code;
  }, [code]);

  useEffect(() => {
    data.output = output;
  }, [output]);

  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: BoxType.VIS_UTK,
        name: data.templateName,
        description: data.description,
        accessLevel: data.accessLevel,
        code: data.defaultCode,
        custom: data.customTemplate,
      });
    }
  }, [data.templateId]);

  const setTemplateConfig = (template: Template) => {
    setTemplateData({ ...template });
  };

  const promptModal = (newTemplate: boolean = false) => {
    setNewTemplateFlag(newTemplate);
    setShowTemplateModal(true);
  };

  const closeModal = () => {
    setShowTemplateModal(false);
  };

  const promptDescription = () => {
    setDescriptionModal(true);
  };

  const closeDescription = () => {
    setDescriptionModal(false);
  };

  const updateTemplate = (template: Template) => {
    setTemplateConfig(template);
    editUserTemplate(template);
  };

  const setSendCodeCallback = (_sendCode: any) => {
    setSendCode(() => _sendCode);
  };

  Environment.serverless = true;

  const compileGrammar = (spec: string) => {
    try {
      const formatDate = (date: Date) => {
        // Get individual date components
        const month = date.toLocaleString("default", { month: "short" });
        const day = date.getDate();
        const year = date.getFullYear();
        const hours = date.getHours();
        const minutes = date.getMinutes();
        const seconds = date.getSeconds();

        // Format the string
        const formattedDate = `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;

        return formattedDate;
      };

      let startTime = formatDate(new Date());

      const outerMainDiv = document.getElementById(
        "utk" + data.nodeId + "outer"
      ) as HTMLElement;
      outerMainDiv.innerHTML = "";
      outerMainDiv.style.width = "100%";
      outerMainDiv.style.height = "100%";
      let mainDiv = document.createElement("div") as HTMLElement;
      mainDiv.style.width = "100%";
      mainDiv.style.height = "100%";
      mainDiv.id = "utk" + data.nodeId;
      outerMainDiv.appendChild(mainDiv);

      if (spec != "") {
        const grammarInterpreter = new GrammarInterpreter(
          data.nodeId,
          JSON.parse(spec),
          mainDiv,
          serverlessLayers,
          serverlessJoinedJsons,
          serverlessComponents,
          interactionCallback
        );
        setGrammarInterpreterObj(grammarInterpreter);
      }

      let endTime = formatDate(new Date());

      const getType = (inputs: any[]) => {
        let typesInput: string[] = [];

        for (const input of inputs) {
          let parsedInput = input;

          if (typeof input == "string") parsedInput = JSON.parse(parsedInput);

          if (parsedInput.dataType == "outputs") {
            typesInput = typesInput.concat(getType(parsedInput.data));
          } else {
            typesInput.push(parsedInput.dataType);
          }
        }

        return typesInput;
      };

      const mapTypes = (typesList: string[]) => {
        let mapTypes: any = {
          DATAFRAME: 0,
          GEODATAFRAME: 0,
          VALUE: 0,
          LIST: 0,
          JSON: 0,
        };

        for (const typeValue of typesList) {
          if (
            typeValue == "int" ||
            typeValue == "str" ||
            typeValue == "float" ||
            typeValue == "bool"
          ) {
            mapTypes["VALUE"] = 1;
          } else if (typeValue == "list") {
            mapTypes["LIST"] = 1;
          } else if (typeValue == "dict") {
            mapTypes["JSON"] = 1;
          } else if (typeValue == "dataframe") {
            mapTypes["DATAFRAME"] = 1;
          } else if (typeValue == "geodataframe") {
            mapTypes["GEODATAFRAME"] = 1;
          }
        }

        return mapTypes;
      };

      let typesInput: string[] = [];

      if (data.input != "") typesInput = getType([data.input]);

      let typesOuput: string[] = [...typesInput];

      let dfIN = []
      let dfOUT = ''

      if (data.input) {
        data.input.data.features.forEach(item => { 
          // Remove geometry key
          const { geometry, ...rest } = item;
          dfIN.push(JSON.stringify(rest));
        });
      }
      

      setInputData(dfIN)

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

      setOutput({ code: "success", content: "" });
    } catch (error: any) {
      setOutput({ code: "error", content: error.message });
    }
  };

  useEffect(() => {
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
  }, [interactionArrays]);

  // list will contain all coordinates from all layers
  const get_camera = (coordinates: number[]) => {
    let minLat = undefined;
    let minLon = undefined;
    let maxLat = undefined;
    let maxLon = undefined;

    for (let i = 0; i < Math.trunc(coordinates.length / 3); i++) {
      if (minLat == undefined || coordinates[i * 3] < minLat) {
        minLat = coordinates[i * 3];
      }

      if (minLon == undefined || coordinates[i * 3 + 1] < minLon) {
        minLon = coordinates[i * 3 + 1];
      }

      if (maxLat == undefined || coordinates[i * 3] > maxLat) {
        maxLat = coordinates[i * 3];
      }

      if (maxLon == undefined || coordinates[i * 3 + 1] > maxLon) {
        maxLon = coordinates[i * 3 + 1];
      }
    }

    let center = [0, 0, 1];

    if (
      minLat != undefined &&
      maxLat != undefined &&
      minLon != undefined &&
      maxLon != undefined
    )
      center = [(minLat + maxLat) / 2.0, (minLon + maxLon) / 2.0, 1];

    return {
      position: center,
      direction: {
        right: [0, 0, 3000],
        lookAt: [0, 0, 0],
        up: [0, 1, 0],
      },
    };
  };

  //Interaction
  useEffect(() => {
  let dfIN: string[] = [];

  if (data.input.data) {
    console.log(data)
    data.input.data.features.forEach((item: any) => {
      // Remove "geometry" key
      const { geometry, ...rest } = item;
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

    const formatDate = (date: Date): string => {
      const month = date.toLocaleString("default", { month: "short" });
      const day = date.getDate();
      const year = date.getFullYear();
      const hours = date.getHours();
      const minutes = date.getMinutes();
      const seconds = date.getSeconds();

      return `${month} ${day} ${year} ${hours}:${minutes}:${seconds}`;
    };

    const endTime = formatDate(new Date());
    const startTime = formatDate(new Date());

    const getType = (inputs: any[]): string[] => {
      let typesInput: string[] = [];

      for (const input of inputs) {
        let parsedInput = input;

        if (typeof input === "string") {
          parsedInput = JSON.parse(input);
        }

        if (parsedInput.dataType === "outputs") {
          typesInput = typesInput.concat(getType(parsedInput.data));
        } else {
          typesInput.push(parsedInput.dataType);
        }
      }

      return typesInput;
    };

    let typesInput: string[] = [];
    if (data.input !== "") {
      typesInput = getType([data.input]);
    }

    const typesOutput = [...typesInput];

    const mapTypes = (typesList: string[]) => {
      const mapTypes = {
        DATAFRAME: 0,
        GEODATAFRAME: 0,
        VALUE: 0,
        LIST: 0,
        JSON: 0,
      };

      for (const typeValue of typesList) {
        if (["int", "str", "float", "bool"].includes(typeValue)) {
          mapTypes.VALUE = 1;
        } else if (typeValue === "list") {
          mapTypes.LIST = 1;
        } else if (typeValue === "dict") {
          mapTypes.JSON = 1;
        } else if (typeValue === "dataframe") {
          mapTypes.DATAFRAME = 1;
        } else if (typeValue === "geodataframe") {
          mapTypes.GEODATAFRAME = 1;
        }
      }

      return mapTypes;
    };

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


  useEffect(() => {
    const processData = async () => {
      if (data.input != "") {
        let parsedInput = data.input; //JSON.parse(data.input);

        let validInput = true;

        console.log("parsedInput.dataType", parsedInput.dataType);

        // validate input
        if (parsedInput.dataType == "outputs") {
          for (const elem of parsedInput.data) {
            if (elem.dataType != "geodataframe") {
              alert("UTK box can only receive geodataframes");
              validInput = false;
            }
          }
        } else if (parsedInput.dataType != "geodataframe") {
          alert("UTK box can only receive geodataframes");
          validInput = false;
        }

        // TODO: Refresh UTK

        if (validInput) {
          // send data to UTK
          let geojsons;
          if(parsedInput.path) {
            geojsons = await fetchData(`${parsedInput.path}`);
          }
          else {
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

            if (typeof geojson == "string")
              parsedGeojson = JSON.parse(parsedGeojson);

            if (
              parsedGeojson.metadata != undefined &&
              parsedGeojson.metadata.name == undefined
            ) {
              alert("All geojson layers for UTK must be named");
              return;
            }

            if (parsedGeojson.metadata == undefined) {
              alert("All geojson layers for UTK must be named");
              return;
            }
          }

          fetch(process.env.BACKEND_URL + "/toLayers", {
            method: "POST",
            body: JSON.stringify({
              geojsons: geojsons,
            }),
            headers: {
              "Content-type": "application/json; charset=UTF-8",
            },
          })
            .then((response) => response.json())
            .then((json: any) => {
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
                  allCoordinates = allCoordinates.concat(
                    geometry.geometry.coordinates
                  );
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

                          if (objectInteracted){
                            console.log("interacted with", j);
                            interactionPerGeom.push(j);
                          }
                        }
                        else if (resolutionModeRef.current == ResolutionTypeUTK.BRUSHING) {
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
            });

          if (grammarInterpreterObj != null) {
            for (let i = 0; i < geojsons.length; i++) {
              // let parsedGeojson = JSON.parse(geojsons[i]);
              let parsedGeojson = geojsons[i];
              // console.log(parsedGeojson);

              let interactedValues = parsedGeojson.features.map(
                (feature: any) => {
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
                }
              );
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

          // setOutput("success");
          data.outputCallback(data.nodeId, data.input);
          await stallDisablePlay();
        }
      }

    };

    processData();

  }, [data.input]);

  async function stallDisablePlay() {
    function delay(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }
    await delay(5000);
    setDisablePlay(false);
  }

  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const listenerSelection = (event: any) => {
    if (event.target != null) {
      let target = event.target as HTMLOptionElement;
      const selectedOption = target.value;

      if (Object.keys(grammarMapObjRef.current).length > 0) {
        let oldInteractions = [...grammarMapObjRef.current.interactions];

        let newGrammarMap = {
          ...grammarMapObjRef.current,
          interactions: oldInteractions.map((elem: any) => {
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

  return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      {/* Data flows in both ways */}
      <Handle
        type="source"
        position={Position.Top}
        id="in/out"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        output={output}
        templateData={templateData}
        code={code}
        user={user}
        handleType={"in/out"}
        disablePlay={disablePlay}
        sendCodeToWidgets={sendCode}
        setOutputCallback={setOutput}
        promptModal={promptModal}
        updateTemplate={updateTemplate}
        promptDescription={promptDescription}
        setTemplateConfig={setTemplateConfig}
      >
        <InputIcon type="N" />
        {/* <label htmlFor="interactionRes" style={{ marginRight: "5px" }}>
                    Interaction resolution:{" "}
                </label>
                <select
                    name="interactionRes"
                    id={data.nodeId + "_" + "interactionRes"}
                    value={resolutionModeRef.current}
                    onChange={listenerSelection}
                >
                    <option value="NONE">None</option>
                    <option value="PICKING">Picking</option>
                    <option value="BRUSHING">Brushing</option>
                </select> */}
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.VIS_UTK}
          name={templateData.name}
          description={templateData.description}
          accessLevel={templateData.accessLevel}
          show={showDescriptionModal}
          handleClose={closeDescription}
          custom={templateData.custom}
        />
        <TemplateModal
          newTemplateFlag={newTemplateFlag}
          templateId={templateData.id}
          callBack={setTemplateConfig}
          show={showTemplateModal}
          handleClose={closeModal}
          boxType={BoxType.VIS_UTK}
          code={code}
        />
        <BoxEditor
          outputId={"utk" + data.nodeId + "outer"}
          customWidgetsCallback={customWidgetsCallback}
          setSendCodeCallback={setSendCodeCallback}
          code={false}
          grammar={true}
          widgets={true}
          setOutputCallback={setOutput}
          data={data}
          output={output}
          boxType={BoxType.VIS_UTK}
          applyGrammar={compileGrammar}
          defaultValue={
            templateData.code == undefined ? data.defaultCode ? data.defaultCode : defaultGrammar : templateData.code
          }
          // readOnly={
          //   (templateData.custom != undefined &&
          //     templateData.custom == false) ||
          //   !(user != null && user.type == "programmer")
          // }
          readOnly={
            (templateData.custom != undefined &&
              templateData.custom == false)
          }
          floatCode={setCode}
        />

        <OutputIcon type="N" />
      </BoxContainer>
    </>
  );
}

export default UtkBox;
