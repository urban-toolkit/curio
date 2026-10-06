// Where a node's header holds the node editor's tab switchers, among the node's
// other tools, on the canvas and in a notebook cell alike, so the node has no
// row of tabs of its own. NodeContainer provides the element; NodeEditor renders
// its tabs into it through a portal, which keeps them inside the editor's
// Tab.Container. Null where there is no header (a dashboard tile).
import { createContext, useContext } from "react";

export const NodeHeaderSlotContext = createContext<HTMLElement | null>(null);

export const useNodeHeaderSlot = () => useContext(NodeHeaderSlotContext);
