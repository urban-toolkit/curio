import React, {
  Suspense,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { createPortal } from "react-dom";
import {
  tabForFocus,
  type ApiSettingsFocus,
  type ApiSettingsTab,
} from "../components/apiSettings/apiSettingsRequest";
import { useSlideDrawerPresentation } from "../hook/useSlideDrawerPresentation";

/** Loaded when first opened: the panel's module graph (the key clients, the
 *  LLM editor) has no business in every canvas that never opens it. */
const ApiSettingsDrawer = React.lazy(() => import("../components/apiSettings/ApiSettingsDrawer"));

type ApiSettingsDrawerContextValue = {
  /** Open on a tab's start, or on the place a card asked for. */
  openApiSettings: (focus?: ApiSettingsFocus | null) => void;
  closeApiSettings: () => void;
  isApiSettingsOpen: boolean;
};

const ApiSettingsDrawerContext = createContext<ApiSettingsDrawerContextValue | null>(null);

/**
 * Mounts API Settings as a drawer on the canvas and the dashboard, shaped like
 * the catalog drawer providers: the same two-phase slide, the same scroll lock,
 * and the drawer unmounted once its exit slide ends.
 */
export function ApiSettingsDrawerProvider({ children }: { children: React.ReactNode }) {
  const { mounted, presented, open, close, finishExit } = useSlideDrawerPresentation();
  const [tab, setTab] = useState<ApiSettingsTab>("keys");
  const [focus, setFocus] = useState<ApiSettingsFocus | null>(null);

  // Gated on `mounted`, like its peers: `presented` goes false a frame into
  // the exit slide, and releasing the lock then let the page jump behind it.
  useEffect(() => {
    if (!mounted) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [mounted]);

  const openApiSettings = useCallback(
    (next: ApiSettingsFocus | null = null) => {
      setFocus(next);
      setTab(tabForFocus(next));
      open();
    },
    [open],
  );

  const ctx = useMemo(
    () => ({ openApiSettings, closeApiSettings: close, isApiSettingsOpen: mounted }),
    [close, openApiSettings, mounted],
  );

  const drawer = mounted
    ? createPortal(
        <Suspense fallback={null}>
          <ApiSettingsDrawer
            presented={presented}
            tab={tab}
            onTabChange={setTab}
            focus={focus}
            onRequestClose={close}
            onExitComplete={finishExit}
          />
        </Suspense>,
        document.body,
      )
    : null;

  return (
    <ApiSettingsDrawerContext.Provider value={ctx}>
      {children}
      {drawer}
    </ApiSettingsDrawerContext.Provider>
  );
}

/** The drawer's controls on the canvas and the dashboard, or null on a page
 *  without one, where API Settings is the settings page. */
export function useApiSettingsDrawerOptional(): ApiSettingsDrawerContextValue | null {
  return useContext(ApiSettingsDrawerContext);
}
