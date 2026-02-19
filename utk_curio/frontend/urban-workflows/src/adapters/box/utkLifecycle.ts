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
  } = useUTK({ data: { ...data }, code: boxState.code });

  const applyGrammar = async (spec: string) => {
    try {
      await handleCompileGrammar(spec);
      boxState.setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      boxState.setOutput({ code: 'error', content: error.message, outputType: '' });
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
  };
}
