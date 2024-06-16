import React, { useState } from "react";
import { Handle, Position } from "reactflow";
import BoxEditor from "./editing/BoxEditor";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { BoxType } from "../constants";
import { BoxContainer } from "./styles";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import DescriptionModal from "./DescriptionModal";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo } from "@fortawesome/free-solid-svg-icons";
import CSS from "csstype";
import { useUserContext } from "../providers/UserProvider";
import { OutputIcon } from "./edges/OutputIcon";
import { InputIcon } from "./edges/InputIcon";

function FlowSwitchBox({ data, isConnectable }) {
  const [output, setOutput] = useState<{ code: string; content: string }>({
    code: "",
    content: "",
  }); // stores the output produced by the last execution of this box
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [sendCode, setSendCode] = useState();
  const [code, setCode] = useState<string>("");
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { user } = useUserContext();

  const promptDescription = () => {
    setDescriptionModal(true);
  };

  const closeDescription = () => {
    setDescriptionModal(false);
  };

  const setSendCodeCallback = (_sendCode: any) => {
    setSendCode(() => _sendCode);
  };

  return (
    <>
      <Handle
        type="target"
        position={Position.Bottom}
        id="in1"
        isConnectable={isConnectable}
      />
      <Handle
        type="target"
        position={Position.Top}
        id="in2"
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
        promptDescription={promptDescription}
      >
        <InputIcon type="2" />
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.FLOW_SWITCH}
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
          boxType={BoxType.FLOW_SWITCH}
          defaultValue={templateData.code}
          readOnly={
            (templateData.custom != undefined &&
              templateData.custom == false) ||
            !(user != null && user.type == "programmer")
          }
          floatCode={setCode}
        />
        <Handle
          type="source"
          position={Position.Right}
          id="out"
          isConnectable={isConnectable}
        />

        <OutputIcon type="1" />
      </BoxContainer>
    </>
  );
}

export default FlowSwitchBox;
