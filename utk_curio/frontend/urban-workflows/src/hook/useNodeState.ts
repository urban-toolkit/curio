import { useState, useEffect } from 'react';
import { NodeType } from '../constants';
import { NodeTemplateId } from '../registry/types';
import { ICodeDataContent } from '../types';
import { Starter, useStarterContext } from '../providers/StarterProvider';
import { useUserContext } from '../providers/UserProvider';

export interface NodeOutput {
  code: string;
  content: ICodeDataContent | string;
  outputType?: string;
}

export function useNodeState(data: any, nodeType: NodeTemplateId) {
  const [output, setOutput] = useState<NodeOutput>(data.output ?? { code: '', content: '', outputType: '' });
  const [code, setCode] = useState<string>(data.code ?? '');
  const [sendCode, setSendCode] = useState<any>();
  const [templateData, setTemplateData] = useState<Starter | any>({});
  const [newTemplateFlag, setNewTemplateFlag] = useState(false);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showDescriptionModal, setShowDescriptionModal] = useState(false);

  const { editUserStarter } = useStarterContext();
  const { user } = useUserContext();

  useEffect(() => { data.code = code; }, [code]);

  // Mirrored by direct mutation rather than setNodes, deliberately: a setNodes
  // per keystroke re-rendered the whole canvas (dev/70). reactFlow.getNodes()
  // still sees these, which is what lets playNodesUpTo read them.
  //
  // `executedCode` records the source that produced the current successful
  // output, so playNodesUpTo can tell a cached result apart from a stale one.
  // A comparison rather than a dirty flag on purpose: Curio's Monaco editors are
  // uncontrolled and useMonacoExternalValue applies external content with
  // executeEdits, so a project load or an agent write re-enters the change
  // handler in a real browser - a flag set there would mark every node dirty
  // straight after a load, while identical content compares equal.
  useEffect(() => {
    data.output = output;
    if (output?.code === 'success') data.executedCode = code;
  }, [output]);

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

  const setTemplateConfig = (template: Starter) => setTemplateData({ ...template });

  const promptModal = (newTemplate: boolean = false) => {
    setNewTemplateFlag(newTemplate);
    setShowTemplateModal(true);
  };

  const closeModal = () => setShowTemplateModal(false);
  const promptDescription = () => setShowDescriptionModal(true);
  const closeDescription = () => setShowDescriptionModal(false);

  const updateTemplate = (template: Starter) => {
    setTemplateConfig(template);
    editUserStarter(template);
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
    // dev/90 A15: per-instance appearance for presentation behaviors —
    // mirrors the canonical data.appearance (generated bundles read it here).
    appearance: data?.appearance,
  };
}
