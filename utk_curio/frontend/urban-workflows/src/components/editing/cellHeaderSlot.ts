// Where a notebook cell's header holds the node editor's tab switchers, among
// the cell's other tools, so the cell has no row of tabs of its own. NodeContainer
// provides the element; NodeEditor renders its tabs into it through a portal,
// which keeps them inside the editor's Tab.Container. Null on the canvas.
import { createContext, useContext } from "react";

export const CellHeaderSlotContext = createContext<HTMLElement | null>(null);

export const useCellHeaderSlot = () => useContext(CellHeaderSlotContext);
