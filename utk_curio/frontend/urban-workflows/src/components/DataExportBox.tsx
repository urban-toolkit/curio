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

function DataExportBox({ data, isConnectable }: DataExportBoxProps) {
  const [output, setOutput] = useState<{ code: string; content: string, outputType: string }>({
    code: "",
    content: "",
    outputType: ""
  }); // stores the output produced by the last execution of this box
  const [code, setCode] = useState<string>("");
  const [sendCode, setSendCode] = useState();
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

  const setSendCodeCallback = (_sendCode: any) => {
    setSendCode(() => _sendCode);
  };

  const iconStyle: CSS.Properties = {
    fontSize: "1.5em",
    color: "#888787",
  };

  useEffect(() => {
    const processDataAsync = async () => {
      try {
        let processedData = data.input;
        // If error, show error tab with friendly and traceback
        if (output?.code === "error") {
          setTabData([
            {
              title: "Output",
              content: "",
              type: "output"
            },
            {
              title: "Error",
              content: {
                friendly: "❌ Error: Failed to process data.",
                traceback: output.content
              },
              type: "error"
            },
            {
              title: "Warning",
              content: { friendly: null, traceback: null },
              type: "warning"
            }
          ]);
        } else {
          setTabData([
            {
              title: "Output",
              content: processedData.output || "No output available",
              type: "output"
            },
            {
              title: "Error",
              content: { friendly: null, traceback: null },
              type: "error"
            },
            {
              title: "Warning",
              content: { friendly: null, traceback: null },
              type: "warning"
            }
          ]);
        }
        setOutput({
          code: "success",
          content: JSON.stringify([processedData.output, processedData.errors, processedData.warnings], null, 2),
          outputType: "tabs"
        });
        data.outputCallback(data.nodeId, tabData);
      } catch (error) {
        console.error("Error processing data:", error);
        setTabData([
          {
            title: "Output",
            content: "",
            type: "output"
          },
          {
            title: "Error",
            content: {
              friendly: "❌ Error: Failed to process data.",
              traceback: error?.toString() || "Unknown error"
            },
            type: "error"
          },
          {
            title: "Warning",
            content: { friendly: null, traceback: null },
            type: "warning"
          }
        ]);
        setOutput({ code: "error", content: error?.toString() || "Failed to process data.", outputType: "tabs" });
      }
    };
    processDataAsync();
  }, [data.input, data.newPropagation, output?.code]);
  const ContentComponent = ({ tabData, activeTab, setActiveTab }: { tabData: any[]; activeTab: string; setActiveTab: (tab: string) => void; }) => (
    <Tabs
      id="three-tabs"
      activeKey={activeTab}
      onSelect={(k) => setActiveTab(k || "0")}
      className="mb-3"
    >
      <Tab eventKey="0" title="Output">
        <div style={{ padding: "15px" }}>
          <h4>Output</h4>
          <div style={{ fontSize: "1.2em", color: "#666" }}>{tabData[0]?.content || "No output available."}</div>
        </div>
      </Tab>
      <Tab eventKey="1" title="Error">
        <div style={{ padding: "15px", display: "flex", flexDirection: "column", height: "100%", minHeight: 100, maxHeight: 400 }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
            {(tabData[1]?.content?.friendly || tabData[1]?.content?.traceback) ? (
              <div style={{ flex: 1, display: "flex", flexDirection: "column", padding: 0 }}>
                {/* Error message */}
                {tabData[1]?.content?.friendly && (
                  <div style={{ background: "#fff8e1", color: "#6d4c41", padding: "16px", fontWeight: 600, fontSize: "1.1em", borderTopLeftRadius: "8px", borderTopRightRadius: "8px", borderBottom: tabData[1]?.content?.traceback ? "1px solid #eee" : undefined }}>
                    {tabData[1].content.friendly}
                  </div>
                )}
                {/* Traceback */}
                {tabData[1]?.content?.traceback && (
                  <div style={{ background: "#ffebee", color: "#b71c1c", padding: "16px", fontWeight: 400, fontFamily: "monospace", borderBottomLeftRadius: "8px", borderBottomRightRadius: "8px", display: "flex", flexDirection: "column" }}>
                    <div style={{ fontWeight: 600, marginBottom: 8 }}>Traceback:</div>
                    <pre style={{ margin: 0, fontSize: "1em", background: "none", color: "inherit" }}>{tabData[1].content.traceback}</pre>
                  </div>
                )}
              </div>
            ) : (
              <div>No errors available</div>
            )}
          </div>
        </div>
      </Tab>
      <Tab eventKey="2" title="Warning">
        <div style={{ padding: "15px" }}>
          {tabData[2]?.content?.friendly && (
            <div style={{ background: "#fffbe6", color: "#8a6d3b", padding: "10px", borderRadius: "5px", marginBottom: "10px", fontWeight: "bold" }}>
              {tabData[2].content.friendly}
            </div>
          )}
          {tabData[2]?.content?.traceback && (
            <div style={{ background: "#e2e3e5", color: "#383d41", padding: "10px", borderRadius: "5px" }}>
              <span role="img" aria-label="Traceback">📄 Traceback:</span><br />
              <pre style={{ margin: 0, fontSize: "1em", fontFamily: "monospace" }}>{tabData[2].content.traceback}</pre>
            </div>
          )}
          {!tabData[2]?.content?.friendly && !tabData[2]?.content?.traceback && (
            <div>No warnings available</div>
          )}
        </div>
      </Tab>
    </Tabs>
  );

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
    setSendCodeCallback={setSendCodeCallback}
    code={true}
    grammar={false}
    widgets={true}
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
    contentComponent={
        <ContentComponent
            tabData={tabData}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
        />
    }
      />
      </BoxContainer>
    </>
  );
}

export default DataExportBox;
