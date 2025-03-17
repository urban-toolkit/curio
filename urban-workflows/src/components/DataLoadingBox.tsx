import React, { useEffect, useState } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../constants";

import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer, buttonStyle } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faCircleInfo } from "@fortawesome/free-solid-svg-icons";

import TemplateModal from "./TemplateModal";
import DescriptionModal from "./DescriptionModal";
import { useUserContext } from "../providers/UserProvider";
import { OutputIcon } from "./edges/OutputIcon";

function DataLoadingBox({ data, isConnectable }) {
  const [output, setOutput] = useState<{ code: string; content: string }>({
    code: "",
    content: "",
  }); // stores the output produced by the last execution of this box
  const [code, setCode] = useState<string>("");
  const [sendCode, setSendCode] = useState();
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [newTemplateFlag, setNewTemplateFlag] = useState(false);

  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();

  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: BoxType.DATA_LOADING,
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

  // useEffect(() => {
  //   let activity_name: any = data.nodeType + "_" + data.nodeId

  //   fetch(process.env.BACKEND_URL + "/updateActivityCode", {
  //     method: "POST",
  //     body: JSON.stringify({
  //       activity_name,
  //       code
  //     }),
  //     headers: {
  //       "Content-type": "application/json; charset=UTF-8",
  //     }
  //   })

  // }, [code]);

  useEffect(() => {
    data.code = code;
  }, [code]);

  return (
    <>
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
        sendCodeToWidgets={sendCode}
        setOutputCallback={setOutput}
        promptModal={promptModal}
        updateTemplate={updateTemplate}
        setTemplateConfig={setTemplateConfig}
        promptDescription={promptDescription}
      >
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.DATA_LOADING}
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
          boxType={BoxType.DATA_LOADING}
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
          boxType={BoxType.DATA_LOADING}
          defaultValue={templateData.code}
          readOnly={
            (templateData.custom != undefined &&
              templateData.custom == false) ||
            !(user != null && user.type == "programmer")
          }
          floatCode={setCode}
        />

        <OutputIcon type="N" />
      </BoxContainer>
    </>
  );
}

export default DataLoadingBox;
