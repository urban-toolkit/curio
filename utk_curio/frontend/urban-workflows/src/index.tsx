import "./styles/curioTokens.css";
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
import {
  refreshPackRegistry,
  syncNodeTypeRegistry,
} from "./registry/packRegistryBootstrap";

/** Re-export for embedders / tooling that imports the app entry-point. */
export { refreshPackRegistry };

(window as unknown as { curio?: Record<string, unknown> }).curio = {
  ...((window as unknown as { curio?: Record<string, unknown> }).curio ?? {}),
  refreshPackRegistry,
};

// Boot sequence:
//   1. Push the built-in port table immediately (so the backend can
//      validate ports even before sign-in).
//   2. Try to pull installed packs; if the user is already authenticated
//      (e.g. via a persisted token), register pack descriptors and
//      re-push the merged port table. Anonymous boots are a no-op until
//      sign-in calls refreshPackRegistry() explicitly.
syncNodeTypeRegistry().then(() => {
  void refreshPackRegistry();
});

import FlowProvider from "./providers/FlowProvider";
import TemplateProvider from "./providers/TemplateProvider";
import UserProvider, { useUserContext } from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { ToastProvider } from "./providers/ToastProvider";
import { NodeFactoryModalProvider } from "./providers/NodeFactoryModalProvider";
import { NodeWarehouseDrawerProvider } from "./providers/NodeWarehouseDrawerProvider";
import { BackendHealthBanner } from "./providers/BackendHealthBanner";
import { MainCanvas } from "./components/MainCanvas";
import { PackPaletteProvider } from "./providers/PackPaletteContext";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import LLMProvider from "./providers/LLMProvider";
import { RequireAuth } from "./components/RequireAuth";

import SignIn from "./pages/auth/SignIn";
import SignUp from "./pages/auth/SignUp";
import ProjectsList from "./pages/projects/ProjectsList";
import NodeFactory from "./pages/nodes/NodeFactory";
import { ProjectLoader } from "./components/ProjectLoader";

const MainCanvasRoute: React.FC = () => (
  <DialogProvider>
    <FlowProvider>
      <TemplateProvider>
        <ProjectLoader>
          <PackPaletteProvider>
            <MainCanvas />
          </PackPaletteProvider>
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
          <NodeWarehouseDrawerProvider>
            <NodeFactoryModalProvider>
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
                      path="/nodes/factory"
                      element={
                        <RequireAuth>
                          <NodeFactory />
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
            </NodeFactoryModalProvider>
          </NodeWarehouseDrawerProvider>
        </ToastProvider>
      </BackendHealthBanner>
    </BrowserRouter>
  );
};

const root = ReactDOM.createRoot(document.getElementById("root")!);

root.render(<App />);
