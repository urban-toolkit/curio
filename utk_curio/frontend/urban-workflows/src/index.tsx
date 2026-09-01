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
//   so the palette is populated before anything reads it.
//
//   An anonymous boot is a genuine no-op: `refreshPackageRegistry` returns
//   early without a session token, because `/api/packages` requires auth and
//   would only 401 on the sign-up page. Sign-in refreshes the registry itself.
void refreshPackageRegistry();

import FlowProvider from "./providers/FlowProvider";
import { CollaborationProvider } from "./providers/CollaborationProvider";
import StarterProvider from "./providers/StarterProvider";
import UserProvider, { useUserContext } from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { ToastProvider } from "./providers/ToastProvider";
import { NodeCatalogDrawerProvider } from "./providers/NodeCatalogDrawerProvider";
import { AgentCatalogDrawerProvider } from "./providers/AgentCatalogDrawerProvider";
import { listenForPeerDatasetCatalogRefresh } from "./services/datasetCatalog";
import { DatasetCatalogDrawerProvider } from "./providers/datasetCatalog";
import { BackendHealthBanner } from "./providers/BackendHealthBanner";
import { MainCanvas } from "./components/MainCanvas";
import { PackagePaletteProvider } from "./providers/PackagePaletteContext";
import { DatasetPaletteProvider } from "./providers/DatasetPaletteContext";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import { RequireAuth } from "./components/RequireAuth";
import ErrorBoundary from "./components/ErrorBoundary";

import SignIn from "./pages/auth/SignIn";
import SignUp from "./pages/auth/SignUp";
import ProjectsList from "./pages/projects/ProjectsList";
import CatalogMasterPage from "./pages/catalog/CatalogMasterPage";
import NodeCatalogBrowse from "./pages/catalog/NodeCatalogBrowse";
import DataCatalogBrowse from "./pages/dataHub/DataCatalogBrowse";
import DataCatalogDetail from "./pages/dataHub/DataCatalogDetail";
import AgentCatalogBrowse from "./pages/agents/AgentCatalogBrowse";
import DataHubPage from "./pages/dataHub/DataHubPage";
import { ProjectLoader } from "./components/ProjectLoader";

const MainCanvasRoute: React.FC = () => (
  // CollaborationProvider must wrap FlowProvider: FlowProvider's mutation
  // handlers call ``useCollab()`` to broadcast graph changes, and a
  // context only reaches *descendants*. Putting it on the inside would
  // hand FlowProvider the no-op default value and silently drop every
  // broadcast.
  <DialogProvider>
    <CollaborationProvider>
      <FlowProvider>
        {/* NodeCatalogDrawerProvider must sit INSIDE FlowProvider — the drawer
            calls useFlowContext to auto-save unsaved dataflows on Install, and
            a portal preserves React tree context, not DOM position. Outside
            FlowProvider, useFlowContext returns no-op defaults and Install
            silently does nothing. The drawer is only ever opened from canvas
            components (UpMenu, PackagesPaletteDropdown), so scoping it here
            doesn't reduce reach. */}
        <NodeCatalogDrawerProvider>
          <DatasetCatalogDrawerProvider>
            <AgentCatalogDrawerProvider>
              <StarterProvider>
                <ProjectLoader>
                  <PackagePaletteProvider>
                    <DatasetPaletteProvider>
                      <MainCanvas />
                    </DatasetPaletteProvider>
                  </PackagePaletteProvider>
                </ProjectLoader>
              </StarterProvider>
            </AgentCatalogDrawerProvider>
          </DatasetCatalogDrawerProvider>
        </NodeCatalogDrawerProvider>
      </FlowProvider>
    </CollaborationProvider>
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
                <ProvenanceProvider>
                  <UserProvider>
                    {/* Backstop under the per-node boundaries (#201): a throw
                        from page chrome rather than from a node still has to
                        land somewhere other than a blank document. */}
                    <ErrorBoundary label="route">
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
                      path="/catalog"
                      element={
                        <RequireAuth>
                          <CatalogMasterPage />
                        </RequireAuth>
                      }
                    >
                      <Route index element={<Navigate to="nodes" replace />} />
                      <Route path="nodes" element={<NodeCatalogBrowse />} />
                      <Route path="data" element={<DataCatalogBrowse />} />
                      <Route path="data/:datasetId" element={<DataCatalogDetail />} />
                      <Route path="agents" element={<AgentCatalogBrowse />} />
                    </Route>
                    <Route
                      path="/data-hub/:datasetId?"
                      element={
                        <RequireAuth>
                          <DataHubPage />
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
                    </ErrorBoundary>
                  </UserProvider>
                </ProvenanceProvider>
            </ReactFlowProvider>
        </ToastProvider>
      </BackendHealthBanner>
    </BrowserRouter>
  );
};

// A rejected promise nobody caught reaches `window` as an `unhandledrejection`,
// and webpack-dev-server's `client.overlay.runtimeErrors` listens for exactly
// that - so in development one escaped rejection paints the error overlay over
// the whole app (#201). Logging it here does not stop the overlay, but it names
// the rejection in the console instead of leaving only the overlay's stack, and
// it makes an escaped promise visible in production too, where there is no
// overlay at all and the failure was previously silent.
window.addEventListener("unhandledrejection", (event) => {
  console.error("[curio] unhandled promise rejection:", event.reason);
});

// Catalog mutations in ANOTHER tab must invalidate this one's cache. Without
// this the broadcast has no listener and the cross-tab half is inert: adding a
// dataset to all projects from `/catalog` in one tab left a dataflow open in
// another serving a listing cached from before the mutation.
listenForPeerDatasetCatalogRefresh();

const root = ReactDOM.createRoot(document.getElementById("root")!);

root.render(<App />);
