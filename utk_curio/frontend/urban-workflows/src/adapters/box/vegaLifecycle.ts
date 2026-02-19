import { BoxLifecycleHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';

export const useVegaLifecycle: BoxLifecycleHook = (data, boxState) => {
  const { handleCompileGrammar } = useVega({ data, code: boxState.code });

  const applyGrammar = async (spec: string) => {
    try {
      await handleCompileGrammar(spec);
      boxState.setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      boxState.setOutput({ code: 'error', content: error.message, outputType: '' });
      alert(error.message);
    }
  };

  return { applyGrammar };
}
