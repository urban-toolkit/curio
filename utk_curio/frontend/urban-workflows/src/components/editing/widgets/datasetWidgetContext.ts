/**
 * What a dataset widget's control asks of the node it is on: the title and
 * format of the dataset its value names, how a file chosen in it gets in, and
 * whether something that can be dropped on the node is over it. The node takes
 * the drop itself (NodeContainer in components/styles.tsx), on its whole card,
 * since the code editor stops drops before they reach a control; it provides
 * this. A control under no such node (a Widgets tab default, a dashboard tile)
 * shows the id it holds and offers no Choose file.
 */
import { createContext, useContext } from "react";

export interface DatasetWidgetNode {
  /** The title and format of the dataset *id* names, when the canvas knows it. */
  describe: (id: string) => { title?: string; format?: string } | undefined;
  /** Takes files chosen in the control as a drop on the node takes them;
   * absent where nothing can be added. */
  takeFiles?: (files: File[]) => void;
  /** Whether a file or a dataset that the node takes is dragged over it. */
  dropping: boolean;
}

const NO_NODE: DatasetWidgetNode = { describe: () => undefined, dropping: false };

export const DatasetWidgetContext = createContext<DatasetWidgetNode>(NO_NODE);

export function useDatasetWidgetNode(): DatasetWidgetNode {
  return useContext(DatasetWidgetContext);
}
