import { useState, useEffect } from 'react';
import { BoxType } from '../constants';
import { Template, useTemplateContext } from '../providers/TemplateProvider';
import { useUserContext } from '../providers/UserProvider';

// Module-level registry: nodeId → latest code, updated synchronously outside React's render cycle.
// getGraphState reads from here so snapshots always capture the most recent editor content
// regardless of React effect timing.
export const nodeCodeRegistry = new Map<string, string>();

export interface BoxOutput {
  code: string;
  content: string;
  outputType?: string;
}

export function useBoxState(data: any, boxType: BoxType) {
  const [output, setOutput] = useState<BoxOutput>({ code: '', content: '', outputType: '' });
  const [code, setCode] = useState<string>('');
  const [sendCode, setSendCode] = useState<any>();
  const [templateData, setTemplateData] = useState<Template | any>({});
  const [newTemplateFlag, setNewTemplateFlag] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setShowDescriptionModal] = useState(false);

  const { editUserTemplate } = useTemplateContext();
  const { user } = useUserContext();

  useEffect(() => {
    data.code = code;
    if (data.nodeId && code) {
      nodeCodeRegistry.set(data.nodeId, code);
    }
  }, [data, code]);

  useEffect(() => { data.output = output; }, [output]);

  useEffect(() => {
    if (data.templateId != undefined) {
      setTemplateData({
        id: data.templateId,
        type: boxType,
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
