import React, { useState, useEffect } from "react";
import { Handle, Position } from "reactflow";
import { useReactFlow } from "reactflow";
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
  const defaultCount = data.inputCount ?? 1;
  const [inputCount, setInputCount] = useState<number>(defaultCount);
  const [inputValues, setInputValues] = useState<any[]>(
    Array(defaultCount).fill(undefined)
  );

  const [output, setOutput] = useState<{ code: string; content: any }>({
    code: "",
    content: { data: [], dataType: "outputs" },
  });
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [showDescriptionModal, setDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();

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

  const setTemplateConfig = (template: Template) => {
    setTemplateData({ ...template, inputCount });
  };

  const promptDescription = () => setDescriptionModal(true);
  const closeDescription = () => setDescriptionModal(false);

  const updateTemplate = (template: Template) => {
    setTemplateConfig(template);
    editUserTemplate({ ...template });
  };

  const iconStyle: CSS.Properties = {
    fontSize: "1.2em",
    color: "#1C191A",
    cursor: "pointer",
    marginLeft: "5px",
  };

  const handleInputCountChange = (newCount: number) => {
    setInputCount(newCount);
    setInputValues(Array(newCount).fill(undefined));
    if (data.inputCount !== undefined) {
      data.inputCount = newCount;
    }
  };

  // Handle input updates for specific ports
  const handleInputUpdate = (index: number, value: any) => {
    const newValues = [...inputValues];
    newValues[index] = value;
    setInputValues(newValues);
    
    // Filter out undefined inputs
    const validInputs = newValues.filter(val => val !== undefined);
    
    const newOutput = { 
      data: validInputs, 
      dataType: "outputs" 
    };
    
    setOutput({ code: "success", content: newOutput });
    data.outputCallback(data.nodeId, newOutput);
  };

  // Listen for input changes from parent
  useEffect(() => {
    if (data.input && Array.isArray(data.input)) {
      // Process inputs in order
      const newValues = [...inputValues];
      let changed = false;
      
      data.input.forEach((input, idx) => {
        if (idx < inputCount && input !== newValues[idx]) {
          newValues[idx] = input;
          changed = true;
        }
      });
      
      if (changed) {
        setInputValues(newValues);
        
        const validInputs = newValues.filter(val => val !== undefined);
        const newOutput = { 
          data: validInputs, 
          dataType: "outputs" 
        };
        
        setOutput({ code: "success", content: newOutput });
        data.outputCallback(data.nodeId, newOutput);
      }
    }
  }, [data.input]);

  return (
    <>
      {Array.from({ length: inputCount }).map((_, index) => {
  const id = index === 0 ? "in" : index === 1 ? "in_2" : `in_${index}`;
  return (
    <Handle
      key={id}
      type="target"
      position={Position.Left}
      id={id}
      style={{
        top: `${((index + 1) * 120) / (inputCount + 1)}%`,
        zIndex: 10,
        pointerEvents: "auto",
      }}
      isConnectable={isConnectable}
    />
  );
})}



      <Handle
        type="source"
        position={Position.Right}
        id="out"
        isConnectable={isConnectable}
        style={{ top: "60%", zIndex: 10, pointerEvents: "auto" }}
      />

      <div style={{ marginBottom: "8px", textAlign: "center" }}>
        <label style={{ fontSize: "0.85em" }}></label>
        <select
          value={inputCount}
          onChange={(e) => handleInputCountChange(parseInt(e.target.value))}
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

      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        boxHeight={60 + inputCount * 25}
        boxWidth={120}
        noContent={true}
        templateData={templateData}
        setOutputCallback={setOutput}
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

export default MergeFlowBox;