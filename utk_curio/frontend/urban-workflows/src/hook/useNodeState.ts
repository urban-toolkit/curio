import { useState, useEffect } from 'react';
import { NodeType } from '../constants';
import { ICodeDataContent } from '../types';
import { Template, useTemplateContext } from '../providers/TemplateProvider';
import { useUserContext } from '../providers/UserProvider';

export interface NodeOutput {
  code: string;
  content: ICodeDataContent | string;
  outputType?: string;
}

export function useNodeState(data: any, nodeType: NodeType) {
  const [output, setOutput] = useState<NodeOutput>(data.output ?? { code: '', content: '', outputType: '' });
  const [code, setCode] = useState<string>(
    typeof data.code === 'string'
      ? data.code
      : typeof data.defaultCode === 'string'
        ? data.defaultCode
        : ''
  );
  const [sendCode, setSendCode] = useState<any>();
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [newTemplateFlag, setNewTemplateFlag] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setShowDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();

  useEffect(() => { data.output = output; }, [output]);

  // Reverse-sync: when collaboration updates node.data.output via setNodes, pull into local state
  useEffect(() => {
    if (data.output && data.output.content && data.output.content !== output.content) {
      setOutput(data.output);
    }
  }, [data.output?.content, data.output?.code]);

  // Reverse-sync: when collaboration updates node.data.code via setNodes, pull into local state
  useEffect(() => {
    if (data.code && data.code !== code) {
      setCode(data.code);
    }
  }, [data.code]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: nodeType,
        name: data.templateName,
        description: data.description,
        accessLevel: data.accessLevel,
        code: data.defaultCode,
        custom: data.customTemplate,
      });
    }
  }, [data.templateId]);

  const setTemplateConfig = (template: Template) => setTemplateData({ ...template });

  const promptModal = (newTemplate: boolean = false) => {
    setNewTemplateFlag(newTemplate);
    setShowTemplateModal(true);
  };

  const closeModal = () => setShowTemplateModal(false);
  const promptDescription = () => setShowDescriptionModal(true);
  const closeDescription = () => setShowDescriptionModal(false);

  const updateTemplate = (template: Template) => {
    setTemplateConfig(template);
    editUserTemplate(template);
  };

  const setSendCodeCallback = (_sendCode: any) => setSendCode(() => _sendCode);

  return {
    output, setOutput,
    code, setCode,
    sendCode,
    templateData, setTemplateData,
    newTemplateFlag,
    showTemplateModal,
    showDescriptionModal,
    user,
    setTemplateConfig,
    promptModal,
    closeModal,
    promptDescription,
    closeDescription,
    updateTemplate,
    setSendCodeCallback,
  };
}
