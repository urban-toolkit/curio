import React, { useEffect, useState } from "react";
import { useWorkFlowContext } from "../providers/WorkflowProvider";

type WorkflowListProps = {
  onSelectWorkflow: (workflowID: string, workflowName: string) => void; 
};

const WorkflowList: React.FC<WorkflowListProps> = ({ onSelectWorkflow }) => {
  const [selectedWorkflowID, setSelectedWorkflowID] = useState<string>("");  
  const [selectedWorkflowName, setSelectedWorkflowName] = useState<string>("");  
  const [newWorkflowName, setNewWorkflowName] = useState<string>("");

  const { getWorkflowNames } = useWorkFlowContext();
  const [workflowNames, setWorkflowNames] = useState<{ id: string, name: string }[]>([]); 

  useEffect(() => {
    const fetchData = async () => {
      const response:any = await getWorkflowNames();

      if (response) {

        const workflows = await response.workflows.map((workflow: { id: string, name: string }) => ({
          id: workflow.id,
          name: workflow.name 
        }));

        setWorkflowNames(workflows.filter((workflow: { name: string; }) => workflow.name.trim() !== ""));
      }
      
    };

    fetchData(); 
  }, []);

  const handleSelectChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const selectedID = event.target.value;
    const selectedName = event.target.selectedOptions[0]?.text;

    setSelectedWorkflowID(selectedID);
    setSelectedWorkflowName(selectedName);
    onSelectWorkflow(selectedID, selectedName); 
  };

  const handleAddWorkflow = () => {
    if (!newWorkflowName.trim()) return;
    setWorkflowNames([...workflowNames, { id: "-1", name: newWorkflowName }]); //Temp ID 
    setNewWorkflowName(""); // Cleaning 
  };

  return (
    <div
      style={{
        position: "relative",
        zIndex: 10,
        padding: "10px",
        background: "white",
        borderRadius: "8px",
        boxShadow: "0px 4px 8px rgba(0,0,0,0.1)",
      }}
    >
      <label htmlFor="workflowSelect">Select a workflow:</label>
      <select
        id="workflowSelect"
        value={selectedWorkflowID}
        onChange={handleSelectChange}
        style={{ width: "100%", padding: "8px", marginTop: "5px", borderRadius: "4px" }}
      >
        <option value=""></option>
        {workflowNames.map((workflow, index) => (
          <option key={index} value={workflow.id}>
            {workflow.name}
          </option>
        ))}
      </select>

      <div style={{ marginTop: "10px" }}>
        <input
          type="text"
          placeholder="New workflow name"
          value={newWorkflowName}
          onChange={(e) => setNewWorkflowName(e.target.value)}
          style={{ width: "calc(100% - 50px)", padding: "8px", borderRadius: "4px", marginRight: "10px" }}
        />
        <button
          onClick={handleAddWorkflow}
          style={{
            padding: "8px 10px",
            borderRadius: "4px",
            background: "#4CAF50",
            color: "white",
            border: "none",
            cursor: "pointer",
          }}
        >
          + Add
        </button>
      </div>
    </div>
  );
};

export default WorkflowList;
