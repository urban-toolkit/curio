import React from "react";
import ReactDOM from "react-dom/client";
import * as monaco from "monaco-editor";
import { loader } from "@monaco-editor/react";

// Use bundled Monaco instead of CDN so the editor works offline
loader.config({ monaco });
// Expose on window for tests and any code that uses window.monaco (e.g. getEditors())
(window as unknown as { monaco: typeof monaco }).monaco = monaco;

import './registry';
import { getAllNodeTypes } from './registry';

// Send the frontend node-type registry to the backend so it can use it
// for provenance, templates, and connection validation without hardcoded dicts.
(() => {
  const nodeTypes: Record<string, { inputTypes: string[]; outputTypes: string[] }> = {};
  for (const desc of getAllNodeTypes()) {
    nodeTypes[desc.id] = {
      inputTypes: desc.inputPorts.flatMap(p => p.types),
      outputTypes: desc.outputPorts.flatMap(p => p.types),
    };
  }
  fetch(process.env.BACKEND_URL + '/node-types', {
    method: 'POST',
    headers: { 'Content-type': 'application/json; charset=UTF-8' },
    body: JSON.stringify({ nodeTypes }),
  }).catch(() => {});
})();

import FlowProvider from "./providers/FlowProvider";
import TemplateProvider from "./providers/TemplateProvider";
import UserProvider from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { BackendHealthBanner } from "./providers/BackendHealthBanner";
import { MainCanvas } from "./components/MainCanvas";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import LLMProvider from "./providers/LLMProvider";

const App: React.FC = () => {
  return (
    <BackendHealthBanner>
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
    </BackendHealthBanner>
  );
};

const root = ReactDOM.createRoot(document.getElementById("root"));

root.render(<App />);
