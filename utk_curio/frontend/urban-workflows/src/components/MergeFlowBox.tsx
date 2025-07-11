import React, { useState, useEffect } from "react";
import { Handle, Position, useStoreApi, Edge } from "reactflow";

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
  const store = useStoreApi();
  const edges = (store.getState().edges ?? []) as Edge[];

  const [inputValues, setInputValues] = useState<any[]>(Array(2).fill(undefined));
  const [output, setOutput] = useState<{ code: string; content: any }>({
    code: "",
    content: { data: [], dataType: "outputs" },
  });
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [showDescriptionModal, setDescriptionModal] = useState(false);
  const { editUserTemplate } = useTemplateContext();

  // Compute how many handles to show based on connected inputs
  const usedHandles = edges
    .filter((e) => e.target === data.nodeId && e.targetHandle?.startsWith("in"))
    .map((e) => e.targetHandle as string);
  const uniqueUsedCount = new Set(usedHandles).size;
  const handleCount = Math.min(5, Math.max(2, uniqueUsedCount + 1));

  // Sync template data
  useEffect(() => {
    if (data.templateId) {
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
  }, [
    data.templateId,
    data.templateName,
    data.description,
    data.accessLevel,
    data.defaultCode,
    data.customTemplate,
  ]);

  const promptDescription = () => setDescriptionModal(true);
  const closeDescription = () => setDescriptionModal(false);
  const updateTemplate = (template: Template) => editUserTemplate(template);

  // Emit output on input change
  useEffect(() => {
    const dataArr = inputValues.filter((v) => v !== undefined);
    const newOut = { data: dataArr, dataType: "outputs" };
    setOutput({ code: "success", content: newOut });
    data.outputCallback(data.nodeId, newOut);
  }, [inputValues, data, data.nodeId]);

  // Sync incoming inputs to state
  useEffect(() => {
    if (Array.isArray(data.input)) {
      setInputValues((prev) => {
        const arr = [...prev];
        data.input!.forEach((val, idx) => {
          if (idx < arr.length) arr[idx] = val;
        });
        return arr;
      });
    }
  }, [data.input]);

  return (
    <>
      {/* Input handles */}
      {Array.from({ length: handleCount }).map((_, idx) => {
        const id = idx === 0 ? "in" : `in_${idx}`;
        return (
          <Handle
            key={id}
            type="target"
            position={Position.Left}
            id={id}
            isConnectable={isConnectable}
            isValidConnection={(connection) =>
              connection.sourceHandle === "out" &&
              connection.target === data.nodeId &&
              connection.targetHandle === id &&
              !usedHandles.includes(id) // prevent multiple edges to same handle
            }
            style={{
              top: `${((idx + 1) * 100) / (handleCount + 1)}%`,
              zIndex: 10,
              pointerEvents: "auto",
            }}
          />
        );
      })}

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable}
        style={{ top: "60%" }}
      />

      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        boxHeight={40 + handleCount * 30}
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
