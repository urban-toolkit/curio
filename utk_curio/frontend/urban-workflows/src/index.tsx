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
import { refreshPackageRegistry } from "./registry/packageRegistryBootstrap";

/** Re-export for embedders / tooling that imports the app entry-point. */
export { refreshPackageRegistry };

(window as unknown as { curio?: Record<string, unknown> }).curio = {
  ...((window as unknown as { curio?: Record<string, unknown> }).curio ?? {}),
  refreshPackageRegistry,
};

// Boot sequence:
//   Fetch installed packages first — `refreshPackageRegistry()` registers every
//   package-derived descriptor (including the auto-installed `curio.builtin@1`)
//   and *then* pushes the merged port table to the backend. Calling
//   `syncNodeTypeRegistry()` up-front would POST an empty `{nodeTypes: {}}`
//   (the registry is empty at module-evaluation time post-Phase-B) and clear
//   the backend's `_node_type_registry`, leaving a validation gap until the
//   package fetch resolves. Anonymous boots are no-ops until sign-in calls
//   `refreshPackageRegistry()` explicitly.
void refreshPackageRegistry();

import FlowProvider from "./providers/FlowProvider";
import StarterProvider from "./providers/StarterProvider";
import UserProvider, { useUserContext } from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { ToastProvider } from "./providers/ToastProvider";
import { NodeCatalogDrawerProvider } from "./providers/NodeCatalogDrawerProvider";
import { BackendHealthBanner } from "./providers/BackendHealthBanner";
import { MainCanvas } from "./components/MainCanvas";
import { PackagePaletteProvider } from "./providers/PackagePaletteContext";
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
      <StarterProvider>
        <ProjectLoader>
          <PackagePaletteProvider>
            <MainCanvas />
          </PackagePaletteProvider>
        </ProjectLoader>
      </StarterProvider>
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
            <NodeCatalogDrawerProvider>
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
            </NodeCatalogDrawerProvider>
        </ToastProvider>
      </BackendHealthBanner>
    </BrowserRouter>
  );
};

const root = ReactDOM.createRoot(document.getElementById("root")!);

root.render(<App />);
