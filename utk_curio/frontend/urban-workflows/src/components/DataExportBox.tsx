import React, { useState, useEffect } from "react";
// Define props interface
interface DataExportBoxProps {
  data: any; // Replace 'any' with a more specific type if available
  isConnectable: boolean;
}
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";

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
import OutputContent from "./editing/OutputContent";

function DataExportBox({ data, isConnectable }: DataExportBoxProps) {
  const [output, setOutput] = useState<{ code: string; content: string, outputType: string }>({
    code: "",
    content: "",
    outputType: ""
  }); // stores the output produced by the last execution of this box
  
  const [downloadFormat, setDownloadFormat] = useState<string>("csv");
  const [code, setCode] = useState<string>("");

  const sendCode = async () => {
    // Set output to "exec" to trigger loading spinner in the UI
    setOutput({ code: "exec", content: "", outputType: downloadFormat });

    // Perform the data download (export) operation
    await downloadData();

    // Set output to "success" to hide spinner and indicate completion
    setOutput({ code: "success", content: "Download complete.", outputType: downloadFormat });
  };

  const [templateData, setTemplateData] = useState<Template | any>({});

  const [newTemplateFlag, setNewTemplateFlag] = useState(false);

  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();

  const [activeTab, setActiveTab] = useState<string>("0");
  const [tabData, setTabData] = useState<any[]>([]);

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
    // Create and configure the label for the export format dropdown
    const label = document.createElement("label");
    label.setAttribute("for", "exportFormat");
    label.style.marginRight = "5px";
    label.textContent = "Export format: ";

    // Create the select (dropdown) element for choosing export format
    const select = document.createElement("select");
    select.setAttribute("name", "exportFormat");
    select.setAttribute("id", data.nodeId + "_select_format");

    // Add export format options to the dropdown
    ["csv", "json", "geojson"].forEach((optionText) => {
      const option = document.createElement("option");
      option.setAttribute("value", optionText);
      option.textContent = optionText.toUpperCase();
      select.appendChild(option);
    });

    // Set the dropdown's current value to the selected download format
    select.value = downloadFormat;

    // Update the download format state when the user selects a new option
    select.addEventListener("change", (event) => {
      if (event.target) {
        const target = event.target as HTMLOptionElement;
        setDownloadFormat(target.value);
      }
    });

    // Add the label and dropdown to the provided container
    div.appendChild(label);
    div.appendChild(select);
  };

  // Function to handle the data download based on the selected format
  const downloadData = async () => {
    // Determine the file path from the input data
    let filePath = "";
    if (data.input && typeof data.input === "object" && data.input.path) {
      filePath = data.input.path;
    }

    // If no file path is available, exit early
    if (!filePath) return;

    try {
      // Fetch the data from the backend or source
      const result: any = await fetchData(`${filePath}`);
      let fileName = "data_export";
      let fileContent = "";

      // --- CSV Export ---
      // If the user selected CSV and the data is a dataframe or geodataframe
      if (
        downloadFormat === "csv" &&
        result.data &&
        (result.dataType === "dataframe" || result.dataType === "geodataframe")
      ) {
        const csvRows: string[] = [];

        // Handle regular dataframe export to CSV
        if (result.dataType === "dataframe") {
          const columns = Object.keys(result.data);
          const rows = result.data[columns[0]]?.length || 0;
          csvRows.push(columns.join(","));
          for (let i = 0; i < rows; i++) {
            const row = columns.map(col => JSON.stringify(result.data[col][i] ?? ""));
            csvRows.push(row.join(","));
          }
        }
        // Handle geodataframe export to CSV (geometry column stringified)
        else if (result.dataType === "geodataframe" && result.data.features) {
          const features = result.data.features;
          // Flatten properties and stringify geometry for each feature
          const properties = features.map((f: any) => ({
            ...f.properties,
            geometry: JSON.stringify(f.geometry),
          }));

          const columns = Object.keys(properties[0]);
          csvRows.push(columns.join(","));
          for (const row of properties) {
            const values = columns.map(col => JSON.stringify(row[col] ?? ""));
            csvRows.push(values.join(","));
          }
        }

        fileContent = csvRows.join("\n");
        fileName += ".csv";
      }

      // --- GeoJSON Export ---
      // If the user selected GeoJSON, stringify the data as GeoJSON
      else if (downloadFormat === "geojson") {
        fileContent = JSON.stringify(result.data);
        fileName += ".geojson";
      }

      // --- JSON Export (default fallback) ---
      // For all other cases, export as plain JSON
      else {
        fileContent = JSON.stringify(result.data);
        fileName += ".json";
      }

      // Create a blob and trigger the download in the browser
      const blob = new Blob([fileContent], { type: "text/plain;charset=utf-8" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (err) {
      // Log any errors that occur during the download process
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

const memoizedOutputComponent = React.useMemo(
  () => <OutputContent output={output} />,
  [output]
);

return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        id="in"
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
      />
      <BoxContainer
        nodeId={data.nodeId}
        handleType={"in"}
        data={data}
        output={output}
        templateData={templateData}
        code={code}
        user={user}
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
        // setSendCodeCallback={setSendCodeCallback}
        setSendCodeCallback={() => {}}
        code={false}
        grammar={false}
        widgets={false}
        setOutputCallback={setOutput}
        data={data}
        output={output}
        boxType={BoxType.DATA_EXPORT}
        defaultValue={templateData.code ? templateData.code : data.defaultCode}
        readOnly={
            (templateData.custom != undefined &&
                templateData.custom == false)
        }
        floatCode={setCode}
        contentComponent={memoizedOutputComponent}
      />
      </BoxContainer>
    </>
  );
}

export default DataExportBox;
