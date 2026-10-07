// Which nodes take several inputs, read from their template's input ports
// (utils/inputSlots): one port that grows a circle per edge, or several ports.
import { tryGetNodeDescriptor } from "../../registry/nodeRegistry";
import { growsInputCircles, inputCapacity } from "../../utils/inputSlots";

type FlowNodeLike = { data?: { nodeType?: string } & Record<string, any> } | null | undefined;

export function nodeGrowsInputs(node: FlowNodeLike): boolean {
    if (!node?.data?.nodeType) return false;
    const descriptor = tryGetNodeDescriptor(node.data.nodeType as any);
    return descriptor !== undefined && growsInputCircles(descriptor.inputPorts);
}

/** Whether *node*'s template has several input ports, each taking one edge (the Spatial Join's points and polygons). */
export function nodeHasSeveralPorts(node: FlowNodeLike): boolean {
    if (!node?.data?.nodeType) return false;
    const descriptor = tryGetNodeDescriptor(node.data.nodeType as any);
    return (descriptor?.inputPorts?.length ?? 0) > 1;
}

/** How many edges *node* takes; `Infinity` for any number. */
export function nodeInputCapacity(node: FlowNodeLike): number {
    const descriptor = node?.data?.nodeType ? tryGetNodeDescriptor(node.data.nodeType as any) : undefined;
    return descriptor ? inputCapacity(descriptor.inputPorts) : 1;
}
