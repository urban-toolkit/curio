// The types FlowProvider shares with the rest of the app: a node's output,
// an interaction, a propagation between pools, and how a node's run ended.
import type { SelectionEchoOptions } from "../../utils/selectionEcho";

/** `selectionEcho`: a selection coming back through a Data Pool, not new data,
 * and `selectionSource` whose it is (utils/selectionEcho). */
export interface IOutput extends SelectionEchoOptions {
    nodeId: string;
    output: unknown;
}

export interface IInteraction {
    nodeId: string;
    details: any;
    priority: number; // used to solve conflicts of interactions 1 has more priority than 0
}

// propagating interactions between pools at different resolutions
export interface IPropagation {
    nodeId: string;
    propagation: any; // {[index]: [interaction value]}
}

// applyNewOutputs = useCallback((newOutNodeId: string, newOutput: string)

/** How a node's run ended, as the node reports it to the runner. */
export interface NodeExecOutcome {
    /** The run failed: the runner runs nothing that depends on this node. */
    failed?: boolean;
}
