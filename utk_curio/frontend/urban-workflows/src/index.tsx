import React from "react";
import ReactDOM from "react-dom/client";

import FlowProvider from "./providers/FlowProvider";
import TemplateProvider from "./providers/TemplateProvider";
import UserProvider from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { MainCanvas } from "./components/MainCanvas";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import LLMProvider from "./providers/LLMProvider";

const App: React.FC = () => {
  return (
    <ReactFlowProvider>
      <LLMProvider>
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
      </LLMProvider>
    </ReactFlowProvider>
  );
};

const root = ReactDOM.createRoot(document.getElementById("root"));

root.render(<App />);
