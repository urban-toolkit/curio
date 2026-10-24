/**
 * The controls a dashboard's viewer changes (#1117): the pin decides. Every
 * widget a pinned tile shows, a pinned Parameter node's included, except the
 * kinds `contracts/dashboardRuns.json` keeps read-only, whose free value could
 * name another of the owner's datasets or files. The backend holds a viewer's
 * values to the same rule (`runs/viewer.py::dashboard_controls`).
 */
import dashboardRuns from "../../contracts/dashboardRuns.json";
import { effectiveValue, normalizeWidgets, type WidgetDef } from "./widgetModel";

/** The widget kinds a viewer never changes, though their node is pinned. */
export const READ_ONLY_WIDGET_KINDS: readonly string[] = dashboardRuns.readOnlyWidgetKinds;

/** `{nodeId: {widgetName: value}}`: the values of the dashboard's controls. */
export type DashboardValues = Record<string, Record<string, unknown>>;

/** Whether a viewer may change *widget* on a pinned tile: every kind but the read-only ones. */
export function changeableOnDashboard(widget: Pick<WidgetDef, "type">): boolean {
    return !READ_ONLY_WIDGET_KINDS.includes(widget.type);
}

/** Every control the pinned tiles show, with its value as it stands, as a viewer's run takes them. */
export function dashboardValues(
    nodes: readonly { id: string; data?: any }[],
): DashboardValues {
    const values: DashboardValues = {};
    for (const node of nodes) {
        if (!node.data?.dashboardPinned) continue;
        const changeable = normalizeWidgets(node.data.widgets).filter(changeableOnDashboard);
        if (changeable.length === 0) continue;
        values[node.id] = Object.fromEntries(changeable.map((widget) => [widget.name, effectiveValue(widget)]));
    }
    return values;
}
