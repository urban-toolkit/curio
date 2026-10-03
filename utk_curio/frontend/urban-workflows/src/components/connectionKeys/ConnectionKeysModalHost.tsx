import React, { Suspense, useEffect, useState } from "react";
import { subscribeConnectionKeysRequests, type ConnectionKeysFocus } from "./connectionKeysRequest";

const ApiSettingsModal = React.lazy(() => import("../ApiSettingsModal"));

/**
 * dev/116: mounted once per page, by the top bar (GlobalPageHeader), which the
 * canvas wears too. When a card asks for the Connection keys section, this
 * opens the settings modal on it with the host prefilled. Nothing renders
 * until asked.
 */
export const ConnectionKeysModalHost: React.FC = () => {
  const [focus, setFocus] = useState<ConnectionKeysFocus | null>(null);
  useEffect(() => subscribeConnectionKeysRequests(setFocus), []);
  if (!focus) return null;
  return (
    <Suspense fallback={null}>
      <ApiSettingsModal isOpen onClose={() => setFocus(null)} focus={focus} />
    </Suspense>
  );
};
