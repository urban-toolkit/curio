import React, { useEffect, useRef, useSyncExternalStore } from 'react';
import CSS from "csstype";
import { Handle, Edge, useEdges } from 'reactflow';
import { NodeContainer } from './styles';
import NodeEditor from './editing/NodeEditor';
import DescriptionModal from './DescriptionModal';
import { OutputIcon } from './edges/OutputIcon';
import { InputIcon } from './edges/InputIcon';
import { getNodeDescriptor, tryGetNodeDescriptor, subscribeToRegistry } from '../registry/nodeRegistry';
import { readCanvasTemplateConfig, resolveEditorTabFlags } from '../utils/canvasTemplateConfig';
import { useNodeState } from '../hook/useNodeState';
import { HandleDef, TIconCardinality } from '../registry/types';
import { useFlowContext } from '../providers/FlowProvider';
import { useCollab } from '../providers/CollaborationProvider';
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
const UniversalNode = React.memo(function UniversalNode({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  // The snapshot must be stable when the descriptor exists so React doesn't
  // tear-and-rebuild on every keystroke; return the descriptor itself (or
  // null) and re-subscribe on every registry pulse.
  const descriptor = useSyncExternalStore(
    subscribeToRegistry,
    () => tryGetNodeDescriptor(data.nodeType) ?? null,
  );
  if (!descriptor) {
    return (
      <div
        style={{
          padding: '8px 12px', minWidth: 180, minHeight: 50,
          border: '1px dashed #b8b8b8', borderRadius: 6,
          background: '#fafafa', color: '#64748b', fontSize: 11,
          fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
        }}
        title={`Waiting on descriptor for ${data.nodeType}`}
      >
        <strong style={{ color: '#334155', fontSize: 12 }}>Loading node…</strong>
        <div style={{ marginTop: 4, opacity: 0.7 }}>{data.nodeType}</div>
      </div>
    );
  }
  return <UniversalNodeBody key={data.nodeType} data={data} isConnectable={isConnectable} />;
});

const UniversalNodeBody = React.memo(function UniversalNodeBody({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  const descriptor = getNodeDescriptor(data.nodeType);
  const { adapter } = descriptor;

  const nodeState = useNodeState(data, descriptor.id);
  const behavior = adapter.useNodeBehavior(data, nodeState);
  const edges = useEdges();

  const sendCode = behavior.sendCodeOverride ?? nodeState.sendCode;
  const setSendCodeCallback = behavior.setSendCodeCallbackOverride ?? nodeState.setSendCodeCallback;
  const setOutputCallback = behavior.setOutputCallbackOverride ?? nodeState.setOutput;
  const output = behavior.outputOverride ?? nodeState.output
  const showLoading = behavior.showLoading ?? false;
  const disablePlay = behavior.disablePlay ?? adapter.container.disablePlay ?? false;

  const { signalNodeExecDone, dashboardOn } = useFlowContext();
  const collab = useCollab();
  const lastTriggerExecRef = useRef<number>(data.triggerExec ?? 0);
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
    if (collab.enabled) collab.signalExecDisplay(data.nodeId);
  }, [data.triggerExec]);

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
  }, [output?.code]);

  // Signal done on unmount if the node was still executing (e.g. deleted while running).
  useEffect(() => {
    return () => {
      if (outputCodeRef.current === "exec") {
        signalNodeExecDone(data.nodeId);
      }
    };
  }, []);
  const defaultValue =
    behavior.defaultValueOverride ??
    (nodeState.templateData.code ? nodeState.templateData.code : data.defaultCode);
  const readOnly =
    nodeState.templateData.custom != undefined && nodeState.templateData.custom === false;

  const allHandles = behavior.handlesOverride
    ?? [...adapter.handles, ...(behavior.dynamicHandles ?? [])];
  const kindConfig = readCanvasTemplateConfig({ data });
  const editorTabs = resolveEditorTabFlags(descriptor, kindConfig);

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
        nodeWidth={data.nodeWidth ?? adapter.container.nodeWidth}
        nodeHeight={data.nodeHeight ?? adapter.container.nodeHeight}
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

        {adapter.editor ? (
          <NodeEditor
            outputId={behavior.outputIdOverride ?? adapter.editor.outputId?.(data.nodeId)}
            setSendCodeCallback={setSendCodeCallback}
            code={editorTabs.code}
            grammar={editorTabs.grammar}
            widgets={editorTabs.widgets}
            provenance={editorTabs.provenance}
            explanation={editorTabs.explanation}
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

        {!dashboardOn && adapter.outputIconType && <OutputIcon type={adapter.outputIconType as TIconCardinality} />}
      </NodeContainer>
    </div>
  );
});

export default UniversalNode;
