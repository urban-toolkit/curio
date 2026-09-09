import React, { Suspense, useEffect, useState } from "react";
import { subscribeConnectionKeysRequests, type ConnectionKeysFocus } from "./connectionKeysRequest";

const AiSettingsModal = React.lazy(() => import("../AiSettingsModal"));

/**
 * dev/116: mounted once on the canvas (the agent dock overlay). When a card
 * asks for the Connection keys section, this opens the settings modal on it
 * with the host prefilled. Nothing renders until asked.
 */
export const ConnectionKeysModalHost: React.FC = () => {
  const [focus, setFocus] = useState<ConnectionKeysFocus | null>(null);
  useEffect(() => subscribeConnectionKeysRequests(setFocus), []);
  if (!focus) return null;
  return (
    <Suspense fallback={null}>
      <AiSettingsModal isOpen onClose={() => setFocus(null)} focus={focus} />
    </Suspense>
  );
};
