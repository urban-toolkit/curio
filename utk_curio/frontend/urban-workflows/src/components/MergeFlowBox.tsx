import React, { useState, useEffect } from "react";
import { Handle, Position } from "reactflow";

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
    inputCount?: number;
  };
  isConnectable: boolean;
}

function MergeFlowBox({ data, isConnectable }: MergeFlowBoxProps) {
  // Default to 2 inputs or saved value
  const defaultCount = data.inputCount ?? 2;
  const [inputCount, setInputCount] = useState<number>(defaultCount);
  // Track order of inputs
  const [inputOrder, setInputOrder] = useState<number[]>(
    Array.from({ length: defaultCount }, (_, i) => i)
  );

  const [output, setOutput] = useState<{ code: string; content: any }>(
    { code: "", content: { data: [], dataType: "outputs" } }
  );
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();

  // When template data loads, sync saved inputCount
  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: BoxType.MERGE_FLOW,
        name: data.templateName,
        description: data.description,
        accessLevel: data.accessLevel,
        code: data.defaultCode,
        custom: data.customTemplate,
        inputCount,
      });
    }
  }, [data.templateId]);

  // Update inputOrder when count changes
  useEffect(() => {
    setInputOrder(Array.from({ length: inputCount }, (_, i) => i));
  }, [inputCount]);

  const setTemplateConfig = (template: Template) => {
    setTemplateData({ ...template, inputCount });
  };

  const promptDescription = () => setDescriptionModal(true);
  const closeDescription   = () => setDescriptionModal(false);

  const updateTemplate = (template: Template) => {
    setTemplateConfig(template);
    editUserTemplate({ ...template});
  };

  const iconStyle: CSS.Properties = {
    fontSize: "1.2em",
    color: "#888787",
    cursor: "pointer",
    marginLeft: "5px",
  };

  // Merge inputs in the order defined by inputOrder
  useEffect(() => {
    let newOutput: any = { data: [], dataType: "outputs" };
    const arr = Array.isArray(data.input) ? data.input : [];

    for (const idx of inputOrder) {
      const val = arr[idx];
      if (val !== undefined && val !== "") {
        newOutput.data.push(val);
      }
    }

    setOutput({ code: "success", content: newOutput });
    data.outputCallback(data.nodeId, newOutput);
  }, [data.input, inputOrder]);

  return (
    <>
      {/* Dynamic input handles */}
      {inputOrder.map((i) => (
        <Handle
          key={`in_${i}`}
          type="target"
          position={Position.Left}
          id={`in_${i}`}
          style={{ top: `${((i + 1) * 100) / (inputCount + 1)}%` }}
          isConnectable={isConnectable}
        />
      ))}

      {/* Single output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable}
      />

      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        boxHeight={50 + inputCount * 20}
        boxWidth={120}
        noContent={true}
        templateData={templateData}
        setOutputCallback={setOutput}
        updateTemplate={updateTemplate}
        promptDescription={promptDescription}
      >
        {/* Input count selector */}
        <div style={{ marginBottom: "8px", textAlign: "center" }}>
          <label style={{ fontSize: "0.85em" }}>Inputs:</label>
          <select
            value={inputCount}
            onChange={(e) => setInputCount(parseInt(e.target.value))}
            style={{ fontSize: "0.85em", marginLeft: "4px" }}
          >
            {[1, 2, 3, 4, 5].map((num) => (
              <option key={num} value={num}>{num}</option>
            ))}
          </select>
          <FontAwesomeIcon
            icon={faCircleInfo}
            title="Select how many inputs this box accepts"
            style={iconStyle}
          />
        </div>

        {/* Description modal trigger */}
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

export default MergeFlowBox;
