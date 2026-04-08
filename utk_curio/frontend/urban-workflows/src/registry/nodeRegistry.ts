import { NodeType } from '../constants';
import { NodeDescriptor } from './types';

const registry = new Map<NodeType, NodeDescriptor>();

export function registerNode(descriptor: NodeDescriptor): void {
  if (registry.has(descriptor.id)) {
    console.warn(`NodeDescriptor for ${descriptor.id} is being overwritten`);
  }
  registry.set(descriptor.id, descriptor);
}

export function getNodeDescriptor(nodeType: NodeType): NodeDescriptor {
  const desc = registry.get(nodeType);
  if (!desc) throw new Error(`No descriptor registered for NodeType: ${nodeType}`);
  return desc;
}

export function getAllNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values());
}

export function getPaletteNodeTypes(): NodeDescriptor[] {
  return Array.from(registry.values())
    .filter(d => d.inPalette)
    .sort((a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999));
}
