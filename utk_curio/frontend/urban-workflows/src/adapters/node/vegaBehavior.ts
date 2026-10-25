
import { useEffect, useRef } from 'react';
import type { GrammarRedraw, NodeBehaviorHook } from '../../registry/types';
import { useVega } from '../../hook/useVega';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { useStarterSpec } from '../../hook/useStarterSpec';
import { opensWithPackageStarter } from '../../registry/packageStarter';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { emptyRenderKind, renderOutcome, type RenderCounts } from '../../utils/renderOutcome';
import { defaultSpecText } from '../../utils/vegaDefaultSpec';
import { isEmptySpecBuffer } from '../../utils/starterSpec';
import { toRows } from '../../utils/rowSource';
import { resolveGeometryField } from '../../utils/geometryField';
import { readGrammarInput, type GrammarInput } from '../../utils/grammarInput';
import type { ScenarioLabel } from '../../utils/scenarios/scenarioColors';
import { inputScenarios } from '../../utils/scenarios/inputScenarios';
import type { Scenario } from '../../utils/scenarios/scenarioModel';
import { readsInputs } from '../../utils/vegaDatasets';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { connected, upstreamErrored, upstreamRunning, upstreamStopped } = useGrammarInputState(data.nodeId);
  const flow = useFlowContext() as {
    // A failed chart says so to the nodes it feeds, as a failed code node does.
    markNodeErrored?: (nodeId: string) => void;
    nodes?: any[];
    edges?: any[];
    scenarios?: Scenario[];
    isRunActive?: boolean;
    serverRunActive?: boolean;
  };
  const { markNodeErrored } = flow;

  // A chart draws exactly its spec. Its scenario chips, which its editor
  // resolves before a run (utils/references/codeReferences), write the colors
  // and names of the boxes its inputs come from; the rows of a spec that reads
  // `inputs` carry each box's id and name. A spec without the chips draws in
  // Vega-Lite's own colors and order.
  const nodes = flow.nodes ?? [];
  const edges = flow.edges ?? [];
  const scenarios = flow.scenarios ?? [];
  const inputs = inputScenarios(data.nodeId, nodes, edges, scenarios);
  // Each circle's label, which its rows carry and its chips write.
  const inputLabels = inputs.map((input) => input.label);
  const labelsRef = useRef({ rows: inputLabels, bySlot: new Map<number, ScenarioLabel>() });
  labelsRef.current = { rows: inputLabels, bySlot: new Map(inputs.map((input) => [input.slot, input.label])) };
  /** What a redraw follows: for a chart reading `inputs` (*stacked*), each
   * circle's box id and name, which its rows carry; and the spec as its chips
   * write it. */
  const keyOf = (stacked: boolean, spec: string): string =>
    JSON.stringify([stacked ? labelsRef.current.rows.map((label) => [label.scenario ?? null, label.name]) : null, spec]);
  // Changes whenever a label does, so the chart asks its chips again.
  const labelsKey = JSON.stringify(
    inputs.map(({ slot, label }) => [slot, label.scenario ?? null, label.name, label.color, label.rank ?? null]),
  );

  // A starter spec chosen from the arriving input's column types, the way
  // every grammar node fills an empty editor (hook/useStarterSpec).
  const generatedSpec = useStarterSpec({
    input: data.input,
    buffer: nodeState.code,
    written: data.defaultCode,
    enabled: !opensWithPackageStarter(data.nodeType),
    read: readVegaPreview,
    choose: chooseVegaStarter,
  });

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
    upstreamRunning,
    upstreamStopped,
    // What the editor holds now, typing included.
    hasSpec: !isEmptySpecBuffer(nodeState.code) || generatedSpec !== undefined,
    // A chart first drawn over zero rows said so; when its rows arrive and it
    // draws them, that has to be said too.
    onRedraw: reportDrawn,
    // The names a spec reading `inputs` gives each input's rows.
    inputLabels,
  });

  // The spec last handed in, whether it reads `inputs`, how its editor writes
  // it again for new labels, and what it was drawn with.
  const appliedRef = useRef<{ spec: string; stacked: boolean; redraw?: GrammarRedraw; key: string } | null>(null);
  const draw = async (spec: string, how?: typeof AS_A_RELABEL) => {
    try {
      reportDrawn(await handleCompileGrammar(spec, how));
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      showToast(error.message, 'error');
      markNodeErrored?.(data.nodeId);
    }
  };
  const applyGrammar = async (spec: string, redraw?: GrammarRedraw) => {
    const stacked = specReadsInputs(spec);
    appliedRef.current = { spec, stacked, redraw, key: keyOf(stacked, spec) };
    await draw(spec);
  };
  /** The spec the applied chart would draw now: its chips written again with
   * the labels as they are, or as it was handed in when its editor cannot. */
  const specNow = (applied: NonNullable<typeof appliedRef.current>): string =>
    applied.redraw?.(labelsRef.current.bySlot) ?? applied.spec;

  // A scenario renamed or recolored draws a chart again when what it draws
  // moves: what its chips write, or, for one that reads `inputs`, the names
  // its rows carry. A run draws it itself, so not during one: once the run
  // ends, the chart is drawn again only if the run did not.
  const runInFlight = !!flow.isRunActive || !!flow.serverRunActive;
  const executing = nodeState.output?.code === 'exec';
  const busyRef = useRef(false);
  busyRef.current = runInFlight || executing;
  // One redraw at a time. A color dragged through the picker is written at
  // each step it passes, and a redraw takes the chart's selection from the
  // view the one before it built, which holds it only once that one is done.
  // Done, it draws again if the labels moved meanwhile.
  const redrawingRef = useRef(false);
  const redraw = async () => {
    redrawingRef.current = true;
    try {
      for (let applied = appliedRef.current; applied && !busyRef.current; applied = appliedRef.current) {
        const spec = specNow(applied);
        const drawnKey = keyOf(applied.stacked, spec);
        if (applied.key === drawnKey) break;
        appliedRef.current = { ...applied, key: drawnKey };
        await draw(spec, AS_A_RELABEL);
      }
    } finally {
      redrawingRef.current = false;
    }
  };
  useEffect(() => {
    if (!appliedRef.current || runInFlight || executing || redrawingRef.current) return;
    void redraw();
  }, [labelsKey, runInFlight, executing]);

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

/**
 * How a chart is drawn again when a scenario is recolored or renamed: with no
 * version recorded in its provenance and nothing handed downstream, since its
 * spec and its input did not change, and with a selection made in the chart
 * kept.
 */
const AS_A_RELABEL = { recordsProvenance: false, forwardsInput: false, keepsSelection: true };

/** Whether the spec *text* reads the stacked dataset `inputs`; not when it is not JSON. */
function specReadsInputs(text: string): boolean {
  try {
    return readsInputs(JSON.parse(text));
  } catch {
    return false;
  }
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
