import React from 'react';
import CSS from "csstype";
import { Handle, Edge, useEdges } from 'reactflow';
import { NodeContainer } from './styles';
import NodeEditor from './editing/NodeEditor';
import DescriptionModal from './DescriptionModal';
import TemplateModal from './TemplateModal';
import { OutputIcon } from './edges/OutputIcon';
import { InputIcon } from './edges/InputIcon';
import { getNodeDescriptor } from '../registry/nodeRegistry';
import { useNodeState } from '../hook/useNodeState';
import { HandleDef, TIconCardinality } from '../registry/types';
import './Node.css';
import 'bootstrap/dist/css/bootstrap.min.css';

function UniversalNode({ data, isConnectable }: { data: any; isConnectable: boolean }) {
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
  const defaultValue =
    lifecycle.defaultValueOverride ??
    (nodeState.templateData.code ? nodeState.templateData.code : data.defaultCode);
  const readOnly =
    nodeState.templateData.custom != undefined && nodeState.templateData.custom === false;

  const allHandles = [...adapter.handles, ...(lifecycle.dynamicHandles ?? [])];

  return (
    <>
      {allHandles.map((h: HandleDef) => {
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
        nodeWidth={adapter.container.nodeWidth}
        nodeHeight={adapter.container.nodeHeight}
        styles={adapter.container.styles as CSS.Properties<0 | (string & {}), string & {}> | undefined}
        disablePlay={disablePlay}
        output={output}
        templateData={nodeState.templateData}
        code={nodeState.code}
        user={nodeState.user}
        sendCodeToWidgets={sendCode}
        setOutputCallback={setOutputCallback}
        promptModal={adapter.showTemplateModal ? nodeState.promptModal : undefined}
        updateTemplate={adapter.showTemplateModal ? nodeState.updateTemplate : undefined}
        setTemplateConfig={adapter.showTemplateModal ? nodeState.setTemplateConfig : undefined}
        promptDescription={nodeState.promptDescription}
      >
        {adapter.inputIconType && <InputIcon type={adapter.inputIconType as TIconCardinality} />}

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

        {adapter.showTemplateModal && (
          <TemplateModal
            newTemplateFlag={nodeState.newTemplateFlag}
            templateId={nodeState.templateData.id}
            callBack={nodeState.setTemplateConfig}
            show={nodeState.showTemplateModal}
            handleClose={nodeState.closeModal}
            nodeType={descriptor.id}
            code={nodeState.code}
          />
        )}

        {adapter.editor && (
          <NodeEditor
            outputId={adapter.editor.outputId?.(data.nodeId)}
            setSendCodeCallback={setSendCodeCallback}
            code={adapter.editor.code}
            grammar={adapter.editor.grammar}
            widgets={adapter.editor.widgets}
            provenance={adapter.editor.provenance}
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

        {adapter.outputIconType && <OutputIcon type={adapter.outputIconType as TIconCardinality} />}
      </NodeContainer>
    </>
  );
}

export default UniversalNode;
