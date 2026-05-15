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
 * replaces the URL with ``/nodes`` so the factory is not a standalone page.
 */
const NodeFactoryRouteBridge: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { openNodeFactory } = useNodeFactoryModal();
  const consumedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (consumedKeyRef.current === location.key) return;
    consumedKeyRef.current = location.key;

    const fromNav = (location.state as { curioDraft?: Draft } | null)?.curioDraft;
    const fromStorage = !fromNav ? readStoredWizardHydrationDraft() : null;
    clearStoredWizardHydrationDraft();

    const incoming = fromNav ?? fromStorage;
    if (incoming?.kinds?.length) {
      openNodeFactory({ draft: incoming });
    } else {
      openNodeFactory({ blank: true });
    }
    navigate("/nodes", { replace: true });
  }, [location.key, location.state, navigate, openNodeFactory]);

  return null;
};

export default NodeFactoryRouteBridge;
