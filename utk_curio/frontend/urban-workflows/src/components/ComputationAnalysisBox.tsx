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
