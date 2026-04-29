import React from "react";
import ReactDOM from "react-dom/client";
import * as monaco from "monaco-editor";
import { loader } from "@monaco-editor/react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  useParams,
} from "react-router-dom";

(self as any).MonacoEnvironment = {
  getWorker(_: string, label: string) {
    if (label === "json") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/json/json.worker", import.meta.url)
      );
    }
    if (label === "css" || label === "scss" || label === "less") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/css/css.worker", import.meta.url)
      );
    }
    if (label === "html" || label === "handlebars" || label === "razor") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/html/html.worker", import.meta.url)
      );
    }
    if (label === "typescript" || label === "javascript") {
      return new Worker(
        new URL("monaco-editor/esm/vs/language/typescript/ts.worker", import.meta.url)
      );
    }
    return new Worker(
      new URL("monaco-editor/esm/vs/editor/editor.worker", import.meta.url)
    );
  },
};

loader.config({ monaco });
(window as unknown as { monaco: typeof monaco }).monaco = monaco;

import "./registry";
import { getAllNodeTypes } from "./registry";

(() => {
  const nodeTypes: Record<
    string,
    { inputTypes: string[]; outputTypes: string[] }
  > = {};
  for (const desc of getAllNodeTypes()) {
    nodeTypes[desc.id] = {
      inputTypes: desc.inputPorts.flatMap((p) => p.types),
      outputTypes: desc.outputPorts.flatMap((p) => p.types),
    };
  }
  fetch(process.env.BACKEND_URL + "/node-types", {
    method: "POST",
    headers: { "Content-type": "application/json; charset=UTF-8" },
    body: JSON.stringify({ nodeTypes }),
  }).catch(() => {});
})();

import FlowProvider from "./providers/FlowProvider";
import CollaborationProvider from "./providers/CollaborationProvider";
import TemplateProvider from "./providers/TemplateProvider";
import UserProvider, { useUserContext } from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { ToastProvider } from "./providers/ToastProvider";
import { BackendHealthBanner } from "./providers/BackendHealthBanner";
import { MainCanvas } from "./components/MainCanvas";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import LLMProvider from "./providers/LLMProvider";
import { RequireAuth } from "./components/RequireAuth";

import SignIn from "./pages/auth/SignIn";
import SignUp from "./pages/auth/SignUp";
import ProjectsList from "./pages/projects/ProjectsList";
import { ProjectLoader } from "./components/ProjectLoader";

const MainCanvasRoute: React.FC = () => (
  <DialogProvider>
    <FlowProvider>
      <CollaborationProvider>
        <TemplateProvider>
          <ProjectLoader>
            <MainCanvas />
          </ProjectLoader>
        </TemplateProvider>
      </CollaborationProvider>
    </FlowProvider>
  </DialogProvider>
);

const LegacyWorkflowRedirect: React.FC = () => {
  const { id } = useParams<{ id?: string }>();

  return <Navigate to={id ? `/dataflow/${id}` : "/dataflow"} replace />;
};

const HomeRedirect: React.FC = () => {
  const { skipProjectPage } = useUserContext();

  return <Navigate to={skipProjectPage ? "/dataflow" : "/projects"} replace />;
};

const ProjectsRoute: React.FC = () => {
  const { skipProjectPage } = useUserContext();

  if (skipProjectPage) return <Navigate to="/dataflow" replace />;

  return <ProjectsList />;
};

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <BackendHealthBanner>
        <ToastProvider>
          <ReactFlowProvider>
            <LLMProvider>
              <ProvenanceProvider>
                <UserProvider>
                  <Routes>
                    <Route path="/auth/signin" element={<SignIn />} />
                    <Route path="/auth/signup" element={<SignUp />} />
                    <Route
                      path="/projects"
                      element={
                        <RequireAuth>
                          <ProjectsRoute />
                        </RequireAuth>
                      }
                    />
                    <Route
                      path="/dataflow/:id?"
                      element={
                        <RequireAuth>
                          <MainCanvasRoute />
                        </RequireAuth>
                      }
                    />
                    <Route
                      path="/workflow/:id?"
                      element={<LegacyWorkflowRedirect />}
                    />
                    <Route
                      path="/"
                      element={<HomeRedirect />}
                    />
                  </Routes>
                </UserProvider>
              </ProvenanceProvider>
            </LLMProvider>
          </ReactFlowProvider>
        </ToastProvider>
      </BackendHealthBanner>
    </BrowserRouter>
  );
};

const root = ReactDOM.createRoot(document.getElementById("root")!);

root.render(<App />);
