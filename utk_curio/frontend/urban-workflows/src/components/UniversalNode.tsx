import React, { useEffect, useRef, useSyncExternalStore } from 'react';
import CSS from "csstype";
import { Handle, Edge, useEdges } from 'reactflow';
import { NodeContainer } from './styles';
import NodeEditor from './editing/NodeEditor';
import DescriptionModal from './DescriptionModal';
import { OutputIcon } from './edges/OutputIcon';
import { InputIcon } from './edges/InputIcon';
import { getNodeDescriptor, tryGetNodeDescriptor, subscribeToRegistry } from '../registry/nodeRegistry';
import { isRegistryReady, subscribeToRegistryReady } from '../registry/packageRegistryBootstrap';
import { UnresolvedNode } from './UnresolvedNode';
import { behaviorDataView } from "../utils/behaviorDataView";
import { isSelectionEcho } from "../utils/selectionEcho";
import { readCanvasTemplateConfig, resolveEditorTabFlags } from '../utils/canvasTemplateConfig';
import { useNodeState } from '../hook/useNodeState';
import { classifyAutkSpecString } from '../utils/autkSpecKind';
import { unversionedNodeType } from '../utils/flowNodeCanonicalType';
import { hasIncomingEdge } from '../utils/nodeEmptyState';
import { isEmptySpecBuffer } from '../utils/vegaDefaultSpec';
import {
  DASHBOARD_TILE_DEFAULT_HEIGHT,
  DASHBOARD_TILE_DEFAULT_WIDTH,
} from '../utils/dashboardLayout';
import { NodeType } from '../constants';
import { HandleDef, TIconCardinality } from '../registry/types';
import { useFlowContext } from '../providers/FlowProvider';
import { NodeAgentBadges } from './agents/attach/NodeAgentBadges';
import { useCollab } from '../providers/CollaborationProvider';
import ErrorBoundary from "./ErrorBoundary";
import './Node.css';
import 'bootstrap/dist/css/bootstrap.min.css';

