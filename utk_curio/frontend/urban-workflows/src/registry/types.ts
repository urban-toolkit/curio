import { NodeType, SupportedType } from '../constants';
import { IconDefinition } from '@fortawesome/fontawesome-svg-core';
import { Position, Edge } from 'reactflow';
import React from 'react';
import { INodeData, ICodeData } from '../types';
import { IPropagation } from '../providers/FlowProvider';

/**
 * Identifier used as the dispatch key for a node kind.
 *
 * - **Built-ins** keep using `NodeType` enum members (e.g. `NodeType.DATA_LOADING`)
 *   so existing call sites continue to type-check unchanged.
 * - **Package kinds** use a canonical string of the form `<packageId>/<templateId>@<major>`
 *   (e.g. `"ai.urbanlab.uhvi/uhvi-load@1"`). This is the string the frontend
 *   registry, backend `_node_type_registry`, saved Trill graphs, and
 *   `/processPythonCode` all dispatch on.
 *
 * See ``docs/WAREHOUSE.md`` for the user-facing overview and
 * ``docs/schemas/node-package.v3.json`` for the manifest schema.
 */
export type NodeTemplateId = NodeType | string;

/**
 * Where a registered descriptor came from. Drives palette sectioning and any
 * future "remove package" affordance — built-ins must never be removed at runtime.
 */
export type NodeSource = 'core' | 'package';

/** Fork provenance when `source === 'package'` (from manifest `lineage`). */
export interface NodePackageLineageCoord {
  packageId: string;
  major: number;
}

export interface NodePackageLineage {
  forkedFrom: NodePackageLineageCoord;
  root: NodePackageLineageCoord;
}

/** Package-provenance metadata attached to descriptors whose `source === 'package'`. */
export interface NodePackageMeta {
  packageId: string;
  major: number;
  version: string;
  /** From manifest `name` — human-readable package title for palette / hub UI. */
  name?: string;
  publisher?: string;
  /** Package-relative path to the optional starter source file (any extension). */
  source?: string;
  lineage?: NodePackageLineage;
  /** When true, the package rejects factory-install / Save-As writes (manifest `readOnly`). */
  readOnly?: boolean;
  /** Canonical creation instant from manifest `createdAt`. */
  createdAt?: string;
  /** Parsed ``createdAt`` for ordering (palette + Nodes Hub). */
  createdAtMs?: number;
  /** From API: filesystem mtime of ``manifest.json`` (informational only). */
  installUpdatedAtMs?: number;
}

export interface PortDef {
  types: SupportedType[];
  cardinality?: '0' | '1' | 'n' | '[0,1]' | '[1,n]' | '[1,2]' | '2';
}

export type EditorType = 'code' | 'widgets' | 'grammar' | 'none';
export type NodeCategory = 'data' | 'computation' | 'vis_grammar' | 'vis_simple' | 'flow';

/* ── Handle configuration ──────────────────────────────────────────── */

export type TIconCardinality = "1" | "2" | "N";

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

/* ── NodeEditor configuration ──────────────────────────────────────── */

export interface EditorConfig {
  code: boolean;
  grammar: boolean;
  widgets: boolean;
  provenance?: boolean;
  disableWidgets?: boolean;
  /** DOM id for the editor output container (e.g. "vega" + nodeId). */
  outputId?: (nodeId: string) => string;
}

/* ── NodeContainer overrides ───────────────────────────────────────── */

export interface ContainerConfig {
  handleType?: 'in' | 'out' | 'in/out';
  disablePlay?: boolean;
  noContent?: boolean;
  nodeWidth?: number;
  nodeHeight?: number;
  styles?: React.CSSProperties;
}

/* ── Node Lifecycle Contract ───────────────────────────────────────── */

export type UseNodeStateReturn = ReturnType<typeof import('../hook/useNodeState').useNodeState>;

/**
 * Runtime data passed to every lifecycle hook by UniversalNode.
 *
 * Extends the persisted `INodeData` with FlowProvider runtime callbacks
 * that are injected when the node is mounted on the canvas.
 */
export interface NodeLifecycleData extends INodeData {
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
 * Every field is optional. UniversalNode applies defaults from `useNodeState`
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
  /** Replace the `setSendCodeCallback` wiring between NodeEditor and the play button. */
  setSendCodeCallbackOverride?: any;
  /** When `true`, NodeContainer shows a loading spinner instead of the play button. */
  showLoading?: boolean;
  /** Custom React subtree rendered inside the NodeEditor content area. */
  contentComponent?: React.ReactNode;
  /** Replace `nodeState.setOutput` — used when output state is managed locally (DataPool, MergeFlow). */
  setOutputCallbackOverride?: any;
  outputOverride?: ICodeData;
  /** Extra handles appended to `adapter.handles` at render time (MergeFlow dynamic inputs). */
  dynamicHandles?: HandleDef[];
  /** When `true`, the play button is disabled. */
  disablePlay?: boolean;
  /**
   * DOM id for the editor's output container, computed at lifecycle time.
   * Replaces the static `adapter.editor.outputId(nodeId)` form so a manifest
   * can declare a grammar-mode kind without carrying executable JS — the
   * lifecycle hook owns the convention (e.g. Vega uses `"vega" + nodeId`).
   */
  outputIdOverride?: string;
}

/**
 * Contract type for node lifecycle hooks.
 *
 * Every lifecycle implementation **must** satisfy this signature.
 * The hook is called by `UniversalNode` on every render — it receives
 * the node's runtime `data` and the shared `nodeState` from `useNodeState`,
 * and returns a `LifecycleResult` whose fields selectively override
 * defaults.
 *
 * **Rules:**
 * 1. Must be a valid React custom hook (may call `useState`, `useEffect`, etc.).
 * 2. Must be deterministic in its hook call order (React rules of hooks).
 * 3. Must return a `LifecycleResult` — omit fields to accept defaults.
 * 4. Must not call `nodeState.setSendCodeCallback` directly — return
 *    `setSendCodeCallbackOverride` instead so UniversalNode can wire it.
 */
export type NodeLifecycleHook = (data: NodeLifecycleData, nodeState: UseNodeStateReturn) => LifecycleResult;

/* ── Full adapter for a node type ──────────────────────────────────── */

export interface NodeAdapter {
  handles: HandleDef[];
  editor: EditorConfig | null;
  container: ContainerConfig;
  inputIconType?: string;
  outputIconType?: string;
  useLifecycle: NodeLifecycleHook;
}

/* ── Descriptor ────────────────────────────────────────────────────── */

export interface NodeDescriptor {
  /**
   * Dispatch key. Either a built-in `NodeType` enum value (default) or a
   * package canonical id `<packageId>/<templateId>@<major>` for package-registered kinds.
   */
  id: NodeTemplateId;
  category: NodeCategory;
  label: string;
  icon: IconDefinition;
  inputPorts: PortDef[];
  outputPorts: PortDef[];
  editor: EditorType;
  grammarId?: string;
  inPalette: boolean;
  paletteOrder?: number;
  /** Optional small label rendered as a badge over the icon in ToolsMenu (e.g. "AUTK", "Vega-Lite"). */
  badge?: string;
  description: string;
  hasCode: boolean;
  hasWidgets: boolean;
  hasGrammar: boolean;
  hasProvenance?: boolean;
  adapter: NodeAdapter;
  tutorialId?: string;
  /**
   * Origin of the descriptor. Omitted = `'core'` for backwards compatibility
   * with the built-in registrations in `registry/descriptors.ts`.
   */
  source?: NodeSource;
  /** Set when `source === 'package'`; metadata threaded through from the package manifest. */
  package?: NodePackageMeta;
}
