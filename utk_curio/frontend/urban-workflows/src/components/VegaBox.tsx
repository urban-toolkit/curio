import React, { useEffect, useState } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer, iconStyle } from "./styles";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType, VisInteractionType } from "../constants";
import DescriptionModal from "./DescriptionModal";
import TemplateModal from "./TemplateModal";
import { useUserContext } from "../providers/UserProvider";
import { useFlowContext } from "../providers/FlowProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faExpand } from "@fortawesome/free-solid-svg-icons";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";
import "./Box.css"

import { fetchData, transformToVega } from '../services/api';
import { Dict } from "vega-lite";

// const schema = require('./vega-schema.json');

const vega = require("vega");
const lite = require("vega-lite");

function VegaBox({ data, isConnectable }) {
  const [output, setOutput] = useState<{ code: string; content: string, outputType: string }>({
      code: "",
      content: "",
      outputType: ""
  }); // stores the output produced by the last execution of this box
  const [interactions, _setInteractions] = useState<any>({}); // {signal: {type: point/interval, data: }} // if type point data contains list of object ids. If type is interval data is an object where each key is an attribute with intervals or lists

  const [currentView, _setCurrentView] = useState<any>(null);
  const currentViewRef = React.useRef(currentView);
  const setCurrentView = (data: any) => {
    currentViewRef.current = data;
    _setCurrentView(data);
  };

  const [code, setCode] = useState<string>("");
  const [sendCode, setSendCode] = useState();
  const [templateData, setTemplateData] = useState<Template | any>({});

  const [newTemplateFlag, setNewTemplateFlag] = useState(false);

  const { boxExecProv } = useProvenanceContext();

  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();
  const { workflowNameRef } = useFlowContext();

  useEffect(() => {
    data.code = code;
  }, [code]);

  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: BoxType.VIS_VEGA,
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

  const interactionsRef = React.useRef(interactions);
  const setInteractions = (data: any) => {
    interactionsRef.current = data;
    _setInteractions(data);
  };

  const parseDataframe = (data: any) => {
    console.log("Parsing", data);
    let columns = Object.keys(data);
    const values = Object.keys(data[columns[0]]).map((key) => {
      let obj: any = {};

      for (const column of columns) {
        obj[column] = data[column][key];
      }

      return obj;
    });

    return values;
  };

  const parseGeoDataframe = (data: any) => {
    console.log("Parsing", data);
    let values = data.features.map((feature: any) => {
      return { ...feature.properties };
    });

    return values;
  };

  useEffect(() => {
    const updateView = async () => {
      // hot reload visualizations with new incoming data
      if (currentView != null) {
        let values: any = [];

        if (data.input != "") {
          // let currentViewState = currentView.getState();

          let parsedInput = data.input;//JSON.parse(data.input);

          // if (parsedInput.dataType == "dataframe")
          //   values = await fetchData(`${parsedInput.path}`, true);
          // else if (parsedInput.dataType == "geodataframe")
          //   values = await fetchData(`${parsedInput.path}`, true);

          const parserMap = {
            "dataframe": parseDataframe,
            "geodataframe": parseGeoDataframe
          };

          const parser = parserMap[parsedInput.dataType];

          if (parser) {
            if (parsedInput.path) {
              values = await fetchData(parsedInput.path);
              values = parser(values.data);
            }
            else {
              values = parser(parsedInput.data);
            }
            
          }

          // if (parsedInput.dataType == "dataframe") {
          //   if(parsedInput.path) {
          //     values = await fetchData(`${parsedInput.path}`);
          //     values['data'] = parseDataframe(values['data']);
          //   }
          //   else {
          //     values['data'] = parseDataframe(values['data']);
          //   }
          // }
          // else if (parsedInput.dataType == "geodataframe") {
          //   if(parsedInput.path) {
          //     values = await fetchData(`${parsedInput.path}`);
          //     values['data'] = parseGeoDataframe(values['data']);
          //   }
          //   else {
          //     values['data'] = parseGeoDataframe(values['data']);
          //   }
          // }


          let changeset = vega
            .changeset()
            .remove(() => true)
            .insert(values);

          setCurrentView((prevView: any) => {
            // prevView.change('data', changeset).runAsync().then(() => {
            //     prevView.setState(currentViewState);
            // });

            prevView.change("data", changeset).runAsync();

            return prevView;
          });
        }
      }
    }
    updateView();

  }, [data.input]);

  useEffect(() => {
    var ro = new ResizeObserver((entries) => {
      for (let entry of entries) {
        if (currentViewRef.current != undefined) {
          window.dispatchEvent(new Event("resize"));
        }
      }
    });

    ro.observe(document.getElementById("vega" + data.nodeId) as HTMLElement);
  }, []);

  const compileGrammar = async (spec: string) => {
    if (data.input != "") {
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
      let inputType = data.input.dataType;// JSON.parse(data.input)["dataType"];

      if (inputType == "dataframe" || inputType == "geodataframe") {
        let specObj = JSON.parse(spec);

        let values: any = [];

        if (data.input != "") {
          let parsedInput = data.input;//JSON.parse(data.input);

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
            "geodataframe": parseGeoDataframe
          };

          const parser = parserMap[parsedInput.dataType];

          if (parser) {
            if (parsedInput.path) {
              values = await fetchData(parsedInput.path);
              values = parser(values.data);
            }
            else {
              values = parser(parsedInput.data);
            }
          }

          specObj["data"] = { values: values, name: "data" };
        }

        specObj["height"] = "container";
        specObj["width"] = "container";
        // specObj["autosize"] = {type: "fit", contains: "padding", resize: true};

        let vegaspec = lite.compile(specObj).spec;
        console.log(specObj);

        var view = new vega.View(vega.parse(vegaspec))
          .logLevel(vega.Warn) // set view logging level
          .renderer("svg")
          .initialize("#vega" + data.nodeId)
          .hover();

        view.runAsync().then(() => {
          const container = document.getElementById("vega" + data.nodeId);
          const parentContainer = container?.parentElement;
          if (parentContainer) {
            // Check if the container has any elements with the class 'vega-bind'
            const hasBindings = container.querySelector('.vega-bind') !== null;
            
            // Dynamically adjust the padding of the parent container based on the presence of bindings
            parentContainer.style.paddingBottom = hasBindings ? '25px' : '';
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
                source: BoxType.VIS_VEGA,
              },
            });

            view.addSignalListener(parsedAttr[0], (name: any, value: any) => {
              // detecting the type of interaction (point/hover or interval (brush))
              let signalAttributes = Object.keys(value);

              let interactedElementsPoint: number[] = []; // id of the elements interacted with point/hover

              if (signalAttributes.length == 0) {
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
                    source: BoxType.VIS_VEGA,
                  };
                }

                newObj[parsedAttr[0]] = {
                  type: type,
                  data: data,
                  priority: 1,
                  source: BoxType.VIS_VEGA,
                };

                setInteractions(newObj);
              } else if (signalAttributes.includes("_vgsid_")) {
                // point/hover
                for (const elem of value._vgsid_) {
                  interactedElementsPoint.push((elem - 1) % values.length); // index of elements increase every time dataset is changed
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
                  source: BoxType.VIS_VEGA,
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
                  source: BoxType.VIS_VEGA,
                };

                setInteractions(newObj);
              }
            });
          }
        }

        // replicating input to the output
        setOutput({ code: "success", content: data.input });
        data.outputCallback(data.nodeId, data.input);
      } else {
        alert(
          inputType + " is not a valid input type for the 2D Plot (Vega-Lite)"
        );
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

      if (data.input != "") typesInput = data.input.dataType;// getType([data.input]);

      let typesOuput: string[] = [...typesInput];

      boxExecProv(
        startTime,
        endTime,
        workflowNameRef.current,
        BoxType.VIS_VEGA + "-" + data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOuput),
        code
      );
    }
  };

  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        isConnectable={isConnectable}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable}
      />
      {/* Data flows in both ways */}
      <Handle
        type="source"
        position={Position.Top}
        id="in/out"
        isConnectable={isConnectable}
      />
      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        output={output}
        templateData={templateData}
        code={code}
        user={user}
        handleType={"in/out"}
        sendCodeToWidgets={sendCode}
        setOutputCallback={setOutput}
        promptModal={promptModal}
        updateTemplate={updateTemplate}
        setTemplateConfig={setTemplateConfig}
        promptDescription={promptDescription}
      >
        <InputIcon type="1" />
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.VIS_VEGA}
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
          boxType={BoxType.VIS_VEGA}
          code={code}
        />
        <BoxEditor
          outputId={"vega" + data.nodeId}
          setSendCodeCallback={setSendCodeCallback}
          code={false}
          grammar={true}
          widgets={true}
          setOutputCallback={setOutput}
          data={data}
          output={output}
          boxType={BoxType.VIS_VEGA}
          applyGrammar={compileGrammar}
          defaultValue={templateData.code ? templateData.code : data.defaultCode}
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

        <OutputIcon type="1" />
      </BoxContainer>
    </>
  );
}

export default VegaBox;
