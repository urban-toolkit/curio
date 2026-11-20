import React from "react";
import { HeaderDrawer } from "../../components/layout/HeaderDrawer";
import MonitorContent from "./MonitorContent";
import type { MonitorTab } from "./monitorTabs";

export interface MonitorDrawerProps {
  presented: boolean;
  /** The tab shown, which the drawer's provider keeps in its state. */
  tab: MonitorTab;
  onTabChange: (tab: MonitorTab) => void;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/** The monitor on the canvas and the dashboard: the /monitor page's content in
 *  the top bar's drawer. It polls while open. */
export const MonitorDrawer: React.FC<MonitorDrawerProps> = ({
  presented,
  tab,
  onTabChange,
  onRequestClose,
  onExitComplete,
}) => (
  <HeaderDrawer
    presented={presented}
    onRequestClose={onRequestClose}
    onExitComplete={onExitComplete}
    title="Monitor"
    titleId="monitor-drawer-title"
    name="monitor"
  >
    <MonitorContent tab={tab} onTabChange={onTabChange} />
  </HeaderDrawer>
);

export default MonitorDrawer;
