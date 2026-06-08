import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useToastContext } from '../../providers/ToastProvider';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { handleCompileGrammar } = useVega({ data, code: nodeState.code });

  const applyGrammar = async (spec: string) => {
    try {
      await handleCompileGrammar(spec);
      nodeState.setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      showToast(error.message, 'error');
    }
  };

  // The DOM id useVega renders the compiled view into — pre-Phase-B this was
  // declared in `adapter.editor.outputId`, but the manifest can't carry a
  // function. We own the `"vega" + nodeId` convention here so UniversalNode
  // can mount the matching `<div id={outputIdOverride}>` container.
  return { applyGrammar, outputIdOverride: 'vega' + data.nodeId };
}
