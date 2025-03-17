import React, { createContext, useContext, useState, ReactNode } from "react";

interface WorkFlowContextProps {
    workflowID: string;
    workflowName: string;
    setWorkflowName: (name: string) => void;
    setWorkflowID: (id: string) => void;
    getWorkflowNames: () => void;
}

const WorkFlowContext = createContext<WorkFlowContextProps | undefined>(undefined);

interface WorkFlowProviderProps {
    children: ReactNode;
}

export const WorkFlowProvider = ({ children }: WorkFlowProviderProps) => {
    const [workflowName, setWorkflowName] = useState<string>("");
    const [workflowID, setWorkflowID] = useState<string>("");

    const getWorkflowNames = async () => {
        const response = await fetch(process.env.BACKEND_URL + "/getWorkflowNames", {
            method: "GET"
        });
        
        if (response.ok) {
            const data = await response.json();
            return data; 
        } else {
            console.error("Error searching workflows");
            return null;
        }
    };

    return (
        <WorkFlowContext.Provider value={{ workflowID, workflowName, setWorkflowName, setWorkflowID, getWorkflowNames }}>
            {children}
        </WorkFlowContext.Provider>
    );
};

export const useWorkFlowContext = () => {
    const context = useContext(WorkFlowContext);
    if (!context) {
        throw new Error("useWorkFlowContext must be used within a WorkFlowProvider");
    }
    return context;
};

export default WorkFlowProvider;
