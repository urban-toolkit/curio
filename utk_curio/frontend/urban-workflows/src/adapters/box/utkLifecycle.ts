import { BoxLifecycleHook } from '../../registry/types';
import { useUTK } from '../../hook/useUTK';

export const useUtkLifecycle: BoxLifecycleHook = (data, boxState) => {
  const {
    sendCode,
    defaultGrammar,
    showLoading,
    setSendCodeCallback,
    customWidgetsCallback,
    handleCompileGrammar,
    setOutput,
    output
  } = useUTK({ data: { ...data }, code: boxState.code });

  const applyGrammar = async (spec: string) => {
    try {
      setOutput({ code: 'exec', content: ''});
      await handleCompileGrammar(spec);
      setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      setOutput({ code: 'error', content: error.message, outputType: '' });
    }
  };

  const defaultValueOverride =
    boxState.templateData.code == undefined
      ? data.defaultCode
        ? data.defaultCode
        : defaultGrammar
      : boxState.templateData.code;

  return {
    applyGrammar,
    sendCodeOverride: sendCode,
    setSendCodeCallbackOverride: setSendCodeCallback,
    showLoading,
    customWidgetsCallback,
    defaultValueOverride,
    setOutputCallbackOverride: setOutput,
    outputOverride: output
  };
}
