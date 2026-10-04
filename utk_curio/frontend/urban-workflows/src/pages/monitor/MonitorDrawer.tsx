import React from "react";
import { HeaderDrawer } from "../../components/layout/HeaderDrawer";
import MonitorContent from "./MonitorContent";

export interface MonitorDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/** The monitor on the canvas and the dashboard: the /monitor page's content in
 *  the top bar's drawer. It polls while open. */
export const MonitorDrawer: React.FC<MonitorDrawerProps> = ({ presented, onRequestClose, onExitComplete }) => (
  <HeaderDrawer
    presented={presented}
    onRequestClose={onRequestClose}
    onExitComplete={onExitComplete}
    title="Monitor"
    titleId="monitor-drawer-title"
    name="monitor"
  >
    <MonitorContent />
  </HeaderDrawer>
);

export default MonitorDrawer;
