// The dataflow's shared tags (#662): the widget each Parameter node holds,
// which any node's code names as `[!! @name !!]`.
import { useMemo } from "react";
import { useFlowContext } from "../providers/FlowProvider";
import { sharedWidgetsOf } from "../utils/references/sharedParameters";
import type { WidgetDef } from "../utils/widgets/widgetModel";

export function useSharedWidgets(): WidgetDef[] {
    const flow = useFlowContext() as { nodes?: any[] };
    const computed = sharedWidgetsOf(flow?.nodes ?? []);
    // The same list keeps its identity, so editors do not redraw their chips
    // whenever an unrelated node changes.
    const signature = JSON.stringify(computed);
    return useMemo(() => computed, [signature]);
}
