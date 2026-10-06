import React, { useEffect, useRef, useSyncExternalStore } from 'react';
import CSS from "csstype";
import { Handle, Edge, Position, useEdges, useUpdateNodeInternals } from 'reactflow';
import { useNotebookViewContext } from '../providers/flow/notebookViewContext';
import {
  NOTEBOOK_CELL_HEIGHT,
  NOTEBOOK_CELL_WIDTH,
  notebookHandleOffsets,
  notebookInputLabel,
} from '../utils/notebookLayout';
import { resolveNodeDisplayLabel } from '../utils/palettePackageFactoryDraft';
import { withInputCircles } from '../adapters/node/handleHelpers';
import { growsInputCircles, inputCapacity, wiredInputSlots } from '../utils/inputSlots';
import { NodeContainer } from './styles';
import NodeEditor from './editing/NodeEditor';
import DescriptionModal from './DescriptionModal';
import { OutputIcon } from './edges/OutputIcon';
import { InputIcon } from './edges/InputIcon';
import { getNodeDescriptor, tryGetNodeDescriptor, subscribeToRegistry } from '../registry/nodeRegistry';
import { isRegistryReady, subscribeToRegistryReady } from '../registry/registryReadiness';
import { UnresolvedNode } from './UnresolvedNode';
import { behaviorDataView } from "../utils/behaviorDataView";
import { isSelectionEcho } from "../utils/selectionEcho";
import { detectWebGpuSupport } from "../utils/webgpuSupport";
import { readCanvasTemplateConfig, resolveEditorTabFlags } from '../utils/canvasTemplateConfig';
import { useNodeState } from '../hook/useNodeState';
import { classifyAutkSpecString } from '../utils/autkSpecKind';
import { unversionedNodeType } from '../utils/flowNodeCanonicalType';
import { hasIncomingEdge, upstreamErroredMessage } from '../utils/nodeEmptyState';
import { isEmptySpecBuffer } from '../utils/starterSpec';
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
import { NodeOutcomeStrip } from './nodes/NodeOutcomeStrip';
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

  // A template with one input port that takes several edges grows a circle
  // per edge (utils/inputSlots). React Flow is told when the circles change,
  // or an edge to a new circle would have nothing to attach to.
  const growsCircles = !behavior.handlesOverride && growsInputCircles(descriptor.inputPorts);
  const wiredSlots = growsCircles ? wiredInputSlots(edges, data.nodeId) : [];
  const baseHandles = growsCircles
    ? withInputCircles(adapter.handles, wiredSlots, inputCapacity(descriptor.inputPorts))
    : adapter.handles;
  const circleIds = baseHandles.map((h) => h.id).join(",");
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    if (growsCircles) updateNodeInternals(data.nodeId);
  }, [circleIds]);

  const sendCode = behavior.sendCodeOverride ?? nodeState.sendCode;
  const setSendCodeCallback = behavior.setSendCodeCallbackOverride ?? nodeState.setSendCodeCallback;
  const setOutputCallback = behavior.setOutputCallbackOverride ?? nodeState.setOutput;
  const output = behavior.outputOverride ?? nodeState.output
  const showLoading = behavior.showLoading ?? false;
  const disablePlay = behavior.disablePlay ?? adapter.container.disablePlay ?? false;

  const { signalNodeExecDone, dashboardOn, projectId, edges: flowEdges, isRunActive, serverRunActive, nodes: flowNodes } = useFlowContext();
  // In the notebook view the node is a cell: a fixed size, its dots on the
  // right edge where the bar draws its connections, no cardinality markers.
  const notebook = useNotebookViewContext();
  const notebookOn = notebook.on && !dashboardOn;
  const cellHeight = notebook.heights.get(data.nodeId) ?? NOTEBOOK_CELL_HEIGHT;
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

  // A run that stopped above this node: a node feeding it failed, so the run
  // never triggered it (#603). It shows the reason as its outcome rather than
  // keeping the output of an earlier run as if it had just run. The Data Pool
  // owns the output it shows and says the same thing in its own empty state.
  const lastSkipExecRef = useRef<number>(data.skipExec ?? 0);
  useEffect(() => {
    const current = data.skipExec ?? 0;
    if (current <= lastSkipExecRef.current) return;
    lastSkipExecRef.current = current;
    if (behavior.outputOverride) return;
    nodeState.setOutput({
      code: "error",
      content: data.skipReason || upstreamErroredMessage(),
    });
  }, [data.skipExec]);

  // A step of a run on the server (useServerRun): running, its outcome, or
  // stopped. Shown through the setter the node's own run uses, so the node
  // reads, reports and records it the same way. `onlyIfRunning` gives a played
  // node back its earlier output only if its own play showed nothing.
  const lastServerOutputRef = useRef<number>(data.serverOutput?.seq ?? 0);
  useEffect(() => {
    const next = data.serverOutput;
    if (!next || next.seq <= lastServerOutputRef.current) return;
    lastServerOutputRef.current = next.seq;
    if (next.onlyIfRunning && output?.code !== "exec") return;
    setOutputCallback(next.output);
  }, [data.serverOutput]);

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
  // The spec the node was written with: loaded, dropped or put in by an agent.
  // The buffer above can read empty for a moment when it is not (see below).
  const writtenSpecIsEmpty = isEmptySpecBuffer(data.defaultCode);
  // Vega compiles its spec against the rows its input names, so a restored input
  // is all it needs - on the canvas as much as on the dashboard. Keyed on the
  // input so a chart behind a Data Pool draws when the pool's fetch lands, and
  // guarded so the same input never recompiles twice.
  // Never while a run is in flight: the runner compiles this node itself, and
  // two ``sendCode`` calls in one tick cancel each other. Each one toggles the
  // widgets pass, so two toggles in the same batch leave the flag where it
  // started, the marker round trip never happens, and the node sits at "exec"
  // until its watchdog. Whatever a run leaves behind is what this draws from
  // the next time an input arrives. A run on the server counts too: its
  // browser part compiles the maps and charts it walks as Run All does, and a
  // chart it leaves out draws here once the run ends, from the input that
  // arrived during it.
  const runInFlight = !!isRunActive || !!serverRunActive;
  const runInFlightRef = useRef(runInFlight);
  runInFlightRef.current = runInFlight;
  // The grammar nodes that draw from their input on their own, by one rule: a
  // Vega chart, and an Autark document that renders (a map or a plot). An
  // Autark data or compute step stays on Play.
  const autarkRender = kind === NodeType.AUTK_GRAMMAR && classifyAutkSpecString(nodeState.code) === "render";
  const drawsFromInput = kind === NodeType.VIS_VEGA || autarkRender;
  useEffect(() => {
    if (kind !== NodeType.VIS_VEGA && kind !== NodeType.AUTK_GRAMMAR) return;
    // An input that lands while the buffer is still empty belongs to a node
    // somebody is wiring up right now: `vegaBehavior` fetches a preview and
    // fills the buffer with a spec guessed from that input's columns a moment
    // later. Drawing the guess would run the node on connect and pull its
    // editor to the output pane while the author is still typing into it, which
    // is not what a restore is for. A reload looks like this for a moment, so
    // the node's written spec decides, not the buffer: the editor mounts on
    // `{}` and floats it into the buffer until Monaco loads and applies the
    // saved spec, and a restored input lands in that window (#711). Canvas
    // only: a pinned tile always opens with its spec already loaded, and the
    // dashboard has no author to interrupt.
    if (!dashboardOn && hasInput && specIsEmpty && writtenSpecIsEmpty) {
      starterFillInputRef.current = data.input;
    }
    // Recorded above for either grammar, even before an empty Autark editor can
    // say whether it renders: the starter it is about to receive does.
    if (!drawsFromInput) return;
    if (!sendCode || disablePlay || specIsEmpty) return;
    if (runInFlight || output?.code === "exec") return;
    if (!hasInput) return;
    // A selection coming back through a Data Pool: the same rows with new
    // `interacted` flags, which useVega's hot reload sets on the rows the view
    // already holds. Rebuilding the chart would throw its own selection away.
    if (isSelectionEcho(data.input)) return;
    if (starterFillInputRef.current === data.input) return;
    if (lastRenderedInputRef.current === data.input) return;
    lastRenderedInputRef.current = data.input;
    const code = nodeState.code;
    if (!autarkRender) {
      setOutputCallback({ code: "exec", content: "" });
      sendCode(code);
      return;
    }
    // An Autark map needs WebGPU. Without it, opening a project must not raise
    // one error per map: the node keeps its "not drawn yet" body, and a Play
    // shows the in-node explanation. The probe is async, so the run state is
    // read again once it answers.
    void detectWebGpuSupport().then((support) => {
      if (!support.supported) return;
      if (runInFlightRef.current || outputCodeRef.current === "exec") return;
      setOutputCallback({ code: "exec", content: "" });
      sendCode(code);
    });
  }, [kind, drawsFromInput, autarkRender, sendCode, disablePlay, specIsEmpty, writtenSpecIsEmpty, hasInput, data.input, runInFlight, dashboardOn]);

  // A wired Autark render tile draws by the rule above when its input lands. An
  // unwired one never receives an input, so it is drawn once here, on the
  // dashboard: its document loads everything it draws. Its upstream data and
  // compute nodes are not run - their layers come from the Data Catalog.
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
    if (connected) return;
    autoRenderedRef.current = true;
    setOutputCallback({ code: "exec", content: "" });
    sendCode(nodeState.code);
  }, [isPinnedAutarkTile, sendCode, disablePlay, specIsEmpty, connected, hasInput, runInFlight]);

  useEffect(() => {
    outputCodeRef.current = output?.code;
    if (output?.code === "error" || output?.code === "success") {
      // A failure stops the run below this node (#603).
      signalNodeExecDone(data.nodeId, { failed: output.code === "error" });
      if (collab.enabled && output) {
        collab.broadcastOutputProduced({
          nodeId: data.nodeId,
          nodeType: data.nodeType,
          output: output as { code: string; content: unknown },
        });
      }
    }
    // Keyed on the OBJECT, not `output?.code`: a node that errors twice in a
    // row (e.g. a node re-triggered by Play with inputs still missing) keeps
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
    ?? [...baseHandles, ...(behavior.dynamicHandles ?? [])];
  const notebookOffsets = notebookOn
    ? notebookHandleOffsets(allHandles.map((h: HandleDef) => ({ id: h.id, type: h.type })), cellHeight)
    : null;

  /** What a dot in the notebook's bar says on hover: which input it is and what feeds it. */
  const notebookDotTitle = (h: HandleDef): string => {
    if (h.id === 'in/out') return 'interaction';
    if (h.type === 'source') return 'output';
    const edge = edges.find((e: Edge) => e.target === data.nodeId && (e.targetHandle ?? 'in') === h.id);
    const source = edge ? (flowNodes ?? []).find((n: any) => n.id === edge.source) : undefined;
    let name: string | null = null;
    try {
      name = source ? resolveNodeDisplayLabel(source.data) || null : null;
    } catch {
      name = null;
    }
    const input = `input ${notebookInputLabel(h.id)}`;
    return name ? `${input} · ${name}` : input;
  };

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
        if (notebookOffsets) {
          // Every dot on the right edge, inputs numbered as the chips count them.
          const label = h.type === 'target' && h.id !== 'in/out' ? notebookInputLabel(h.id) : '';
          return (
            <Handle
              key={h.id}
              id={h.id}
              type={h.type}
              position={Position.Right}
              isConnectable={connectable}
              style={{ ...(style ?? {}), top: notebookOffsets.get(h.id) }}
              title={notebookDotTitle(h)}
              className="curio-notebook-dot"
            >
              {label.length > 0 && label.length <= 2 ? (
                <span className="curio-notebook-dot-label">{label}</span>
              ) : null}
            </Handle>
          );
        }
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
        // A notebook cell has the column's fixed size, passed on its own: the
        // node's size props stay its canvas size, so the node keeps that size
        // when the canvas comes back, and like a tile a cell never writes its
        // size into the node.
        cellBox={notebookOn ? { width: NOTEBOOK_CELL_WIDTH, height: cellHeight } : undefined}
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
        {!dashboardOn && !notebookOn && adapter.inputIconType && <InputIcon type={adapter.inputIconType as TIconCardinality} />}

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
          // output tab. ``noContent`` containers
          // legitimately return ``undefined`` here — they're icon-only.
          behavior.contentComponent ?? null
        )}
        </ErrorBoundary>

        {/* dev/138: the node carries its own reason. A toast fades and a code
            node's traceback lives in its output area, but a grammar or
            presentation node had no surface at all — so a failed render was a
            red word with no text. Outside the boundary on purpose: a node whose
            content subtree crashed is exactly the one that must still say why. */}
        {!dashboardOn && (
          <NodeOutcomeStrip
            nodeId={data.nodeId}
            projectId={projectId}
            output={output}
          />
        )}

        {!dashboardOn && !notebookOn && adapter.outputIconType && <OutputIcon type={adapter.outputIconType as TIconCardinality} />}
      </NodeContainer>

      {/* Agents attached to this node render as avatars at its bottom edge. */}
      {!dashboardOn && <NodeAgentBadges nodeId={data.nodeId} />}
    </div>
  );
});

export default UniversalNode;
