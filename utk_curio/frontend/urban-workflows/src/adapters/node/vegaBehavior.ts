import { useEffect, useRef, useState } from 'react';
import { useEdges } from 'reactflow';

import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchPreviewData } from '../../services/api';
import { hasIncomingEdge } from '../../utils/nodeEmptyState';
import { defaultSpecText, isEmptySpecBuffer } from '../../utils/vegaDefaultSpec';

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
      let payload: any = input.data;
      if (input.path) {
        // /get-preview returns 100 rows, which is cheaper than /get and plenty
        // for classifying columns.
        const preview = await fetchPreviewData(input.path);
        payload = preview?.data ?? preview;
      }
      if (cancelled || payload == null) return;

      const isGeo = input.dataType === 'geodataframe';
      const schema = payload.schema ?? input.schema ?? null;
      const geometryName = isGeo ? (payload.geometry_name ?? null) : null;
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
  return {
    applyGrammar,
    outputIdOverride: 'vega' + data.nodeId,
    // Only ever offered for an empty buffer, so it cannot displace real work.
    defaultValueOverride: generatedSpec ?? undefined,
  };
};

/** Column-oriented dataframe payload -> row records, for classification. */
function rowsFromColumns(payload: any): any[] {
  if (payload == null || typeof payload !== 'object') return [];
  const columns = Object.keys(payload);
  if (columns.length === 0) return [];

  const first = payload[columns[0]];
  const keys = Array.isArray(first)
    ? first.map((_: unknown, i: number) => i)
    : first && typeof first === 'object'
      ? Object.keys(first)
      : [];

  return keys.map((key: any) => {
    const row: any = {};
    for (const column of columns) {
      const values = payload[column];
      row[column] = Array.isArray(values) ? values[key] : values?.[key];
    }
    return row;
  });
}
