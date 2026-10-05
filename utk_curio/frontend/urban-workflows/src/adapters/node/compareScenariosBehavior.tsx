/**
 * The Compare Scenarios node (#662): any number of scenario outcomes on its
 * growing input circles, stacked by its Python code into one table under each
 * input's scenario, which is its output; a chart of that table in the
 * scenarios' colors, drawn by the Vega-Lite node's code; and a What differs
 * tab over the scenarios' levers. In Difference, its code subtracts input 0
 * from input 1 instead, and the difference, its output, is drawn on a map by
 * the Autark node's code (a table difference as a table).
 *
 * Its code is written for it: one line per input, reading the input through
 * its chip under the scenario's id and name (`utils/compare/compareCode`). When
 * an input, or the scenario an input comes from, changes, the labels at
 * `metadata.compareScenarios.inputs` and the code are written again together,
 * which makes the node stale; so it is when the view the node is in changes
 * (`utils/compare/compareMode`: the user's choice, else Difference for two
 * rasters or two layers), the key Difference joins rows on, or the layer it
 * reads from inputs that are an Autark node's several layers. A run then
 * compares the new inputs, in the browser or on the server, as any Python
 * node's code runs.
 */
import React, { useEffect, useMemo } from "react";
import type { NodeBehaviorHook } from "../../registry/types";
import { useFlowContext } from "../../providers/FlowProvider";
import { CompareScenariosBody } from "../../components/compare/CompareScenariosBody";
import { compareInputs, labelsNeedWriting } from "../../utils/compare/compareInputs";
import { compareCode, keyOfCode, layerOfCode, modeOfCode, stackCode } from "../../utils/compare/compareCode";
import { inputKinds, wantedMode } from "../../utils/compare/compareMode";
import { normalizeCompareSettings, type CompareSettings } from "../../utils/compare/compareSettings";
import type { Scenario } from "../../utils/scenarios/scenarioModel";

/**
 * What a failed run says, for the body: a traceback's last line without its
 * exception's name (the stacking step's refusals end there), else the message.
 */
export function failureLine(content: unknown): string {
  const text = String(content ?? "").trim();
  if (!text.includes("Traceback (most recent call last)")) return text;
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  const last = lines[lines.length - 1] ?? text;
  return last.replace(/^[A-Za-z_][\w.]*(Error|Exception): /, "");
}

/**
 * The file a successful run saved its output to, from its outcome's last
 * "Saved to file:" line: what a run shows, and what a project load restores
 * the node with (`useCode.loadTrill`), on the canvas and on the dashboard.
 */
export function savedFile(content: unknown): string | null {
  const lines = String(content ?? "").split("\n");
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const match = lines[i].match(/^Saved to file: (\S+)\s*$/);
    if (match) return match[1];
  }
  return null;
}

export const useCompareScenariosBehavior: NodeBehaviorHook = (data, nodeState) => {
  const flow = useFlowContext() as any;
  const nodes: any[] = flow?.nodes ?? [];
  const edges: any[] = flow?.edges ?? [];
  const scenarios: Scenario[] = flow?.scenarios ?? [];
  const inputs = compareInputs(data.nodeId, nodes, edges, scenarios);
  const inputsKey = JSON.stringify(inputs.map((input) => [input.slot, input.label]));
  // What the code is written for besides the labels: the view the node wants,
  // the key Difference joins rows on, and the layer it reads from an Autark
  // node's several.
  const wanted = normalizeCompareSettings((data as any).compareScenarios);
  const kinds = inputKinds((data as any).inputSlots, inputs.map((input) => input.slot));
  const modeKey = JSON.stringify([wantedMode(wanted, kinds), wanted?.difference?.key ?? null, wanted?.layer ?? null]);
  // Nothing is written where nobody can save it: the dashboard, a shared view.
  const writable = !flow?.dashboardOn && flow?.viewerMode !== "shared";

  useEffect(() => {
    if (!writable) return;
    const live = nodes.find((n) => n.id === data.nodeId)?.data;
    if (!live) return;
    const stored = normalizeCompareSettings(live.compareScenarios);
    const current = String(live.code ?? live.defaultCode ?? "");
    // The view its code was written for; code that calls neither step was
    // written by hand, and only a change of its inputs writes it again.
    const written = modeOfCode(current);
    const mode = wantedMode(stored, inputKinds(live.inputSlots, inputs.map((input) => input.slot))) ?? written ?? "chart";
    const relabel = labelsNeedWriting(stored?.inputs, inputs, edges.length > 0);
    const switched = written !== null && written !== mode;
    const rekeyed = written === "difference" && mode === "difference" && keyOfCode(current) !== stored?.difference?.key;
    const relayered = written !== null && layerOfCode(current) !== stored?.layer;
    if (!relabel && !switched && !rekeyed && !relayered) return;
    const code = compareCode(mode, inputs, stored?.difference, stored?.layer);
    const settings: CompareSettings = { ...(stored ?? {}) };
    if (inputs.length > 0) settings.inputs = inputs.map((input) => input.label);
    else delete settings.inputs;
    // The play reads the node's code from here, before its editor floats it.
    nodeState.setCode(code);
    flow.updateDataNode?.(data.nodeId, {
      ...live,
      compareScenarios: Object.keys(settings).length > 0 ? settings : undefined,
      defaultCode: code,
      code,
    });
    if (nodeState.output?.code === "success") flow.markNodeStale?.(data.nodeId);
  }, [inputsKey, modeKey, writable]);

  // NodeEditor opens the Output tab whenever the body's identity changes, so
  // it changes with the node's outcome and nothing else: a run shows its chart
  // however it ran (a play, Run All in the browser, a run on the server, whose
  // steps reach the node as its outcome alone), and typing never moves the tab.
  const output = nodeState.output;
  const outcome = output?.code === "success" || output?.code === "error"
    ? `${output.code}:${String(output.content ?? "")}`
    : String(output?.code ?? "");
  const runError = output?.code === "error" ? failureLine(output.content) : null;
  const ranTo = output?.code === "success" ? savedFile(output.content) : null;
  const contentComponent = useMemo(
    () => <CompareScenariosBody nodeId={data.nodeId} runError={runError} savedPath={ranTo} />,
    [data.nodeId, outcome],
  );
  // A node just dropped has no code yet; it gets the code for its inputs.
  const fresh = typeof data.defaultCode !== "string" || data.defaultCode === "";
  return {
    contentComponent,
    ...(fresh ? { defaultValueOverride: stackCode(inputs) } : {}),
  };
};
