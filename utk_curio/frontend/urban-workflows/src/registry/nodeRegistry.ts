import { BoxType } from '../constants';
import { BoxDescriptor } from './types';

const registry = new Map<BoxType, BoxDescriptor>();

export function registerNode(descriptor: BoxDescriptor): void {
  if (registry.has(descriptor.id)) {
    console.warn(`BoxDescriptor for ${descriptor.id} is being overwritten`);
  }
  registry.set(descriptor.id, descriptor);
}

export function getNodeDescriptor(boxType: BoxType): BoxDescriptor {
  const desc = registry.get(boxType);
  if (!desc) throw new Error(`No descriptor registered for BoxType: ${boxType}`);
  return desc;
}

export function getAllNodeTypes(): BoxDescriptor[] {
  return Array.from(registry.values());
}

export function getPaletteNodeTypes(): BoxDescriptor[] {
  return Array.from(registry.values())
    .filter(d => d.inPalette)
    .sort((a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999));
}
