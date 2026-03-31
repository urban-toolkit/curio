import React from "react";
import ReactDOM from "react-dom/client";
import { pyodideExecutor } from "./services/PyodideExecutor";

// Preload Pyodide in the background when enabled so it's ready by the time
// the user clicks ▶ on a node. (~30 MB download, happens once then cached.)
if (process.env.PYODIDE_ENABLED === 'true') {
    pyodideExecutor.load().catch((err) =>
        console.warn('[Curio/Pyodide] Background preload failed:', err)
    );
}

import FlowProvider from "./providers/FlowProvider";
import TemplateProvider from "./providers/TemplateProvider";
import UserProvider from "./providers/UserProvider";
import DialogProvider from "./providers/DialogProvider";
import { MainCanvas } from "./components/MainCanvas";
import { ReactFlowProvider } from "reactflow";
import ProvenanceProvider from "./providers/ProvenanceProvider";
import LLMProvider fromv "./providers/LLMProvider";

const InteractionLogger: React.FC = () => {
  React.useEffect(() => {
    const handler = (event: Event) => {
      const target = event.target as HTMLElement | null;
      const buttonLike = target?.closest("button, [role='button'], a");
      if (!buttonLike) return;
      const el = buttonLike as HTMLElement;
      const label =
        el.getAttribute("aria-label") ||
        el.innerText.trim() ||
        el.id ||
        "(unlabeled)";
      console.log("[Curio][UI] click", {
        label,
        id: el.id,
        classes: el.className,
        path: window.location.pathname,
      });
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, []);
  return null;
};

const App: React.FC = () => {
  return (
    <ReactFlowProvider>
      <InteractionLogger />
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
