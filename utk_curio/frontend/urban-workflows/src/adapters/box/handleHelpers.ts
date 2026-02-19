import { Position } from 'reactflow';
import { HandleDef } from '../../registry/types';

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

/** Append a top source handle id="in/out" (grammar + display boxes). */
export function withBidirectional(base: HandleDef[]): HandleDef[] {
  return [
    ...base,
    { id: 'in/out', type: 'source', position: Position.Top, isConnectableOverride: suggestionGuard },
  ];
}

/** FlowSwitch: bottom target + top target, right source rendered inside container. */
export function flowSwitchHandles(): HandleDef[] {
  return [
    { id: 'in1', type: 'target', position: Position.Bottom, isConnectableOverride: suggestionGuard },
    { id: 'in2', type: 'target', position: Position.Top, isConnectableOverride: suggestionGuard },
    { id: 'out', type: 'source', position: Position.Right },
  ];
}
