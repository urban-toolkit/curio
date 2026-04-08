import { NodeLifecycleHook } from '../../registry/types';
import { useUTK } from '../../hook/useUTK';

export const useUtkLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const {
    sendCode,
    defaultGrammar,
    showLoading,
    disablePlay,
    setSendCodeCallback,
    customWidgetsCallback,
    handleCompileGrammar,
    setOutput,
    output,
  } = useUTK({ data: { ...data }, code: nodeState.code });

  const applyGrammar = async (spec: string) => {
    try {
      // If the spec from the editor doesn't have 'grid', the generated grammar
      // hasn't propagated to the editor yet. Fall back to the latest defaultGrammar.
      let grammarToCompile = spec;
      try {
        const parsed = JSON.parse(spec);
        if (!parsed.grid && defaultGrammar !== '{}') {
          grammarToCompile = defaultGrammar;
        }
      } catch { /* not valid JSON, let compileGrammar handle it */ }

      setOutput({ code: 'exec', content: ''});
      await handleCompileGrammar(grammarToCompile);
      setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      setOutput({ code: 'error', content: error.message, outputType: '' });
    }
  };

  const defaultValueOverride =
    nodeState.templateData.code == undefined
      ? data.defaultCode
        ? data.defaultCode
        : defaultGrammar
      : nodeState.templateData.code;

  return {
    disablePlay,
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
