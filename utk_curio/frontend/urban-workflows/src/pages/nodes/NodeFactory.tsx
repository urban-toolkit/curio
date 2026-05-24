import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useNodeFactoryModal } from "../../providers/NodeFactoryModalProvider";
import {
  clearStoredWizardHydrationDraft,
  readStoredWizardHydrationDraft,
} from "../../utils/palettePackFactoryDraft";
import type { Draft } from "./factoryDraftModel";

/**
 * Deep-link target for ``/nodes/factory``. Opens the modal wizard and
 * sends the user back to the canvas — there is no standalone factory page.
 *
 * Redirect target prefers the previous canvas route (stashed in
 * ``location.state.returnTo`` by the caller, or extracted from
 * ``document.referrer``); falls back to ``/`` so callers without context
 * still land somewhere reachable. Using ``/`` directly would deposit
 * users at the projects list, not the canvas they came from.
 */
const NodeFactoryRouteBridge: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { openNodeFactory } = useNodeFactoryModal();
  const consumedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (consumedKeyRef.current === location.key) return;
    consumedKeyRef.current = location.key;

    const state = (location.state as { curioDraft?: Draft; returnTo?: string } | null);
    const fromNav = state?.curioDraft;
    const fromStorage = !fromNav ? readStoredWizardHydrationDraft() : null;
    clearStoredWizardHydrationDraft();

    const incoming = fromNav ?? fromStorage;
    if (incoming?.kinds?.length) {
      openNodeFactory({ draft: incoming });
    } else {
      openNodeFactory({ blank: true });
    }

    const referrerPath = (() => {
      try {
        const ref = new URL(document.referrer);
        if (ref.origin !== window.location.origin) return null;
        return ref.pathname + ref.search;
      } catch {
        return null;
      }
    })();
    const target = state?.returnTo ?? referrerPath ?? "/";
    navigate(target, { replace: true });
  }, [location.key, location.state, navigate, openNodeFactory]);

  return null;
};

export default NodeFactoryRouteBridge;
