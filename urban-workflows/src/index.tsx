import React from "react";
import ReactDOM from "react-dom/client";

import FlowProvider from "./providers/FlowProvider";
import TemplateProvider from "./providers/TemplateProvider";
import UserProvider from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { MainCanvas } from "./components/MainCanvas";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import WorkflowProvider from "./providers/WorkflowProvider";

const App: React.FC = () => {
  return (
    <ReactFlowProvider>
      <WorkflowProvider>
        <ProvenanceProvider>
          <UserProvider>
            <DialogProvider>
              <FlowProvider>
                <TemplateProvider>
                  <MainCanvas />
                </TemplateProvider>
              </FlowProvider>
            </DialogProvider>
          </UserProvider>
        </ProvenanceProvider>
      </WorkflowProvider>
    </ReactFlowProvider>
  );
};

const root = ReactDOM.createRoot(document.getElementById("root"));

root.render(<App />);
