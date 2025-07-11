import React, { useState, useEffect } from "react";
import { useRef } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer, buttonStyle } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faCircleInfo } from "@fortawesome/free-solid-svg-icons";
import "./Box.css"

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../constants";
import DescriptionModal from "./DescriptionModal";
import TemplateModal from "./TemplateModal";
import { useUserContext } from "../providers/UserProvider";
import { InputIcon } from "./edges/InputIcon";
import { fetchData } from "../services/api";

function DataExportBox({ data, isConnectable }) {
  const [output, setOutput] = useState<{ code: string; content: string, outputType: string }>({
    code: "",
    content: "",
    outputType: ""
  }); // stores the output produced by the last execution of this box
  
  const [downloadFormat, setDownloadFormat] = useState<string>("csv");
  const [code, setCode] = useState<string>("");
  const sendCode = async () => {
    setOutput({ code: "exec", content: "", outputType: downloadFormat }); // trigger spinner

    await downloadData();

    setOutput({ code: "success", content: "Download complete.", outputType: downloadFormat }); // hide spinner
  };

  const [templateData, setTemplateData] = useState<Template | any>({});

  const [newTemplateFlag, setNewTemplateFlag] = useState(false);

  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();

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
        type: BoxType.DATA_EXPORT,
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

  const customWidgetsCallback = (div: HTMLElement) => {
    const label = document.createElement("label");
    label.setAttribute("for", "exportFormat");
    label.style.marginRight = "5px";
    label.textContent = "Export format: ";

    const select = document.createElement("select");
    select.setAttribute("name", "exportFormat");
    select.setAttribute("id", data.nodeId + "_select_format");

    ["csv", "json", "geojson"].forEach((optionText) => {
      const option = document.createElement("option");
      option.setAttribute("value", optionText);
      option.textContent = optionText.toUpperCase();
      select.appendChild(option);
    });

    select.value = downloadFormat;
    select.addEventListener("change", (event) => {
      if (event.target) {
        const target = event.target as HTMLOptionElement;
        setDownloadFormat(target.value);
      }
    });

    div.appendChild(label);
    div.appendChild(select);
  };

  const downloadData = async () => {
  let filePath = "";
  if (data.input && typeof data.input === "object" && data.input.path) {
    filePath = data.input.path;
  }

  if (!filePath) return;

  try {
    const result: any = await fetchData(`${filePath}`);
    let fileName = "data_export";
    let fileContent = "";

    if (downloadFormat === "csv" && result.data) {
      const columns = Object.keys(result.data);
      const rows = result.data[columns[0]]?.length || 0;
      const csvRows = [] as string[];
      csvRows.push(columns.join(","));
      for (let i = 0; i < rows; i++) {
        const row = columns.map((col) => result.data[col][i]);
        csvRows.push(row.join(","));
      }
      fileContent = csvRows.join("\n");
      fileName += ".csv";
    } else if (downloadFormat === "geojson") {
      fileContent = JSON.stringify(result.data);
      fileName += ".geojson";
    } else {
      fileContent = JSON.stringify(result.data);
      fileName += ".json";
    }

    const blob = new Blob([fileContent], { type: "text/plain;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  } catch (err) {
    console.error("Failed to download data", err);
  }
};

useEffect(() => {
  setOutput({ code: "success", content: "", outputType: downloadFormat });
}, [data.input, downloadFormat]);



  const iconStyle: CSS.Properties = {
    fontSize: "1.5em",
    color: "#888787",
  };

  return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        isConnectable={isConnectable}
      />
      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        output={output}
        templateData={templateData}
        code={code}
        user={user}
        handleType={"in"}
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
          boxType={BoxType.DATA_EXPORT}
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
          boxType={BoxType.DATA_EXPORT}
          code={code}
        />

        <BoxEditor
          setSendCodeCallback={(_: any) => {}}
          code={false}
          grammar={false}
          widgets={true}
          provenance={false}
          setOutputCallback={setOutput}
          customWidgetsCallback={customWidgetsCallback}
          data={data}
          output={output}
          boxType={BoxType.DATA_EXPORT}
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
      </BoxContainer>
    </>
  );
}

export default DataExportBox;
