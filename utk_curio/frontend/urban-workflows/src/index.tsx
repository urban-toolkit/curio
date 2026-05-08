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
import { pyodideExecutor } from "./services/PyodideExecutor";

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
  if (process.env.PYODIDE_ENABLED !== 'true') {
    fetch(process.env.BACKEND_URL + "/node-types", {
      method: "POST",
      headers: { "Content-type": "application/json; charset=UTF-8" },
      body: JSON.stringify({ nodeTypes }),
    }).catch(() => {});
  }
})();

// Preload Pyodide in the background when enabled so it's ready by the time
// the user clicks ▶ on a node. (~30 MB download, happens once then cached.)
if (process.env.PYODIDE_ENABLED === 'true') {
    pyodideExecutor.load().catch((err) =>
        console.warn('[Curio/Pyodide] Background preload failed:', err)
    );
}

import FlowProvider from "./providers/FlowProvider";
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
import { useCode } from "./hook/useCode";

const WorkflowRestorer: React.FC = () => {
    const { loadTrill } = useCode();

    React.useEffect(() => {
        if (process.env.PYODIDE_ENABLED !== 'true') return;
        try {
            const saved = localStorage.getItem('curio_workflow');
            if (saved) loadTrill(JSON.parse(saved));
        } catch (_) {}
    }, []);

    return null;
};

const MainCanvasRoute: React.FC = () => (
  <DialogProvider>
    <FlowProvider>
      <WorkflowRestorer />
      <TemplateProvider>
        <ProjectLoader>
          <MainCanvas />
        </ProjectLoader>
      </TemplateProvider>
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
    <BrowserRouter basename={(process.env.PUBLIC_PATH || "/").replace(/\/$/, "") || undefined}>
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
                      element={
                        <RequireAuth>
                          <HomeRedirect />
                        </RequireAuth>
                      }
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
