import React, { useState, useEffect } from "react";
import { Handle, Position, useStoreApi, Edge } from "reactflow";
import "bootstrap/dist/css/bootstrap.min.css";
import DescriptionModal from "./DescriptionModal";
import { BoxType } from "../constants";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { BoxContainer } from "./styles";

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
  const [edges, setEdges] = useState<Edge[]>([]);
  const [inputValues, setInputValues] = useState<any[]>(Array(5).fill(undefined));
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [showDescriptionModal, setDescriptionModal] = useState(false);
  const { editUserTemplate } = useTemplateContext();

  // Subscribe to global edges
  useEffect(() => {
    const unsubscribe = store.subscribe(({ edges: ef }) => {
      setEdges(ef ?? []);
    });
    return () => unsubscribe();
  }, [store]);

  // Initialize template data
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

  // Emit output when inputs update
  useEffect(() => {
    const outArr = inputValues.filter(v => v !== undefined);

    // Debugging: Log the output array, node ID, and input values
    console.log("MergeFlowBox Debug:", {
      nodeId: data.nodeId,
      inputValues,
      filteredOutput: outArr,
    });

    // Emit output even if the array is empty
    data.outputCallback(data.nodeId, {
      data: outArr.length > 0 ? outArr : [],
      dataType: "outputs",
    });
  }, [inputValues, data.nodeId, data.outputCallback]);

  // Sync external inputs
  useEffect(() => {
    if (Array.isArray(data.input)) {
      setInputValues(prev => {
        const cp = Array.isArray(prev) ? [...prev] : Array(5).fill(undefined);
        data.input!.forEach((val, i) => { if (i < cp.length) cp[i] = val; });
        return cp;
      });
    }
  }, [data.input]);

  const promptDescription = () => setDescriptionModal(true);
  const closeDescription = () => setDescriptionModal(false);
  const updateTemplate = (t: Template) => editUserTemplate(t);

  return (
    <>
      {/* input handles */}
      {Array.from({ length: 5 }).map((_, idx) => {
        const handleId = `in_${idx}`;
        const connected = edges.some(e => e.target === data.nodeId && e.targetHandle === handleId);

        return (
          <Handle
            key={handleId}
            id={handleId}
            type="target"
            position={Position.Left}
            isConnectable={isConnectable && !connected}
            style={{
              top: `${((idx + 1) * 100) / 6}%`,
              backgroundColor: connected ? "green" : "red",
              width: "17px",
              height: "17px",
              borderRadius: "50%",
              zIndex: 10,
              pointerEvents: "auto",
            }}
          />
        );
      })}

      {/* output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable}
        style={{ top: "50%" }}
      />

      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        boxHeight={60 + 5 * 50}
        boxWidth={100}
        noContent
        templateData={templateData}
        setOutputCallback={(val: any, idx = 0) =>
          setInputValues(prev => {
            const cp = Array.isArray(prev) ? [...prev] : Array(5).fill(undefined);
            cp[idx] = val;
            return cp;
          })
        }
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

async function processData(fileName: string) {
  try {
    if (!fileName) {
      throw new Error("Missing fileName for processing data.");
    }

    const data = await fetchData(fileName);
    console.log("[DataPoolBox] Successfully fetched data:", data);
    // ...existing code...
  } catch (error) {
    console.error("[DataPoolBox] Error processing data asynchronously:", error);
    // Optionally, display a user-friendly error message in the UI
  }
}