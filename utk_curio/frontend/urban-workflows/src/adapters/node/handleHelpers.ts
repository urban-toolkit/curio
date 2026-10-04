import { Position } from 'reactflow';
import { HandleDef } from '../../registry/types';
import { inputCircleCount, slotHandleId } from '../../utils/inputSlots';

const suggestionGuard = (data: any, isConnectable: boolean) =>
  isConnectable && (data.suggestionType == undefined || data.suggestionType === 'none');

/** Left target + right source (most common layout). */
export function standardInOut(): HandleDef[] {
  return [
    { id: 'in', type: 'target', position: Position.Left, isConnectableOverride: suggestionGuard },
    { id: 'out', type: 'source', position: Position.Right, isConnectableOverride: suggestionGuard },
  ];
}

/** Right source only (e.g. DataLoading). */
export function outputOnly(): HandleDef[] {
  return [
    { id: 'out', type: 'source', position: Position.Right, isConnectableOverride: suggestionGuard },
  ];
}

/** Left target only (e.g. DataExport). */
export function inputOnly(): HandleDef[] {
  return [
    { id: 'in', type: 'target', position: Position.Left, isConnectableOverride: suggestionGuard },
  ];
}

/**
 * *base* with its `in` handle replaced by a node's input circles: one per
 * wired circle plus a free one below, up to *max*, spread down the left edge.
 * Circle 0 keeps the id `in`, so a node with one circle draws as before.
 */
export function withInputCircles(base: HandleDef[], wired: number[], max: number): HandleDef[] {
  const input = base.find((h) => h.id === 'in');
  if (!input) return base;
  const count = inputCircleCount(wired, max);
  const circles: HandleDef[] = Array.from({ length: count }, (_, slot) => ({
    ...input,
    id: slotHandleId(slot),
    style: count === 1 ? input.style : { ...input.style, top: `${((slot + 1) * 100) / (count + 1)}%` },
  }));
  return base.flatMap((h) => (h === input ? circles : [h]));
}

/** Append a top source handle id="in/out" (grammar + display boxes). */
export function withBidirectional(base: HandleDef[]): HandleDef[] {
  return [
    ...base,
    { id: 'in/out', type: 'source', position: Position.Top, isConnectableOverride: suggestionGuard },
  ];
}

