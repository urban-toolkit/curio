import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useToastContext } from '../../providers/ToastProvider';
import { renderOutcome } from '../../utils/renderOutcome';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { handleCompileGrammar } = useVega({ data, code: nodeState.code });

  const applyGrammar = async (spec: string) => {
    try {
      const counts = await handleCompileGrammar(spec);
      // dev/136: compiling is not drawing. A schema-valid spec over zero rows
      // renders its axes and nothing else, and a spec whose encoded field is
      // entirely null renders an empty panel — both used to land here as
      // `success`, so the node showed a green Done over a blank chart and
      // every agent reading the journal was told the node was fine.
      const outcome = renderOutcome(counts ?? {});
      if (outcome.empty) {
        nodeState.setOutput({ code: 'error', content: outcome.message, outputType: '' });
        showToast(outcome.message, 'error');
        return;
      }
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
