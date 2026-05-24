import type { NodeCategory } from "../registry/types";

/** Short labels for node categories (palette chips, package headers, etc.). */
export const NODE_CATEGORY_SHORT_LABEL: Record<NodeCategory, string> = {
    data: "Data",
    computation: "Compute",
    vis_grammar: "Viz",
    vis_simple: "Chart",
    flow: "Flow",
};
