/**
 * The monitor's two tabs: Status, what the deployment is doing now, and
 * Usage, what it did for the people using it over the last 90 days. The
 * /monitor page keeps the tab in its URL (`/monitor`, `/monitor/usage`), the
 * canvas's Monitor drawer in its state.
 */
import type { TabBarTab } from "../../components/layout/TabBar";

export type MonitorTab = "status" | "usage";

/** The tabs, in their order. */
export const MONITOR_TABS: TabBarTab<MonitorTab>[] = [
  { key: "status", label: "Status" },
  { key: "usage", label: "Usage" },
];

/** The page's path of *tab*. */
export function monitorPath(tab: MonitorTab): string {
  return tab === "usage" ? "/monitor/usage" : "/monitor";
}

/** The tab a page path's segment after /monitor names: Status with none, null when it names no tab. */
export function tabOfSegment(segment: string | undefined): MonitorTab | null {
  if (segment === undefined || segment === "") return "status";
  return segment === "usage" ? "usage" : null;
}
