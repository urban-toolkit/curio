import React, { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useApiSettingsDrawerOptional } from "../../providers/ApiSettingsDrawerProvider";
import { settingsPath, subscribeApiSettingsRequests } from "./apiSettingsRequest";

/**
 * Mounted once per page, by the top bar (GlobalPageHeader), which the canvas
 * wears too. When a card asks for a place in API Settings, this opens the
 * drawer on it where there is one (the canvas, the dashboard), or goes to the
 * settings page on it. Renders nothing.
 */
export const ApiSettingsRequestHost: React.FC = () => {
  const drawer = useApiSettingsDrawerOptional();
  const navigate = useNavigate();
  useEffect(
    () =>
      subscribeApiSettingsRequests((focus) => {
        if (drawer) drawer.openApiSettings(focus);
        else navigate(settingsPath(focus));
      }),
    [drawer, navigate],
  );
  return null;
};
