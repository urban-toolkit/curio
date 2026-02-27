import { BoxType, SupportedType } from '../constants';
import { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import { Position, Edge } from 'reactflow';
import React from 'react';
import { INodeData, ICodeData } from '../types';
import { IPropagation } from '../providers/FlowProvider';

export interface PortDef {
  types: SupportedType[];
  cardinality?: '0' | '1' | 'n' | '[1,n]' | '[1,2]' | '2';
}

export type EditorType = 'code' | 'widgets' | 'grammar' | 'none';
export type BoxCategory = 'data' | 'computation' | 'vis_grammar' | 'vis_simple' | 'flow';

/* ── Handle configuration ──────────────────────────────────────────── */

export interface HandleDef {
  id: string;
  type: 'source' | 'target';
  position: Position;
  style?: React.CSSProperties;
  /** Compute handle style at render time (used by MergeFlow dynamic handles). */
  dynamicStyle?: (data: any, edges: Edge[]) => React.CSSProperties;
  /** Override default connectable logic per-handle. */
  isConnectableOverride?: (data: any, isConnectable: boolean, edges: Edge[]) => boolean;
}

/* ── BoxEditor configuration ───────────────────────────────────────── */

export interface EditorConfig {
  code: boolean;
  grammar: boolean;
  widgets: boolean;
  provenance?: boolean;
  disableWidgets?: boolean;
  /** DOM id for the editor output container (e.g. "vega" + nodeId). */
  outputId?: (nodeId: string) => string;
}

/* ── BoxContainer overrides ────────────────────────────────────────── */

export interface ContainerConfig {
  handleType?: 'in' | 'out' | 'in/out';
  disablePlay?: boolean;
  noContent?: boolean;
  boxWidth?: number;
  boxHeight?: number;
  styles?: React.CSSProperties;
}

/* ── Box Lifecycle Contract ────────────────────────────────────────── */

export type UseBoxStateReturn = ReturnType<typeof import('../hook/useBoxState').useBoxState>;

/**
 * Runtime data passed to every lifecycle hook by UniversalBox.
 *
 * Extends the persisted `INodeData` with FlowProvider runtime callbacks
 * that are injected when the node is mounted on the canvas.
 */
export interface BoxLifecycleData extends INodeData {
  /** FlowProvider callback — push this node's output to downstream nodes. */
  outputCallback: (nodeId: string, output: any) => void;
  /** FlowProvider callback — propagate interaction resolution data. */
  propagationCallback: (propagation: IPropagation) => void;
  /** FlowProvider callback — push interactions to connected interaction nodes. */
  interactionsCallback: (interactions: any, nodeId: string) => void;
  /** Current propagation counter (triggers re-processing in DataPool). */
  newPropagation?: number;
  /** AI suggestion marker — `"none"` or `undefined` means not a suggestion. */
  suggestionType?: string;
}

/**
 * The return value of a lifecycle hook.
 *
 * Every field is optional. UniversalBox applies defaults from `useBoxState`
 * for any field the lifecycle does not override. A no-op lifecycle may
 * return `{}`.
 */
export interface LifecycleResult {
  /** Compile a grammar spec and render the result (grammar-viz boxes). */
  applyGrammar?: (spec: string) => Promise<void>;
  /** Populate the widgets panel with custom DOM controls. */
  customWidgetsCallback?: (div: HTMLElement) => void;
  /** Override the initial code/grammar editor value. */
  defaultValueOverride?: string;
  /** Replace the default "play" action with a custom send-code routine. */
  sendCodeOverride?: any;
  /** Replace the `setSendCodeCallback` wiring between BoxEditor and the play button. */
  setSendCodeCallbackOverride?: any;
  /** When `true`, BoxContainer shows a loading spinner instead of the play button. */
  showLoading?: boolean;
  /** Custom React subtree rendered inside the BoxEditor content area. */
  contentComponent?: React.ReactNode;
  /** Replace `boxState.setOutput` — used when output state is managed locally (DataPool, MergeFlow). */
  setOutputCallbackOverride?: any;
  outputOverride?: ICodeData;
  /** Extra handles appended to `adapter.handles` at render time (MergeFlow dynamic inputs). */
  dynamicHandles?: HandleDef[];
}

/**
 * Contract type for box lifecycle hooks.
 *
 * Every lifecycle implementation **must** satisfy this signature.
 * The hook is called by `UniversalBox` on every render — it receives
 * the node's runtime `data` and the shared `boxState` from `useBoxState`,
 * and returns a `LifecycleResult` whose fields selectively override
 * defaults.
 *
 * **Rules:**
 * 1. Must be a valid React custom hook (may call `useState`, `useEffect`, etc.).
 * 2. Must be deterministic in its hook call order (React rules of hooks).
 * 3. Must return a `LifecycleResult` — omit fields to accept defaults.
 * 4. Must not call `boxState.setSendCodeCallback` directly — return
 *    `setSendCodeCallbackOverride` instead so UniversalBox can wire it.
 */
export type BoxLifecycleHook = (data: BoxLifecycleData, boxState: UseBoxStateReturn) => LifecycleResult;

/* ── Full adapter for a box type ───────────────────────────────────── */

export interface BoxAdapter {
  handles: HandleDef[];
  editor: EditorConfig | null;
  container: ContainerConfig;
  inputIconType?: string;
  outputIconType?: string;
  showTemplateModal?: boolean;
  useLifecycle: BoxLifecycleHook;
}

/* ── Descriptor ────────────────────────────────────────────────────── */

export interface BoxDescriptor {
  id: BoxType;
  category: BoxCategory;
  label: string;
  icon: IconDefinition;
  inputPorts: PortDef[];
  outputPorts: PortDef[];
  editor: EditorType;
  grammarId?: string;
  inPalette: boolean;
  paletteOrder?: number;
  description: string;
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  hasProvenance?: boolean;
  adapter: BoxAdapter;
  tutorialId?: string;
}
