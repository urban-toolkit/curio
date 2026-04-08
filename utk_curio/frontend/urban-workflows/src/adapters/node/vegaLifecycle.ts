import { NodeLifecycleHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';

export const useVegaLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const { handleCompileGrammar } = useVega({ data, code: nodeState.code });

  const applyGrammar = async (spec: string) => {
    try {
      await handleCompileGrammar(spec);
      nodeState.setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      alert(error.message);
    }
  };

  return { applyGrammar };
}
