
import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { useStarterSpec } from '../../hook/useStarterSpec';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { emptyRenderKind, renderOutcome } from '../../utils/renderOutcome';
import { defaultSpecText } from '../../utils/vegaDefaultSpec';
import { isEmptySpecBuffer } from '../../utils/starterSpec';
import { toRows } from '../../utils/rowSource';
import { resolveGeometryField } from '../../utils/geometryField';
import { readGrammarInput, type GrammarInput } from '../../utils/grammarInput';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { connected, upstreamErrored } = useGrammarInputState(data.nodeId);
  // A failed chart says so to the nodes it feeds, as a failed code node does.
  const { markNodeErrored } = useFlowContext() as { markNodeErrored?: (nodeId: string) => void };

  // A starter spec chosen from the arriving input's column types, the way
  // every grammar node fills an empty editor (hook/useStarterSpec).
  const generatedSpec = useStarterSpec({
    input: data.input,
    buffer: nodeState.code,
    written: data.defaultCode,
    read: readVegaPreview,
    choose: chooseVegaStarter,
  });

  const { handleCompileGrammar } = useVega({
    data,
    code: nodeState.code,
    connected,
    upstreamErrored,
    // What the editor holds now, typing included.
    hasSpec: !isEmptySpecBuffer(nodeState.code) || generatedSpec !== undefined,
  });

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
        nodeState.setOutput({
          code: 'error', content: outcome.message, outputType: '',
          // dev/136: the harness reads this rather than the prose — the
          // cause rides the kind, because the fix differs per cause.
          kind: emptyRenderKind(outcome.cause),
        } as any);
        showToast(outcome.message, 'error');
        markNodeErrored?.(data.nodeId);
        return;
      }
      nodeState.setOutput({ code: 'success', content: '', outputType: '' });
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      showToast(error.message, 'error');
      markNodeErrored?.(data.nodeId);
    }
  };

  // The DOM id useVega renders the compiled view into — pre-Phase-B this was
  // declared in `adapter.editor.outputId`, but the manifest can't carry a
  // function. We own the `"vega" + nodeId` convention here so UniversalNode
  // can mount the matching `<div id={outputIdOverride}>` container.
  return {
    applyGrammar,
    outputIdOverride: 'vega' + data.nodeId,
    // Only ever offered for an empty buffer, so it cannot displace real work.
    defaultValueOverride: generatedSpec,
  };
};

/** The input's 100-row preview: plenty for classifying columns, and cheaper than /get. */
function readVegaPreview(input: unknown): Promise<GrammarInput> {
  return readGrammarInput(input, { label: 'the 2D Plot (Vega-Lite)', preview: true });
}

/** The Vega-Lite ladder over the input's first frame (utils/vegaDefaultSpec). */
function chooseVegaStarter(read: GrammarInput): string | null {
  const frame = read.frames[0];
  if (!frame) return null;
  const geo = frame.dataType === 'geodataframe';
  // A FeatureCollection's properties never list its active geometry column,
  // which is why that column is named by the payload rather than found here.
  const rows = geo
    ? (frame.payload?.features ?? []).map((f: any) => f?.properties ?? {})
    : toRows({ data: frame.payload });
  // A DataFrame's geometry column is typed `str` or `object`, so it is found
  // by value, as the Autark node finds it.
  const geometryName = geo ? frame.geometryName : resolveGeometryField(rows, null).field;
  return defaultSpecText(frame.schema, rows, geometryName);
}
