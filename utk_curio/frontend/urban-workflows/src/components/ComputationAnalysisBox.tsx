import React, { useState, useEffect } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";
import { BoxType } from "../constants";
import { BoxContainer, buttonStyle, iconStyle } from "./styles";
import CSS from "csstype";
import "./Box.css"

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import TemplateModal from "./TemplateModal";
import DescriptionModal from "./DescriptionModal";
import { useUserContext } from "../providers/UserProvider";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";
import Tabs from "react-bootstrap/Tabs";
import Tab from "react-bootstrap/Tab";
// import { COMMON_ERRORS } from "./COMMON_ERRORS";

function ComputationAnalysisBox({ data, isConnectable }) {
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
  const { user } = useUserContext();

  const { editUserTemplate } = useTemplateContext();

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
        type: BoxType.COMPUTATION_ANALYSIS,
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

  // Tab state for three tabs
  const [tabData, setTabData] = useState<any[]>([]);

  // Build tab data from output or error
  useEffect(() => {
    // If error, show error tab with friendly and traceback
    if (output?.code === "error") {
      const match = output.content.match(/(\w+Error):/);
      // let errorType = match ? match[1] : null;
      // let friendlyMessage = errorType ? (COMMON_ERRORS[errorType] || "❗ An unknown error occurred.") : null;
      setTabData([
        {
          title: "Output",
          content: "",
          type: "output"
        },
        {
          title: "Error",
          content: {
            friendly: output.content,
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
          content: output.content,
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
  }, [output]);

  // ContentComponent for three tabs (Output, Error, Warning)
  const ContentComponent = ({ tabData }: { tabData: any[]; }) => {
    
    return (
      <Tabs
        id="computation-tabs"
        className="mb-2"
      >
        <Tab eventKey="0" title="Output">
          <div style={{ padding: "15px" }}>
            <h6>Output</h6>
            <div style={{ fontSize: "12px", color: "#666" }}>{tabData[0]?.content || "No output available."}</div>
          </div>
        </Tab>
        <Tab eventKey="1" title="Error">
          <div style={{
            padding: "15px",
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: 300,
            maxHeight: 600,
          }}>
            <div style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
              {(tabData[1]?.content?.friendly || tabData[1]?.content?.traceback) ? (
                <div className="error-traceback-scroll" style={{ flex: 1, display: "flex", flexDirection: "column", padding: 0 }}>
                  {/* Error message */}
                  {/* {tabData[1]?.content?.friendly && (
                    <div
                      style={{
                        background: "#fff8e1",
                        color: "#6d4c41",
                        padding: "16px",
                        fontWeight: 600,
                        fontSize: "1.1em",
                        borderTopLeftRadius: "8px",
                        borderTopRightRadius: "8px",
                        borderBottom: tabData[1]?.content?.traceback ? "1px solid #eee" : undefined
                      }}
                    >
                      {tabData[1].content.friendly}
                    </div>
                  )} */}
                  {/* Traceback */}
                  {tabData[1]?.content?.traceback && (
                    <div
                      style={{
                        background: "#ffebee",
                        color: "#b71c1c",
                        padding: "12px",
                        fontWeight: 400,
                        fontFamily: "monospace",
                        borderBottomLeftRadius: "8px",
                        borderBottomRightRadius: "8px",
                        display: "flex",
                        flexDirection: "column"
                      }}
                    >
                      <div style={{ fontWeight: 600 }}>Traceback:</div>
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
              <div style={{ background: "#fffbe6", color: "#8a6d3b", padding: "10px", borderRadius: "5px", fontWeight: "bold" }}>
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
  };

  // Memoize content component for BoxEditor
  const memoizedContentComponent = React.useMemo(
    () => <ContentComponent tabData={tabData} />,
    [tabData]
  );

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
        promptDescription={promptDescription}
        setTemplateConfig={setTemplateConfig}
      >
        <InputIcon type="N" />
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.COMPUTATION_ANALYSIS}
          name={templateData.name}
          description={templateData.description}
          accessLevel={templateData.accessLevel}
          show={showDescriptionModal}
          handleClose={closeDescription}
          custom={templateData.custom}
        />
        <BoxEditor
          setSendCodeCallback={setSendCodeCallback}
          code={true}
          grammar={false}
          widgets={true}
          setOutputCallback={setOutput}
          data={data}
          output={output}
          boxType={BoxType.COMPUTATION_ANALYSIS}
          defaultValue={templateData.code ? templateData.code : data.defaultCode}
          readOnly={
            (templateData.custom != undefined &&
              templateData.custom == false)
          }
          floatCode={setCode}
          contentComponent={memoizedContentComponent}
        />
        <TemplateModal
          newTemplateFlag={newTemplateFlag}
          templateId={templateData.id}
          callBack={setTemplateConfig}
          show={showTemplateModal}
          handleClose={closeModal}
          boxType={BoxType.COMPUTATION_ANALYSIS}
          code={code}
        />

        <OutputIcon type="N" />
      </BoxContainer>
    </>
  );
}

export default ComputationAnalysisBox;
