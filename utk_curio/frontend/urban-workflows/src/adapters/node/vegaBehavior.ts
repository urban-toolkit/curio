
import { NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { useStarterSpec } from '../../hook/useStarterSpec';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { emptyRenderKind, renderOutcome, type RenderCounts } from '../../utils/renderOutcome';
import { defaultSpecText } from '../../utils/vegaDefaultSpec';
import { isEmptySpecBuffer } from '../../utils/starterSpec';
import { toRows } from '../../utils/rowSource';
import { resolveGeometryField } from '../../utils/geometryField';
import { readGrammarInput, type GrammarInput, type GrammarFrame } from '../../utils/grammarInput';
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { compareInputs } from '../../utils/compare/compareInputs';
import type { Scenario } from '../../utils/scenarios/scenarioModel';
import {
  compareStarterSpec, isComparing, requiredColumns, scenarioRequirements, type ScenarioInput,
} from '../../utils/vegaCompare';
import { VegaCompareStrip } from '../../components/vega/VegaCompareStrip';

/** The red ring of a circle whose scenario lacks a column the spec reads. */
const MISSING_RING = '0 0 0 3px #c0392b';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { connected, upstreamErrored } = useGrammarInputState(data.nodeId);
  // A failed chart says so to the nodes it feeds, as a failed code node does.
  const flow = useFlowContext() as any;
  const markNodeErrored: ((nodeId: string) => void) | undefined = flow?.markNodeErrored;

  // Compare scenarios (utils/vegaCompare): each input circle is a scenario,
  // labelled by the scenario its node is in (utils/compare/compareInputs).
  const comparing = isComparing(data);
  const inputs: ScenarioInput[] = compareInputs(
    data.nodeId, flow?.nodes ?? [], flow?.edges ?? [], (flow?.scenarios ?? []) as Scenario[],
  ).map(({ slot, label }) => ({ slot, label }));
  const inputsKey = JSON.stringify(inputs);
  const scenarios = useMemo(() => (comparing ? inputs : null), [comparing, inputsKey]);
  const comparingRef = useRef(comparing);
  comparingRef.current = comparing;

  // A starter spec chosen from the arriving input's column types, the way
  // every grammar node fills an empty editor (hook/useStarterSpec).
  const generatedSpec = useStarterSpec({
    input: data.input,
    buffer: nodeState.code,
    written: data.defaultCode,
    read: readVegaPreview,
    choose: (read) => (comparingRef.current ? compareStarterSpec(firstNumberColumn(read.frames[0])) : chooseVegaStarter(read)),
  });

  // Each circle's columns, from the input's preview, for what a scenario lacks.
  const [columnsBySlot, setColumnsBySlot] = useState<Map<number, string[]>>(new Map());
  useEffect(() => {
    if (!comparing || data.input == null || data.input === '') {
      setColumnsBySlot(new Map());
      return;
    }
    let cancelled = false;
    readVegaPreview(data.input)
      .then((read) => {
        if (cancelled) return;
        const next = new Map<number, string[]>();
        for (const frame of read.frames) next.set(frame.circle, [...new Set([...(next.get(frame.circle) ?? []), ...frameColumns(frame)])]);
        setColumnsBySlot(next);
      })
      .catch(() => { if (!cancelled) setColumnsBySlot(new Map()); });
    return () => { cancelled = true; };
  }, [comparing, data.input]);

  // dev/136: compiling is not drawing. A schema-valid spec over zero rows
  // renders its axes and nothing else, and a spec whose encoded field is
  // entirely null renders an empty panel — both used to land as `success`, so
  // the node showed a green Done over a blank chart and every agent reading
  // the journal was told the node was fine. The same judgement for a chart's
  // first draw and for every redraw its new rows cause.
  const reportDrawn = (counts: RenderCounts | undefined) => {
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
  };

  const { handleCompileGrammar } = useVega({
    data,
    code: nodeState.code,
    connected,
    upstreamErrored,
    // What the editor holds now, typing included.
    hasSpec: !isEmptySpecBuffer(nodeState.code) || generatedSpec !== undefined,
    // A chart first drawn over zero rows said so; when its rows arrive and it
    // draws them, that has to be said too.
    onRedraw: reportDrawn,
    scenarios,
  });

  const applyGrammar = async (spec: string) => {
    try {
      reportDrawn(await handleCompileGrammar(spec));
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      showToast(error.message, 'error');
      markNodeErrored?.(data.nodeId);
    }
  };

  // Switching compare on or off, or a scenario's label changing, draws the
  // chart again over its new data.
  const drawnOnce = useRef(false);
  useEffect(() => {
    if (!drawnOnce.current) { drawnOnce.current = true; return; }
    if (data.input == null || data.input === '' || isEmptySpecBuffer(nodeState.code)) return;
    void applyGrammar(String(nodeState.code));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [comparing, inputsKey]);

  const required = useMemo(() => {
    try { return requiredColumns(JSON.parse(String(nodeState.code ?? ''))); } catch { return []; }
  }, [nodeState.code]);
  const rows = scenarioRequirements(inputs, required, columnsBySlot);
  // The strip says what each scenario needs while the node compares them; the
  // switch is in Node settings.
  const outputHeader = comparing ? React.createElement(VegaCompareStrip, { rows }) : undefined;
  const bySlot = new Map(rows.map((row) => [row.slot, row]));
  const inputCircleDecor = comparing
    ? (slot: number) => {
        const row = bySlot.get(slot);
        if (!row) return undefined;
        const lacks = row.missing.length > 0;
        return {
          style: { background: row.label.color, ...(lacks ? { boxShadow: MISSING_RING } : {}) },
          title: `input_${slot} · ${row.label.name}${lacks ? ` — missing: ${row.missing.join(', ')}` : ''}`,
        };
      }
    : undefined;

  // The DOM id useVega renders the compiled view into — pre-Phase-B this was
  // declared in `adapter.editor.outputId`, but the manifest can't carry a
  // function. We own the `"vega" + nodeId` convention here so UniversalNode
  // can mount the matching `<div id={outputIdOverride}>` container.
  return {
    applyGrammar,
    outputIdOverride: 'vega' + data.nodeId,
    // Only ever offered for an empty buffer, so it cannot displace real work.
    defaultValueOverride: generatedSpec,
    ...(outputHeader ? { outputHeader } : {}),
    ...(inputCircleDecor ? { inputCircleDecor } : {}),
  };
};

/** A frame's column names: its schema's, else its rows'. */
function frameColumns(frame: GrammarFrame): string[] {
  if (frame.schema) return Object.keys(frame.schema);
  const rows = frame.dataType === 'geodataframe'
    ? (frame.payload?.features ?? []).slice(0, 20).map((f: any) => f?.properties ?? {})
    : toRows({ data: frame.payload }).slice(0, 20);
  return [...new Set(rows.flatMap((row: any) => Object.keys(row ?? {})))] as string[];
}

/** A frame's first column holding numbers, for a comparison's starter bars. */
function firstNumberColumn(frame: GrammarFrame | undefined): string | null {
  if (!frame) return null;
  const rows = frame.dataType === 'geodataframe'
    ? (frame.payload?.features ?? []).slice(0, 20).map((f: any) => f?.properties ?? {})
    : toRows({ data: frame.payload }).slice(0, 20);
  for (const column of frameColumns(frame)) {
    if (rows.some((row: any) => typeof row?.[column] === 'number')) return column;
  }
  return null;
}

/** The input's 100-row preview: plenty for classifying columns, and cheaper than /get. */
function readVegaPreview(input: unknown): Promise<GrammarInput> {
  return readGrammarInput(input, { label: 'the 2D Plot (Vega-Lite)', preview: true, circles: true });
}

/** The Vega-Lite ladder over the input's first frame, its first input's (utils/vegaDefaultSpec). */
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
