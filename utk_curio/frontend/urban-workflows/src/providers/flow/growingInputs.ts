// Which nodes grow an input circle per edge, read from their template's input
// port (utils/inputSlots).
import { tryGetNodeDescriptor } from "../../registry/nodeRegistry";
import { growsInputCircles, inputCapacity } from "../../utils/inputSlots";

type FlowNodeLike = { data?: { nodeType?: string } & Record<string, any> } | null | undefined;

export function nodeGrowsInputs(node: FlowNodeLike): boolean {
    if (!node?.data?.nodeType) return false;
    const descriptor = tryGetNodeDescriptor(node.data.nodeType as any);
    return descriptor !== undefined && growsInputCircles(descriptor.inputPorts);
}

/** How many edges *node* takes; `Infinity` for any number. */
export function nodeInputCapacity(node: FlowNodeLike): number {
    const descriptor = node?.data?.nodeType ? tryGetNodeDescriptor(node.data.nodeType as any) : undefined;
    return descriptor ? inputCapacity(descriptor.inputPorts) : 1;
}
