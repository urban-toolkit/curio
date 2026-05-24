import React, { useEffect, useRef } from 'react';
import CSS from "csstype";
import { Handle, Edge, useEdges } from 'reactflow';
import { NodeContainer } from './styles';
import NodeEditor from './editing/NodeEditor';
import DescriptionModal from './DescriptionModal';
import { OutputIcon } from './edges/OutputIcon';
import { InputIcon } from './edges/InputIcon';
import { getNodeDescriptor } from '../registry/nodeRegistry';
import { readCanvasKindConfig, resolveEditorTabFlags } from '../utils/canvasKindConfig';
import { useNodeState } from '../hook/useNodeState';
import { HandleDef, TIconCardinality } from '../registry/types';
import { useFlowContext } from '../providers/FlowProvider';
import './Node.css';
import 'bootstrap/dist/css/bootstrap.min.css';

// When the canvas node's `data.nodeType` changes (e.g. after Save-As rebinds
// the node to a new pack kind), the descriptor's `useLifecycle` hook function
// can change. Calling a *different* hook at the same call site violates
// React's rules of hooks and corrupts the state slots ("baseQueue is undefined").
// Keying the inner body by `data.nodeType` forces an unmount/remount so the
// new hook chain starts fresh.
const UniversalNode = React.memo(function UniversalNode({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  return <UniversalNodeBody key={data.nodeType} data={data} isConnectable={isConnectable} />;
});

const UniversalNodeBody = React.memo(function UniversalNodeBody({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  const descriptor = getNodeDescriptor(data.nodeType);
  const { adapter } = descriptor;

  const nodeState = useNodeState(data, descriptor.id);
  const lifecycle = adapter.useLifecycle(data, nodeState);
  const edges = useEdges();

  const sendCode = lifecycle.sendCodeOverride ?? nodeState.sendCode;
  const setSendCodeCallback = lifecycle.setSendCodeCallbackOverride ?? nodeState.setSendCodeCallback;
  const setOutputCallback = lifecycle.setOutputCallbackOverride ?? nodeState.setOutput;
  const output = lifecycle.outputOverride ?? nodeState.output
  const showLoading = lifecycle.showLoading ?? false;
  const disablePlay = lifecycle.disablePlay ?? adapter.container.disablePlay ?? false;

  const { signalNodeExecDone, dashboardOn } = useFlowContext();
  const lastTriggerExecRef = useRef<number>(data.triggerExec ?? 0);
  const outputCodeRef = useRef(output?.code);

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
  }, [data.triggerExec]);

  useEffect(() => {
    outputCodeRef.current = output?.code;
    if (output?.code === "error" || output?.code === "success") {
      signalNodeExecDone(data.nodeId);
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
    lifecycle.defaultValueOverride ??
    (nodeState.templateData.code ? nodeState.templateData.code : data.defaultCode);
  const readOnly =
    nodeState.templateData.custom != undefined && nodeState.templateData.custom === false;

  const allHandles = [...adapter.handles, ...(lifecycle.dynamicHandles ?? [])];
  const kindConfig = readCanvasKindConfig({ data });
  const editorTabs = resolveEditorTabFlags(descriptor, kindConfig);

  return (
    <>
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

        {adapter.editor && (
          <NodeEditor
            outputId={lifecycle.outputIdOverride ?? adapter.editor.outputId?.(data.nodeId)}
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
            applyGrammar={lifecycle.applyGrammar}
            customWidgetsCallback={lifecycle.customWidgetsCallback}
            defaultValue={defaultValue}
            readOnly={readOnly}
            floatCode={nodeState.setCode}
            contentComponent={lifecycle.contentComponent}
          />
        )}

        {!dashboardOn && adapter.outputIconType && <OutputIcon type={adapter.outputIconType as TIconCardinality} />}
      </NodeContainer>
    </>
  );
});

export default UniversalNode;
