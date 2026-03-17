import React from 'react';
import CSS from "csstype";
import { Handle, Edge, useEdges } from 'reactflow';
import { BoxContainer } from './styles';
import BoxEditor from './editing/BoxEditor';
import DescriptionModal from './DescriptionModal';
import TemplateModal from './TemplateModal';
import { OutputIcon } from './edges/OutputIcon';
import { InputIcon } from './edges/InputIcon';
import { getNodeDescriptor } from '../registry/nodeRegistry';
import { useBoxState } from '../hook/useBoxState';
import { HandleDef, TIconCardinality } from '../registry/types';
import './Box.css';
import 'bootstrap/dist/css/bootstrap.min.css';

function UniversalBox({ data, isConnectable }: { data: any; isConnectable: boolean }) {
  const descriptor = getNodeDescriptor(data.nodeType);
  const { adapter } = descriptor;

  const boxState = useBoxState(data, descriptor.id);
  const lifecycle = adapter.useLifecycle(data, boxState);
  const edges = useEdges();

  const sendCode = lifecycle.sendCodeOverride ?? boxState.sendCode;
  const setSendCodeCallback = lifecycle.setSendCodeCallbackOverride ?? boxState.setSendCodeCallback;
  const setOutputCallback = lifecycle.setOutputCallbackOverride ?? boxState.setOutput;
  const output = lifecycle.outputOverride ?? boxState.output
  const showLoading = lifecycle.showLoading ?? false;
  const disablePlay = lifecycle.disablePlay ?? adapter.container.disablePlay ?? false;
  const defaultValue =
    lifecycle.defaultValueOverride ??
    (boxState.templateData.code ? boxState.templateData.code : data.defaultCode);
  const readOnly =
    boxState.templateData.custom != undefined && boxState.templateData.custom === false;

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

      <BoxContainer
        nodeId={data.nodeId}
        data={data}
        handleType={adapter.container.handleType}
        isLoading={showLoading}
        noContent={adapter.container.noContent}
        boxWidth={adapter.container.boxWidth}
        boxHeight={adapter.container.boxHeight}
        styles={adapter.container.styles as CSS.Properties<0 | (string & {}), string & {}> | undefined}
        disablePlay={disablePlay}
        output={output}
        templateData={boxState.templateData}
        code={boxState.code}
        user={boxState.user}
        sendCodeToWidgets={sendCode}
        setOutputCallback={setOutputCallback}
        promptModal={adapter.showTemplateModal ? boxState.promptModal : undefined}
        updateTemplate={adapter.showTemplateModal ? boxState.updateTemplate : undefined}
        setTemplateConfig={adapter.showTemplateModal ? boxState.setTemplateConfig : undefined}
        promptDescription={boxState.promptDescription}
      >
        {adapter.inputIconType && <InputIcon type={adapter.inputIconType as TIconCardinality} />}

        <DescriptionModal
          nodeId={data.nodeId}
          boxType={descriptor.id}
          name={boxState.templateData.name}
          description={boxState.templateData.description}
          accessLevel={boxState.templateData.accessLevel}
          show={boxState.showDescriptionModal}
          handleClose={boxState.closeDescription}
          custom={boxState.templateData.custom}
        />

        {adapter.showTemplateModal && (
          <TemplateModal
            newTemplateFlag={boxState.newTemplateFlag}
            templateId={boxState.templateData.id}
            callBack={boxState.setTemplateConfig}
            show={boxState.showTemplateModal}
            handleClose={boxState.closeModal}
            boxType={descriptor.id}
            code={boxState.code}
          />
        )}

        {adapter.editor && (
          <BoxEditor
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
            boxType={descriptor.id}
            applyGrammar={lifecycle.applyGrammar}
            customWidgetsCallback={lifecycle.customWidgetsCallback}
            defaultValue={defaultValue}
            readOnly={readOnly}
            floatCode={boxState.setCode}
            contentComponent={lifecycle.contentComponent}
          />
        )}

        {adapter.outputIconType && <OutputIcon type={adapter.outputIconType as TIconCardinality} />}
      </BoxContainer>
    </>
  );
}

export default UniversalBox;