// When the canvas node's `data.nodeType` changes (e.g. after Save-As rebinds
// the node to a new package kind), the descriptor's `useNodeBehavior` hook function
// can change. Calling a *different* hook at the same call site violates
// React's rules of hooks and corrupts the state slots ("baseQueue is undefined").
// Keying the inner body by `data.nodeType` forces an unmount/remount so the
// new hook chain starts fresh.
//
// The outer wrapper also gates on descriptor presence: a node imported from a
// saved dataflow can mount before its package's descriptor has finished
// registering (race against `refreshPackageRegistry` mid-`loadProject`). We
// render a placeholder until the registry catches up — `useSyncExternalStore`
// subscribes to registry mutations so the body remounts as soon as its
// descriptor lands.
//
// That wait is only right while the registry might still deliver. Once it has
// settled, a missing descriptor means no installed package provides this type,
// and continuing to say "Loading node…" is a lie the user cannot see past —
// which is exactly what the streetvision example showed, permanently (#233).
// `UnresolvedNode` tells the two apart, and renders handles either way so the
// edges touching it can still be drawn.
const UniversalNode = React.memo(function UniversalNode({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  // The snapshot must be stable when the descriptor exists so React doesn't
  // tear-and-rebuild on every keystroke; return the descriptor itself (or
  // null) and re-subscribe on every registry pulse.
  const descriptor = useSyncExternalStore(
    subscribeToRegistry,
    () => tryGetNodeDescriptor(data.nodeType) ?? null,
  );
  const registryReady = useSyncExternalStore(
    subscribeToRegistryReady,
    isRegistryReady,
    () => false,
  );
  if (!descriptor) {
    return (
      <UnresolvedNode
        nodeId={data.nodeId}
        nodeType={data.nodeType}
        registryReady={registryReady}
      />
    );
  }
  return <UniversalNodeBody key={data.nodeType} data={data} isConnectable={isConnectable} />;
});

const UniversalNodeBody = React.memo(function UniversalNodeBody({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  const descriptor = getNodeDescriptor(data.nodeType);
  const { adapter } = descriptor;

  const nodeState = useNodeState(data, descriptor.id);
  // dev/90 A15: behaviors read content as data.code OR data.content — hand
  // the hook the compat view (render-time only, never persisted).
  const behavior = adapter.useNodeBehavior(behaviorDataView(data), nodeState);
  const edges = useEdges();

  const sendCode = behavior.sendCodeOverride ?? nodeState.sendCode;
  const setSendCodeCallback = behavior.setSendCodeCallbackOverride ?? nodeState.setSendCodeCallback;
  const setOutputCallback = behavior.setOutputCallbackOverride ?? nodeState.setOutput;
  const output = behavior.outputOverride ?? nodeState.output
  const showLoading = behavior.showLoading ?? false;
  const disablePlay = behavior.disablePlay ?? adapter.container.disablePlay ?? false;

  const { signalNodeExecDone, dashboardOn, edges: flowEdges, isRunActive } = useFlowContext();
  const kindConfig = readCanvasTemplateConfig({ data });
  const editorTabs = resolveEditorTabFlags(descriptor, kindConfig);
  const collab = useCollab();
  const lastTriggerExecRef = useRef<number>(data.triggerExec ?? 0);
  // The input this node's content was last compiled against, by a run or by the
  // restore path below, so neither repeats the other's work.
  const lastRenderedInputRef = useRef<unknown>(undefined);
  // The input that reached this node while its spec buffer was still empty, so
  // the restore path can tell an authoring gesture from a reload. See below.
  const starterFillInputRef = useRef<unknown>(undefined);
  const outputCodeRef = useRef(output?.code);

  // Lock-on-focus / unlock-on-blur. Safe to call always: useCollab()
  // returns no-op handlers when collaboration is disabled.
  const handleNodeFocus = () => {
    if (collab.enabled) collab.lockNode(data.nodeId);
  };
  const handleNodeBlur = (e: React.FocusEvent<HTMLDivElement>) => {
    if (!collab.enabled) return;
    // Only release when focus leaves the entire node subtree — clicks
    // between buttons / handles inside the node shouldn't toggle the lock.
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    collab.unlockNode(data.nodeId);
  };

  // Peer lock detection. ``self`` lock is suppressed so the user sees no
  // chip over their own node.
  const lockInfo = collab.lockedNodes[data.nodeId];
  const lockedByOther = Boolean(
    lockInfo && (collab.currentUserId == null || lockInfo.user_id !== collab.currentUserId),
  );

  useEffect(() => {
    const current = data.triggerExec ?? 0;
    if (current <= lastTriggerExecRef.current) return;
    lastTriggerExecRef.current = current;
    if (disablePlay || !sendCode) {
      signalNodeExecDone(data.nodeId);
      return;
    }
    setOutputCallback({ code: "exec", content: "" });
    sendCode(nodeState.code);
    lastRenderedInputRef.current = data.input;
    if (collab.enabled) collab.signalExecDisplay(data.nodeId);
  }, [data.triggerExec]);

  // ── Drawing from a restored input, with no Play ──────────────────────────
  //
  // A grammar node only draws when something calls its ``applyGrammar``, which
  // until now only a Play did. That is the whole reason a reloaded chart used to
  // be an empty box, and it is fatal on the dashboard, which has no play button
  // at all. Both kinds are compiled the same way a Play compiles them (through
  // ``sendCode``, so the widgets pass still resolves its markers first) rather
  // than by reaching into the behaviours.
  //
  // What is deliberately NOT here: code nodes. Their pane shows the run's stdout,
  // which no saved dataset can restore, so running one would execute the user's
  // code because they opened a page.
  const kind = unversionedNodeType(String(data.nodeType ?? ""));
  const connected = hasIncomingEdge(flowEdges ?? edges, data.nodeId);
  const hasInput = data.input != null && data.input !== "";
  const specIsEmpty = isEmptySpecBuffer(nodeState.code);
  // Vega compiles its spec against the rows its input names, so a restored input
  // is all it needs - on the canvas as much as on the dashboard. Keyed on the
  // input so a chart behind a Data Pool draws when the pool's fetch lands, and
  // guarded so the same input never recompiles twice.
  // Never while a run is in flight: the runner compiles this node itself, and
  // two ``sendCode`` calls in one tick cancel each other. Each one toggles the
  // widgets pass, so two toggles in the same batch leave the flag where it
  // started, the marker round trip never happens, and the node sits at "exec"
  // until its watchdog. Whatever a run leaves behind is what this draws from
  // the next time an input arrives.
  const runInFlight = !!isRunActive;
  useEffect(() => {
    if (kind !== NodeType.VIS_VEGA) return;
    // An input that lands while the buffer is still empty belongs to a node
    // somebody is wiring up right now: `vegaBehavior` fetches a preview and
    // fills the buffer with a spec guessed from that input's columns a moment
    // later. Drawing the guess would run the node on connect and pull its
    // editor to the output pane while the author is still typing into it, which
    // is not what a restore is for. A reload never looks like this, because the
    // saved spec is in the buffer before the data is. Canvas only: a pinned
    // tile always opens with its spec already loaded, and the dashboard has no
    // author to interrupt.
    if (!dashboardOn && hasInput && specIsEmpty) {
      starterFillInputRef.current = data.input;
    }
    if (!sendCode || disablePlay || specIsEmpty) return;
    if (runInFlight || output?.code === "exec") return;
    if (!hasInput) return;
    // A selection coming back through a Data Pool: the same rows with new
    // `interacted` flags, which useVega's hot reload swaps into the view it
    // already has. Rebuilding the chart would throw its own selection away.
    if (isSelectionEcho(data.input)) return;
    if (starterFillInputRef.current === data.input) return;
    if (lastRenderedInputRef.current === data.input) return;
    lastRenderedInputRef.current = data.input;
    setOutputCallback({ code: "exec", content: "" });
    sendCode(nodeState.code);
  }, [kind, sendCode, disablePlay, specIsEmpty, hasInput, data.input, runInFlight, dashboardOn]);

  // An Autark tile is drawn once, and only on the dashboard. Its render spec
  // needs a WebGPU canvas, so this is real work rather than a recompile: the
  // page it is pinned to is the only place worth doing it, and only for the tile
  // itself. Its upstream data and compute nodes are not run - their layers come
  // from the Data Catalog, which is the point.
  const autoRenderedRef = useRef(false);
  const isPinnedAutarkTile =
    dashboardOn
    && kind === NodeType.AUTK_GRAMMAR
    && !!data.dashboardPinned
    && classifyAutkSpecString(nodeState.code) === "render";
  useEffect(() => {
    if (!isPinnedAutarkTile || autoRenderedRef.current) return;
    if (!sendCode || disablePlay || specIsEmpty) return;
    if (runInFlight || output?.code === "exec") return;
    // Wait for the input a wired tile needs; an unwired one has everything in
    // its own spec.
    if (connected && !hasInput) return;
    autoRenderedRef.current = true;
    setOutputCallback({ code: "exec", content: "" });
    sendCode(nodeState.code);
  }, [isPinnedAutarkTile, sendCode, disablePlay, specIsEmpty, connected, hasInput, runInFlight]);

  useEffect(() => {
    outputCodeRef.current = output?.code;
    if (output?.code === "error" || output?.code === "success") {
      signalNodeExecDone(data.nodeId);
      if (collab.enabled && output) {
        collab.broadcastOutputProduced({
          nodeId: data.nodeId,
          nodeType: data.nodeType,
          output: output as { code: string; content: unknown },
        });
      }
    }
    // Keyed on the OBJECT, not `output?.code`: a node that errors twice in a
    // row (e.g. a merge re-triggered by Play with inputs still missing) keeps
    // code === "error", and a code-keyed effect never re-fires — the run then
    // hangs on the stall watchdog. setOutput always produces a fresh object,
    // and signalNodeExecDone ignores nodes outside the active level, so
    // duplicate signals are harmless (dev/64).
  }, [output]);

  // Signal done on unmount if the node was still executing (e.g. deleted while running).
  useEffect(() => {
    return () => {
      if (outputCodeRef.current === "exec") {
        signalNodeExecDone(data.nodeId);
      }
    };
  }, []);
  // Prefer data.defaultCode (always up-to-date via updateDefaultCode / setNodes) over
  // the locally-cached templateData.code which is only initialised once when templateId
  // first appears and never re-synced.  This ensures that programmatic code updates
  // (e.g. dataset drag-and-drop, AI suggestions) are reflected in the Monaco editor.
  const defaultValue =
    behavior.defaultValueOverride ??
    data.defaultCode ??
    nodeState.templateData.code;
  const readOnly =
    nodeState.templateData.custom != undefined && nodeState.templateData.custom === false;

  const allHandles = behavior.handlesOverride
    ?? [...adapter.handles, ...(behavior.dynamicHandles ?? [])];

  return (
    // ``display: contents`` keeps the wrapper invisible to ReactFlow's
    // layout (handle positioning relies on ``.react-flow__node`` as the
    // anchor) while still catching React's bubbled focus/blur events.
    <div
      onFocus={handleNodeFocus}
      onBlur={handleNodeBlur}
      style={{ display: "contents" }}
    >
      {lockedByOther && (
        <div
          className="collab-lock-chip"
          title={`Editing: ${lockInfo?.name || lockInfo?.username}`}
          style={{
            position: "absolute",
            top: -8,
            right: -8,
            zIndex: 10,
            background: "#ff9800",
            color: "#fff",
            borderRadius: "50%",
            width: 22,
            height: 22,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 10,
            fontWeight: 700,
            boxShadow: "0 1px 3px rgba(0,0,0,0.35)",
            pointerEvents: "none",
          }}
        >
          {(lockInfo?.username || "?").slice(0, 2).toUpperCase()}
        </div>
      )}
      {!dashboardOn && allHandles.map((h: HandleDef) => {
        const connectable =
          h.isConnectableOverride
            ? h.isConnectableOverride(data, isConnectable, edges)
            : isConnectable;
        const style = h.dynamicStyle ? h.dynamicStyle(data, edges) : h.style;
        return (
          <Handle
            key={h.id}
            id={h.id}
            type={h.type}
            position={h.position}
            isConnectable={connectable}
            style={style}
          />
        );
      })}

      <NodeContainer
        nodeId={data.nodeId}
        data={data}
        handleType={adapter.container.handleType}
        isLoading={showLoading}
        noContent={adapter.container.noContent}
        // A tile keeps its own size, which the dashboard's resize handle writes
        // to ``dashboardWidth``/``dashboardHeight``. Read only here: writing the
        // canvas fields from the dashboard would persist tile geometry as the
        // node's size on the canvas (TrillGenerator saves those).
        //
        // An unsized tile falls back to the dashboard's own default rather than
        // to the node's canvas size. A node is sized to sit among many on a
        // canvas, and at that size a tile reads as a stray node rather than as
        // the content of the page. The page fits every tile to the window, so
        // the larger default costs nothing when several are pinned.
        nodeWidth={
          dashboardOn
            ? (data.dashboardWidth ?? DASHBOARD_TILE_DEFAULT_WIDTH)
            : (data.nodeWidth ?? adapter.container.nodeWidth)
        }
        nodeHeight={
          dashboardOn
            ? (data.dashboardHeight ?? DASHBOARD_TILE_DEFAULT_HEIGHT)
            : (data.nodeHeight ?? adapter.container.nodeHeight)
        }
        styles={adapter.container.styles as CSS.Properties<0 | (string & {}), string & {}> | undefined}
        disablePlay={disablePlay}
        output={output}
        templateData={nodeState.templateData}
        code={nodeState.code}
        user={nodeState.user}
        sendCodeToWidgets={sendCode}
        setOutputCallback={setOutputCallback}
        promptDescription={nodeState.promptDescription}
      >
        {!dashboardOn && adapter.inputIconType && <InputIcon type={adapter.inputIconType as TIconCardinality} />}

        <DescriptionModal
          nodeId={data.nodeId}
          nodeType={descriptor.id}
          name={nodeState.templateData.name}
          description={nodeState.templateData.description}
          accessLevel={nodeState.templateData.accessLevel}
          show={nodeState.showDescriptionModal}
          handleClose={nodeState.closeDescription}
          custom={nodeState.templateData.custom}
        />

        {/* Per-node blast radius (#201). A throw from one node's content used
            to unmount the whole React root - canvas, menus and every other
            node - leaving a blank page. Contained here, the rest of the
            dataflow keeps working and the broken node says so in place. */}
        <ErrorBoundary
          label={`node ${data.nodeId}`}
          // A render throw mid-run used to leave this node at "exec" for good:
          // the boundary swallows the subtree but UniversalNode stays mounted,
          // so neither the output watcher nor the unmount safety net fires and
          // the run is held until its ten-minute watchdog (#271).
          onError={(err) => setOutputCallback({ code: "error", content: err.message || "This node could not render." })}
        >
        {adapter.editor ? (
          <NodeEditor
            outputId={behavior.outputIdOverride ?? adapter.editor.outputId?.(data.nodeId)}
            setSendCodeCallback={setSendCodeCallback}
            code={editorTabs.code}
            grammar={editorTabs.grammar}
            widgets={editorTabs.widgets}
            provenance={editorTabs.provenance}
            disableWidgets={adapter.editor.disableWidgets}
            setOutputCallback={setOutputCallback}
            data={data}
            output={output}
            nodeType={descriptor.id}
            applyGrammar={behavior.applyGrammar}
            customWidgetsCallback={behavior.customWidgetsCallback}
            defaultValue={defaultValue}
            readOnly={readOnly || lockedByOther}
            floatCode={nodeState.setCode}
            contentComponent={behavior.contentComponent}
          />
        ) : (
          // ``editor: "none"`` in the manifest means there's no tabbed editor
          // surface — but the behavior hook can still inject custom UI via
          // ``contentComponent`` (the streetvision place-picker, etc.).
          // Without this branch that UI would be silently dropped because
          // ``contentComponent`` is otherwise only rendered inside NodeEditor's
          // output tab. ``noContent`` containers (merge-flow, spatial-join)
          // legitimately return ``undefined`` here — they're icon-only.
          behavior.contentComponent ?? null
        )}
        </ErrorBoundary>

        {!dashboardOn && adapter.outputIconType && <OutputIcon type={adapter.outputIconType as TIconCardinality} />}
      </NodeContainer>

      {/* Agents attached to this node render as avatars at its bottom edge. */}
      {!dashboardOn && <NodeAgentBadges nodeId={data.nodeId} />}
    </div>
  );
});

export default UniversalNode;
