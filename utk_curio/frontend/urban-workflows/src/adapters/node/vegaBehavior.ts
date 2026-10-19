
import { useEffect, useRef } from 'react';
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
import { readGrammarInput, type GrammarInput } from '../../utils/grammarInput';
import { upstreamCompareLabels } from '../../utils/compare/compareInputs';
import type { CompareInputLabel } from '../../utils/compare/compareSettings';
import { scenarioScale } from '../../utils/compare/comparePresets';
import { withScenarioScales } from '../../utils/compare/scenarioScales';
import type { Scenario } from '../../utils/scenarios/scenarioModel';

export const useVegaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const { showToast } = useToastContext();
  const { connected, upstreamErrored } = useGrammarInputState(data.nodeId);
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

  // A chart after a Compare Scenarios node draws its scenarios as that node's
  // Chart tab does, in the colors of their boxes and the order of its inputs
  // (utils/compare/scenarioScales), whatever the spec writes for them.
  const labels = upstreamCompareLabels(data.nodeId, flow.nodes ?? [], flow.edges ?? [], flow.scenarios ?? []);
  const scalesKey = scalesKeyOf(labels);
  const labelsRef = useRef(labels);
  labelsRef.current = labels;

  // A starter spec chosen from the arriving input's column types, the way
  // every grammar node fills an empty editor (hook/useStarterSpec).
  const generatedSpec = useStarterSpec({
    input: data.input,
    buffer: nodeState.code,
    written: data.defaultCode,
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
    // What the editor holds now, typing included.
    hasSpec: !isEmptySpecBuffer(nodeState.code) || generatedSpec !== undefined,
    // A chart first drawn over zero rows said so; when its rows arrive and it
    // draws them, that has to be said too.
    onRedraw: reportDrawn,
  });

  // The spec last handed in, and the scales it was drawn with.
  const appliedRef = useRef<{ spec: string; scalesKey: string } | null>(null);
  const draw = async (spec: string, how?: typeof AS_THE_CHART_TAB) => {
    try {
      reportDrawn(await handleCompileGrammar(withCompareScales(spec, labelsRef.current), how));
    } catch (error: any) {
      nodeState.setOutput({ code: 'error', content: error.message, outputType: '' });
      showToast(error.message, 'error');
      markNodeErrored?.(data.nodeId);
    }
  };
  const applyGrammar = async (spec: string) => {
    appliedRef.current = { spec, scalesKey: scalesKeyOf(labelsRef.current) };
    await draw(spec);
  };

  // A scenario renamed or recolored draws the chart again, as it draws the
  // Compare node's Chart tab again, and the same way. A run draws it itself,
  // so not during one: once the run ends, the chart is drawn again only if the
  // run did not.
  const runInFlight = !!flow.isRunActive || !!flow.serverRunActive;
  const executing = nodeState.output?.code === 'exec';
  useEffect(() => {
    const applied = appliedRef.current;
    if (!applied || applied.scalesKey === scalesKey || runInFlight || executing) return;
    appliedRef.current = { ...applied, scalesKey };
    void draw(applied.spec, AS_THE_CHART_TAB);
  }, [scalesKey, runInFlight, executing]);

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
 * How a chart after a Compare Scenarios node is drawn again when a scenario
 * is recolored or renamed: as the Compare node's Chart tab draws its own
 * (components/compare/CompareChart), with no version recorded in its
 * provenance and nothing handed downstream. A selection made in the chart is
 * kept, which the Chart tab's presets never make.
 */
const AS_THE_CHART_TAB = { recordsProvenance: false, forwardsInput: false, keepsSelection: true };

/**
 * What a chart after a Compare node draws of *labels*: the scenarios' names
 * and colors in the order of its inputs (`scenarioScale`). A scenario id
 * alone, or the order a label's keys are written in, draws nothing different.
 */
function scalesKeyOf(labels: readonly CompareInputLabel[] | null): string {
  return labels ? JSON.stringify(scenarioScale(labels)) : '';
}

/**
 * *spec* with its channels on `scenario_name` drawn as *labels* say
 * (utils/compare/scenarioScales); as written, character for character, with no
 * labels, with nothing to fill, or when it is not JSON, which the compile then
 * reports as it always does.
 */
function withCompareScales(spec: string, labels: readonly CompareInputLabel[] | null): string {
  if (!labels) return spec;
  let parsed: unknown;
  try {
    parsed = JSON.parse(spec);
  } catch {
    return spec;
  }
  const filled = withScenarioScales(parsed, labels);
  return filled === parsed ? spec : JSON.stringify(filled);
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
