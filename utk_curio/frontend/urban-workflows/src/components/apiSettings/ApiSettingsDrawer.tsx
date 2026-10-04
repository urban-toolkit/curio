import React from "react";
import { HeaderDrawer } from "../layout/HeaderDrawer";
import { ApiSettingsPanel } from "./ApiSettingsPanel";
import type { ApiSettingsFocus, ApiSettingsTab } from "./apiSettingsRequest";

export interface ApiSettingsDrawerProps {
  presented: boolean;
  tab: ApiSettingsTab;
  onTabChange: (tab: ApiSettingsTab) => void;
  focus: ApiSettingsFocus | null;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/** API Settings on the canvas and the dashboard: the settings page's panel in
 *  the top bar's drawer. */
export const ApiSettingsDrawer: React.FC<ApiSettingsDrawerProps> = ({
  presented,
  tab,
  onTabChange,
  focus,
  onRequestClose,
  onExitComplete,
}) => (
  <HeaderDrawer
    presented={presented}
    onRequestClose={onRequestClose}
    onExitComplete={onExitComplete}
    title="API Settings"
    titleId="api-settings-drawer-title"
    name="settings"
  >
    <ApiSettingsPanel tab={tab} onTabChange={onTabChange} focus={focus} />
  </HeaderDrawer>
);

export default ApiSettingsDrawer;
