import React, { useState, useEffect } from "react";
import { Handle, Position, useStoreApi, Edge } from "reactflow";
import "bootstrap/dist/css/bootstrap.min.css";
import DescriptionModal from "./DescriptionModal";
import { BoxType } from "../constants";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer } from "./styles";
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

  const [inputCount, setInputCount] = useState<number>(2);
  const [inputValues, setInputValues] = useState<any[]>(Array(2).fill(undefined));
  const [output, setOutput] = useState<{ code: string; content: any }>({
    code: "",
    content: { data: [], dataType: "outputs" },
  });
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [showDescriptionModal, setDescriptionModal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { editUserTemplate } = useTemplateContext();

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

  // Check if a handle is already connected
  const isHandleConnected = (handleId: string) => {
    return edges.some((e) => e.target === data.nodeId && e.targetHandle === handleId);
  };

  // Validation for connections to inputs
  const isValidConnectionForInput = (connection: any, handleId: string) => {
    if (connection.sourceHandle !== "out") return false;

    // Prevent multiple edges on the same handle
    if (isHandleConnected(handleId)) {
      setError(`Input handle ${handleId} is already connected.`);
      return false;
    }

    // Prevent exceeding 5 inputs
    const connectedInputs = edges.filter(
      (e) => e.target === data.nodeId && e.targetHandle?.startsWith("in")
    );
    if (connectedInputs.length >= 5) {
      setError("Maximum of 5 inputs allowed.");
      return false;
    }

    // Ensure target and handle matches
    if (connection.target !== data.nodeId || connection.targetHandle !== handleId) return false;

    setError(null); // clear errors if valid
    return true;
  };

  // Adjust handles based on edges and limit max to 5
  useEffect(() => {
    const used = edges
      .filter((e) => e.target === data.nodeId && e.targetHandle?.startsWith("in"))
      .map((e) => e.targetHandle as string);

    const unique = Array.from(new Set(used));
    let desired = Math.min(5, Math.max(2, unique.length + 1));

    // Only add new handle if last handle is connected
    if (desired > 2 && !unique.includes(`in_${desired - 1}`)) {
      desired = desired - 1;
    }

    if (desired !== inputCount) {
      setInputCount(desired);
      setInputValues((prev) => {
        const arr = [...prev];
        while (arr.length < desired) arr.push(undefined);
        return arr.slice(0, desired);
      });
    }
  }, [edges, data.nodeId, inputCount]);

  const promptDescription = () => setDescriptionModal(true);
  const closeDescription = () => setDescriptionModal(false);
  const updateTemplate = (template: Template) => editUserTemplate(template);

  // Emit output when inputs change
  useEffect(() => {
    const dataArr = inputValues.filter((v) => v !== undefined);
    const newOut = { data: dataArr, dataType: "outputs" };
    setOutput({ code: "success", content: newOut });
    data.outputCallback(data.nodeId, newOut);
  }, [inputValues, data, data.nodeId]);

  // Reflect external input changes
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
      {Array.from({ length: inputCount }).map((_, idx) => {
        const id = idx === 0 ? "in" : `in_${idx}`;
        return (
          <Handle
            key={id}
            type="target"
            position={Position.Left}
            id={id}
            isConnectable={isConnectable}
            isValidConnection={(connection) => isValidConnectionForInput(connection, id)}
            style={{
              top: `${((idx + 1) * 100) / (inputCount + 1)}%`,
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
        boxHeight={40 + inputCount * 30}
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
