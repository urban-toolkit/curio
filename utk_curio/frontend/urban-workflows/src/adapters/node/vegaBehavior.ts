import { useEffect, useRef, useState } from 'react';
import { useEdges } from 'reactflow';

import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchPreviewData } from '../../services/api';
import { emptyRenderKind, renderOutcome } from '../../utils/renderOutcome';
import { hasIncomingEdge } from '../../utils/nodeEmptyState';
import { defaultSpecText, isEmptySpecBuffer } from '../../utils/vegaDefaultSpec';
import { activeGeometryName } from '../../utils/parsing';
import { toRows } from '../../utils/rowSource';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const edges = useEdges();
  const connected = hasIncomingEdge(edges, data.nodeId);

  // A starter spec chosen from the arriving input's column types.
  //
  // Deliberately narrow: it fills only a buffer that is still empty, and only
  // once per node per session. `useMonacoExternalValue` no-ops when the value
  // is unchanged, so re-asserting it is safe for the cursor and undo stack, but
  // that is not licence to re-assert it over something the user has typed.
  const [generatedSpec, setGeneratedSpec] = useState<string | null>(null);
  const hasAutoFilledRef = useRef(false);

  const currentBuffer = data.defaultCode ?? nodeState.templateData.code;
  const bufferIsEmpty = isEmptySpecBuffer(currentBuffer) && generatedSpec == null;

  const { handleCompileGrammar } = useVega({
    data,
    code: nodeState.code,
    connected,
    hasSpec: !isEmptySpecBuffer(generatedSpec ?? currentBuffer),
  });

  useEffect(() => {
    if (hasAutoFilledRef.current) return;
    if (!bufferIsEmpty) return;

    const input = data.input;
    // An edge alone carries no schema. `data.input` is set only once an
    // upstream node has actually produced output (or a saved workflow replayed
    // one), which is exactly when the column types become knowable.
    if (input == null || input === '') return;

    let cancelled = false;

    const fill = async () => {
      // Whatever arrives is parseOutput's envelope, `{ dataType, data, schema }`,
      // with the column dtypes BESIDE `data`, not inside it. In the app an input
      // is an artifact reference (`{ path, dataType }`, see normalizeFlowInput),
      // so the envelope is the /get-preview response; only merge bundles and
      // Data Pool layers arrive inline.
      let envelope: any = input;
      if (input.path) {
        // /get-preview returns 100 rows, which is cheaper than /get and plenty
        // for classifying columns.
        envelope = await fetchPreviewData(input.path);
      }
      if (cancelled || envelope == null) return;
      const payload: any = envelope.data;
      if (payload == null) return;

      const isGeo = (envelope.dataType ?? input.dataType) === 'geodataframe';
      // The schema comes off the envelope. Reading it off the payload was a bug:
      // a FeatureCollection carries none, so the classifier fell back to the
      // feature properties, which never list the active geometry column, and a
      // GeoDataFrame of string attributes came out as a bar of counts.
      const schema = envelope.schema ?? payload.schema ?? input.schema ?? null;
      const geometryName = isGeo ? activeGeometryName(payload) : null;
      const rows = isGeo
        ? (payload.features ?? []).map((f: any) => f?.properties ?? {})
        : rowsFromColumns(payload);

      const text = defaultSpecText(schema, rows, geometryName);
      if (!cancelled && text) {
        hasAutoFilledRef.current = true;
        setGeneratedSpec(text);
      }
    };

    fill().catch(() => {
      // A default is a convenience. Failing to pick one leaves the editor
      // empty, which is the honest state anyway.
    });

    return () => {
      cancelled = true;
    };
  }, [data.input, bufferIsEmpty]);

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
  return {
    applyGrammar,
    outputIdOverride: 'vega' + data.nodeId,
    // Only ever offered for an empty buffer, so it cannot displace real work.
    defaultValueOverride: generatedSpec ?? undefined,
  };
};

/** Column-oriented dataframe payload -> row records, for classification. */
function rowsFromColumns(payload: any): any[] {
  // Fifth copy of the same flatten, now utils/rowSource. Eager: these rows go
  // to vega-lite's `values`, which wants a real array.
  return toRows({ data: payload });
}
