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
    suggestionType?: string;
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

    // Debugging: Log the output array and node ID
    console.log("MergeFlowBox Output:", { nodeId: data.nodeId, outArr });

    if (outArr.length > 0) {
      data.outputCallback(data.nodeId, { data: outArr, dataType: "outputs" });
    }
  }, [inputValues, data.nodeId, data.outputCallback]);

  // Sync external inputs
  useEffect(() => {
  if (Array.isArray(data.input)) {
    console.log("[MergeFlowBox] Incoming data.input:", data.input);
    
    setInputValues(prev => {
      const cp = Array.isArray(prev) ? [...prev] : Array(5).fill(undefined);

      data.input!.forEach((val, i) => {
        console.log(`  → assigning cp[${i}] =`, val);
        if (i < cp.length) cp[i] = val;
      });

      console.log("[MergeFlowBox] Updated inputValues copy:", cp);
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
            isConnectable={isConnectable && !connected && (data.suggestionType == undefined || data.suggestionType == "none")}
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
        isConnectable={isConnectable && (data.suggestionType == undefined || data.suggestionType == "none")}
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
