import React, { useState, useEffect } from "react";
import { Handle, Position, useReactFlow, useStoreApi } from "reactflow";
import "bootstrap/dist/css/bootstrap.min.css";
import DescriptionModal from "./DescriptionModal";
import { BoxType } from "../constants";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer } from "./styles";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleInfo } from "@fortawesome/free-solid-svg-icons";

interface MergeFlowBoxProps {
  data: {
    nodeId: string;
    input?: any[];
    outputCallback: (id: string, out: any) => void;
    templateId?: string;
    templateName?: string;
    description?: string;
    accessLevel?: string;
    defaultCode?: string;
    customTemplate?: any;
  };
  isConnectable: boolean;
}

export default function MergeFlowBox({ data, isConnectable }: MergeFlowBoxProps) {
  const edges = useStoreApi().getState().edges;
  const [inputCount, setInputCount] = useState<number>(1);
  const [inputValues, setInputValues] = useState<any[]>([undefined]);
  const [output, setOutput] = useState<{ code: string; content: any }>({
    code: "",
    content: { data: [], dataType: "outputs" },
  });
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [showDescriptionModal, setDescriptionModal] = useState(false);
  const { editUserTemplate } = useTemplateContext();

  // Sync templateData when templateId or inputCount changes
  useEffect(() => {
    if (data.templateId !== undefined) {
      setTemplateData({
        id: data.templateId,
        type: BoxType.MERGE_FLOW,
        name: data.templateName,
        description: data.description,
        accessLevel: data.accessLevel,
        code: data.defaultCode,
        custom: data.customTemplate,
      });
    }
  }, [data.templateId, data.templateName, data.description, data.accessLevel, data.defaultCode, data.customTemplate]);

  // Watch edges reactively
  useEffect(() => {
    const inputConnections = (edges as any[]).filter(
      (edge: any) => edge.target === data.nodeId && edge.targetHandle?.startsWith("in")
    );
    const usedHandles = new Set<string>(inputConnections.map((e: any) => e.targetHandle));

    if (usedHandles.size < 5 && usedHandles.size >= inputCount) {
      setInputCount(usedHandles.size + 1);
      setInputValues((prev) => [...prev, undefined]);
    }
  }, [edges, data.nodeId, inputCount]);

  const promptDescription = () => setDescriptionModal(true);
  const closeDescription = () => setDescriptionModal(false);

  const updateTemplate = (template: Template) => {
    editUserTemplate(template);
  };

  const iconStyle: CSS.Properties = {
    fontSize: "1.2em",
    color: "#1C191A",
    cursor: "pointer",
    marginLeft: "5px",
  };

  // Notify parent when inputValues change
  useEffect(() => {
    const newOutput = { data: inputValues.filter((v) => v !== undefined), dataType: "outputs" };
    setOutput({ code: "success", content: newOutput });
    data.outputCallback(data.nodeId, newOutput);
  }, [inputValues, data, data.nodeId]);

  // Update inputValues from data.input
  useEffect(() => {
    if (Array.isArray(data.input)) {
      setInputValues((prev) => {
        const updated = [...prev];
        data.input!.forEach((val, idx) => {
          if (idx < updated.length) updated[idx] = val;
        });
        return updated;
      });
    }
  }, [data.input]);

  return (
    <>
      {/* Dynamic input handles */}
      {Array.from({ length: inputCount }).map((_, index) => {
        const handleId = index === 0 ? "in" : `in_${index}`;
        const used = (edges as any[]).some(
          (e: any) => e.target === data.nodeId && e.targetHandle === handleId
        );
        return (
          <Handle
            key={handleId}
            type="target"
            position={Position.Left}
            id={handleId}
            isConnectable={isConnectable}
            isValidConnection={() => !used}
            style={{ top: `${((index + 1) * 120) / (inputCount + 1)}%`, zIndex: 10 }}
          />
        );
      })}

      {/* Single output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable}
        style={{ top: "60%", zIndex: 10 }}
      />

      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        boxHeight={60 + inputCount * 25}
        boxWidth={120}
        noContent
        templateData={templateData}
        setOutputCallback={setInputValues}
        updateTemplate={updateTemplate}
        promptDescription={promptDescription}
      >
        <DescriptionModal
          nodeId={data.nodeId}
          boxType={BoxType.MERGE_FLOW}
          name={templateData.name}
          description={templateData.description}
          accessLevel={templateData.accessLevel}
          show={showDescriptionModal}
          handleClose={closeDescription}
          custom={templateData.custom}
        />
      </BoxContainer>
    </>
  );
}
