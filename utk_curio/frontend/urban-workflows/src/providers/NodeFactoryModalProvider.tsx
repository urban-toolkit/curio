import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import type { InstallResponse } from "../api/packsApi";
import { useToastContext } from "./ToastProvider";
import type { Draft } from "../pages/nodes/factoryDraftModel";
import { NodeFactoryWizard } from "../pages/nodes/NodeFactoryWizard";
import modalStyles from "../pages/nodes/NodeFactoryModal.module.css";

export type OpenNodeFactoryOptions = {
  blank?: boolean;
  draft?: Draft | null;
  forkInstallNotice?: boolean;
  /** Fired after install succeeds and the pack registry refresh has run inside the wizard. */
  onInstallSuccess?: (result: InstallResponse) => void;
};

type NodeFactoryModalContextValue = {
  openNodeFactory: (opts?: OpenNodeFactoryOptions) => void;
  closeNodeFactory: () => void;
};

const NodeFactoryModalContext = createContext<NodeFactoryModalContextValue | null>(null);

function cloneDraft(d: Draft): Draft {
  return JSON.parse(JSON.stringify(d)) as Draft;
}

export function NodeFactoryModalProvider({ children }: { children: React.ReactNode }) {
  const { showToast } = useToastContext();
  const [visible, setVisible] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  const [initialDraft, setInitialDraft] = useState<Draft | null>(null);
  const [forkInstallNotice, setForkInstallNotice] = useState(false);
  const wizardDirtyRef = useRef(false);
  const preOpenFocusRef = useRef<HTMLElement | null>(null);
  const onInstallSuccessExtraRef = useRef<((r: InstallResponse) => void) | null>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);

  const closeNodeFactory = useCallback((force?: boolean) => {
    if (!force && wizardDirtyRef.current) {
      const ok = window.confirm("Discard your changes in Node Factory?");
      if (!ok) return;
    }
    wizardDirtyRef.current = false;
    setVisible(false);
    setForkInstallNotice(false);
    onInstallSuccessExtraRef.current = null;
    const el = preOpenFocusRef.current;
    preOpenFocusRef.current = null;
    queueMicrotask(() => el?.focus?.());
  }, []);

  useEffect(() => {
    if (!visible) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [visible]);

  const openNodeFactory = useCallback((opts?: OpenNodeFactoryOptions) => {
    preOpenFocusRef.current = document.activeElement as HTMLElement | null;
    wizardDirtyRef.current = false;
    onInstallSuccessExtraRef.current = opts?.onInstallSuccess ?? null;
    const blank = opts?.blank ?? false;
    if (blank) {
      setInitialDraft(null);
    } else if (opts?.draft?.kinds?.length) {
      setInitialDraft(cloneDraft(opts.draft));
    } else {
      setInitialDraft(null);
    }
    setForkInstallNotice(!!opts?.forkInstallNotice);
    setResetKey((k) => k + 1);
    setVisible(true);
  }, []);

  useEffect(() => {
    if (!visible) return;

    const onKeyDownCapture = (ev: KeyboardEvent) => {
      if (ev.key !== "Escape") return;
      ev.preventDefault();
      ev.stopPropagation();
      closeNodeFactory(false);
    };

    window.addEventListener("keydown", onKeyDownCapture, true);
    return () => window.removeEventListener("keydown", onKeyDownCapture, true);
  }, [visible, closeNodeFactory]);

  useEffect(() => {
    if (!visible) return;
    const surface = surfaceRef.current;
    if (!surface) return;

    const listFocusables = () => {
      const sel =
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
      return [...surface.querySelectorAll<HTMLElement>(sel)].filter(
        (n) => n.offsetParent !== null || n === document.activeElement,
      );
    };

    const t = window.setTimeout(() => {
      const nodes = listFocusables();
      nodes[0]?.focus();
    }, 0);

    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key !== "Tab") return;
      const nodes = listFocusables();
      if (nodes.length === 0) return;
      const idx = nodes.indexOf(document.activeElement as HTMLElement);
      if (ev.shiftKey) {
        if (idx <= 0) {
          ev.preventDefault();
          nodes[nodes.length - 1]!.focus();
        }
      } else if (idx === -1 || idx === nodes.length - 1) {
        ev.preventDefault();
        nodes[0]!.focus();
      }
    };

    surface.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(t);
      surface.removeEventListener("keydown", onKeyDown);
    };
  }, [visible, resetKey]);

  const wizardDirtySetter = useCallback((d: boolean) => {
    wizardDirtyRef.current = d;
  }, []);

  const onInstallSuccess = useCallback(
    (result: InstallResponse) => {
      showToast(`Installed ${result.pack.name} (${result.pack.version}).`, "success");
      onInstallSuccessExtraRef.current?.(result);
      closeNodeFactory(true);
    },
    [closeNodeFactory, showToast],
  );

  const ctx = useMemo(
    () => ({ openNodeFactory, closeNodeFactory }),
    [closeNodeFactory, openNodeFactory],
  );

  const modal = visible ? (
    createPortal(
      <div
        className={modalStyles.overlayRoot}
        role="presentation"
        data-curio-node-factory-overlay="true"
        onMouseDown={(e) => {
          if (e.target === e.currentTarget) closeNodeFactory(false);
        }}
      >
        <div
          ref={surfaceRef}
          className={modalStyles.modalSurface}
          role="dialog"
          aria-modal="true"
          aria-labelledby="node-factory-modal-title"
          tabIndex={-1}
        >
          <div className={modalStyles.modalTopBar}>
            <h2 className={modalStyles.modalTitle} id="node-factory-modal-title">
              Node factory
            </h2>
            <button
              type="button"
              className={modalStyles.closeBtn}
              onClick={() => closeNodeFactory(false)}
            >
              Close
            </button>
          </div>
          <NodeFactoryWizard
            resetKey={resetKey}
            initialDraft={initialDraft ?? undefined}
            forkInstallNotice={forkInstallNotice}
            onRequestClose={() => closeNodeFactory(false)}
            onInstallSuccess={onInstallSuccess}
            onDirtyChange={wizardDirtySetter}
          />
        </div>
      </div>,
      document.body,
    )
  ) : null;

  return (
    <NodeFactoryModalContext.Provider value={ctx}>
      {children}
      {modal}
    </NodeFactoryModalContext.Provider>
  );
}

export function useNodeFactoryModal(): NodeFactoryModalContextValue {
  const v = useContext(NodeFactoryModalContext);
  if (!v) {
    throw new Error("useNodeFactoryModal must be used within NodeFactoryModalProvider");
  }
  return v;
}
