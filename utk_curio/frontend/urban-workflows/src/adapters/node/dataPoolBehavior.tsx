import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useEdges } from 'reactflow';
import { NodeBehaviorHook } from '../../registry/types';
import useTableData from '../../hook/useTableData';
import { ICodeData, ICodeDataContent } from '../../types';
import { IPropagation, useFlowContext } from '../../providers/FlowProvider';
import DataPoolContent from './components/DataPoolContent';
import { hasIncomingEdge, incomingSourceIds, NODE_EMPTY_COPY, resolveNodeEmptyReason } from '../../utils/nodeEmptyState';
import { reportNodeRuntime } from '../../services/nodeRuntimeReport';
import { ResolutionType } from '../../constants';
import { isSelectionEcho } from '../../utils/selectionEcho';
import { columnRows, featureRows, isActiveSelect, matchSelections } from '../../utils/selectionMatch';
import { dataPoolMode, DataPoolModes } from '../../utils/dataPoolModes';
import { copyForFlags } from '../../utils/poolFlagCopy';

/** The charts joined to a pool by an interaction edge. */
function interactionPeers(edges: readonly any[], poolId: string): Set<string> {
  const peers = new Set<string>();
  for (const edge of edges) {
    if (edge?.sourceHandle !== 'in/out' || edge?.targetHandle !== 'in/out') continue;
    if (edge.source === poolId) peers.add(edge.target);
    else if (edge.target === poolId) peers.add(edge.source);
  }
  return peers;
}

export const useDataPoolBehavior: NodeBehaviorHook = (data, nodeState) => {
  // Which empty state to show turns on whether anything is wired in, which
  // only the graph knows (#224).
  const poolEdges = useEdges();
  const connected = hasIncomingEdge(poolEdges, data.nodeId);
  // A failed upstream node propagates nothing, so "no input" is ambiguous
  // between never-run and ran-and-failed. The exec status is the only place
  // that difference is recorded (#347).
  const { projectId: flowProjectId, nodeExecStatus, updateDataNode } = useFlowContext();
  const upstreamErrored = incomingSourceIds(poolEdges, data.nodeId).some(
    (sourceId) => nodeExecStatus?.[sourceId] === "errored",
  );
  const [output, setOutput] = useState<ICodeData>({ code: '', content: '' });

  // How the selections that reach the pool combine: the selects of one chart,
  // and the charts with each other. Read from the node, where the selects in
  // the body save them and TrillGenerator writes them (metadata.dataPool).
  const savedModes = (data as { dataPool?: DataPoolModes }).dataPool;
  const insideChartMode = dataPoolMode(savedModes?.insideChart);
  const betweenChartsMode = dataPoolMode(savedModes?.betweenCharts);
  const saveMode = useCallback((key: keyof DataPoolModes, value: string) => {
    const mode = dataPoolMode(value);
    if (mode === dataPoolMode(savedModes?.[key])) return;
    updateDataNode(data.nodeId, { ...data, dataPool: { ...(savedModes ?? {}), [key]: mode } });
  }, [data, savedModes, updateDataNode]);
  const onInsideChartModeChange = useCallback((value: string) => saveMode('insideChart', value), [saveMode]);
  const onBetweenChartsModeChange = useCallback((value: string) => saveMode('betweenCharts', value), [saveMode]);

  const {
    createTableData,
    processDataAsync,
    activeTab,
    setActiveTab,
    tabData,
  } = useTableData({ data });

  // Tracks the most recent in-flight processDataAsync so Play All can wait for
  // it. Without this, UniversalNode sees no `sendCode` for the pool and calls
  // signalNodeExecDone immediately — the next topological level then runs
  // before the pool's async fetch has propagated output to its children, and
  // downstream code nodes crash on `arg=None`.
  const inflightRef = useRef<Promise<any> | null>(null);
  // True once any feature has been marked interacted="1" so that a subsequent
  // "clear brush" (UNDETERMINED signal) still resets features to "0".
  const anyInteractedRef = useRef(false);
  // The input and propagation toggle the last run saw. A run that another
  // pool's propagation started (the toggle flipped, the input did not change)
  // re-emits the same rows, and so does one fed by an upstream pool's echo.
  const lastRunRef = useRef<{ input: unknown; propagation: unknown } | null>(null);
  // Each linked chart's latest selection, keyed by the chart's node id, oldest
  // first. FlowProvider hands the pool only the selection that just changed;
  // a merge combines it with the ones the other charts still hold.
  const selectionsRef = useRef(new Map<string | undefined, any>());
  // The delivery already taken in, so a mode change resolves the same
  // selections again without counting the last one as new.
  const deliveredRef = useRef<unknown>(undefined);
  // A chart whose interaction edge to the pool is removed takes its selection
  // with it, so no merge goes on combining a chart that is no longer linked.
  const peers = useMemo(() => interactionPeers(poolEdges, data.nodeId), [poolEdges, data.nodeId]);
  const peersRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const id of peersRef.current) {
      if (!peers.has(id)) selectionsRef.current.delete(id);
    }
    peersRef.current = peers;
  }, [peers]);

  useEffect(() => {
    const hasInput = (() => {
      if (data.input == null || data.input === "") return false;
      if (typeof data.input !== "object") return true;
      const input = data.input as { dataType?: string; data?: unknown[] };
      if (input.dataType === "outputs") {
        return Array.isArray(input.data) && input.data.length > 0;
      }
      return Object.keys(input).length > 0;
    })();

    if (!hasInput) {
      setOutput({ code: "", content: "" });
      return;
    }

    const last = lastRunRef.current;
    const selectionEcho = isSelectionEcho(data.input) || (
      last != null && last.input === data.input && last.propagation !== data.newPropagation
    );
    lastRunRef.current = { input: data.input, propagation: data.newPropagation };

    let cancelled = false;
    const p = processDataAsync({ selectionEcho });
    inflightRef.current = p;
    (async () => {
      try {
        const result = await p;
        if (!cancelled) setOutput(result as ICodeData);
      } finally {
        if (inflightRef.current === p) inflightRef.current = null;
      }
    })();
    return () => { cancelled = true; };
  }, [data.input, data.newPropagation]);

  // Play All path. UniversalNode wires this as `sendCode` so it skips the
  // immediate signalNodeExecDone and shows the "exec" indicator on the pool.
  // signalNodeExecDone for the pool then fires from FlowProvider.applyNewOutput
  // *after* processDataAsync has propagated downstream — so the next level
  // only triggers once children's data.input is set. In the common Play All
  // path, the data-input effect above has already published a promise on
  // inflightRef before this callback runs (effects fire in declaration order
  // and the behavior hook is registered before UniversalNode's triggerExec
  // effect), so we just await it. Falls through to a fresh fetch when
  // triggered without a data-input change (e.g. a second Play All click).
  const sendCodeOverride = useCallback(async () => {
    if (inflightRef.current) return inflightRef.current;
    const p = processDataAsync();
    inflightRef.current = p;
    try {
      const result = await p;
      setOutput(result as ICodeData);
    } finally {
      if (inflightRef.current === p) inflightRef.current = null;
    }
  }, [processDataAsync]);

  useEffect(() => {
    if (output.content != "" && data.interactions != undefined) {

      // Take in what was just delivered, newest last. The chart that just
      // selected is the newest entry, priority 1; every other chart's latest
      // selection is priority 0. A merge resolves them all. OVERWRITE resolves
      // the newest alone, as it resolved the delivery alone before, so a layer
      // no chart just selected keeps its flags.
      const held = selectionsRef.current;
      if (data.interactions !== deliveredRef.current) {
        deliveredRef.current = data.interactions;
        const delivered = (data.interactions as any[])
          .filter(Boolean)
          .sort((a, b) => (a.priority === 1 ? 1 : 0) - (b.priority === 1 ? 1 : 0));
        for (const interaction of delivered) {
          held.delete(interaction.nodeId);
          held.set(interaction.nodeId, interaction);
        }
      }
      const kept = Array.from(held.values());
      const latest = kept.length > 0 ? { ...kept[kept.length - 1], priority: 1 } : undefined;
      const interactions: any[] = betweenChartsMode === ResolutionType.OVERWRITE
        ? (latest ? [latest] : [])
        : kept.map((interaction, index) => (index === kept.length - 1 ? latest : { ...interaction, priority: 0 }));

      // Skip purely initialising/empty signals (e.g. Vega's UNDETERMINED emit on
      // setup) when no features are currently marked, so the O(n) marking loop
      // and clone don't run on every mount. If features were previously marked
      // interacted="1" we still need to process to reset them to "0" (clear brush).
      const hasRealInteraction = interactions.some((interaction: any) =>
        Object.values(interaction?.details ?? {}).some((detail: any) => isActiveSelect(detail)),
      );
      if (!hasRealInteraction && !anyInteractedRef.current) return;

      // Group incoming interactions by the layer they target so multi-layer
      // wrappers can route a brush on (say) roads to the roads features only,
      // not surface. Interactions without a `layerRef` — Vega, plain Python
      // dataframes — go to the `undefined` bucket and fall back to the legacy
      // first-layer behavior so existing single-layer flows are unaffected.
      const interactionsByLayer = new Map<string | undefined, any[]>();
      for (const interaction of interactions) {
        const sel = interaction?.details?.autk_selection;
        const layerRef: string | undefined = sel?.layerRef;
        const bucket = interactionsByLayer.get(layerRef) ?? [];
        bucket.push(interaction);
        interactionsByLayer.set(layerRef, bucket);
      }

      // The flags go on a copy of the output, never on the output itself:
      // what the pool sent before is still held downstream (utils/poolFlagCopy).
      // The whole wrapper is re-emitted so sibling layers in an `outputs`
      // envelope survive the round-trip (surface/parks/water for road brushes).
      const rawContent = output.content as any;
      const isOutputsWrapper =
        typeof rawContent === 'object' &&
        rawContent.dataType === 'outputs' &&
        Array.isArray(rawContent.data);
      const clonedOutput = isOutputsWrapper
        ? { ...rawContent, data: rawContent.data.map(copyForFlags) }
        : copyForFlags(rawContent);
      // For multi-layer `outputs` wrappers, process each layer independently;
      // for single-layer wrappers (geodataframe / dataframe), there's just one
      // pass and the behavior matches the pre-multilayer code exactly.
      const layers: ICodeDataContent[] = isOutputsWrapper ? clonedOutput.data : [clonedOutput];

      // Propagation accumulates across all processed layers — historically a
      // dataframe-only feature that other pools downstream consume via
      // applyNewPropagation, so its shape doesn't change here.
      let propagationObj: IPropagation = {
          nodeId: data.nodeId,
          propagation: {},
      };

      let anyInteractedThisEvent = false;

      for (let layerIdx = 0; layerIdx < layers.length; layerIdx++) {
      const parsedInput = layers[layerIdx];
      const layerName = (parsedInput as any).layerName;

      // Pick which interactions apply to this layer.
      //
      // Single-layer wrapper: there's only one place the interactions can land,
      // so route every interaction to it regardless of whether the autk-grammar
      // emit used a "upstream" alias dataRef (Vega/Python flows) or the actual
      // table name (single-layer autk compute). This keeps Interaction_Vega_Autark
      // and Interaction_Autark working without per-example dataRef alignment.
      //
      // Multi-layer wrapper: match interactions to layers by name. Interactions
      // whose layerRef doesn't match any layer in the wrapper are dropped (the
      // source explicitly named a target that isn't here). No-layerRef
      // interactions still fall through to data[0] so existing Vega flows are
      // unaffected even when promoted to a multi-layer wrapper later.
      let interactionsForLayer: any[];
      if (layers.length === 1) {
        interactionsForLayer = interactions;
      } else {
        interactionsForLayer = interactionsByLayer.get(layerName) ?? [];
        if (layerIdx === 0) {
          const fallback = interactionsByLayer.get(undefined);
          if (fallback) interactionsForLayer = [...interactionsForLayer, ...fallback];
        }
      }
      if (interactionsForLayer.length === 0) continue;

      let columns: string[] = [];
      let dfIndices: string[] = [];

      if (parsedInput.dataType == "dataframe") {
          columns = Object.keys(parsedInput.data);
          dfIndices = Object.keys(parsedInput.data[columns[0]]);
      }

      // Which rows the selections pick out, resolved within each chart and
      // across charts: the matcher a chart joined by a direct interaction edge
      // uses too (utils/selectionMatch).
      const rows = parsedInput.dataType == "geodataframe"
          ? featureRows(parsedInput.data)
          : parsedInput.dataType == "dataframe"
              ? columnRows(parsedInput.data)
              : { count: 0, value: () => undefined };
      const interactedList: number[] = matchSelections(interactionsForLayer, rows, {
          plot: insideChartMode,
          between: betweenChartsMode,
      });

      // O(1) lookup replaces O(n) Array.includes inside the marking loop below.
      const interactedSet = new Set<number>(interactedList);

      // A dataframe holds its flags in a column; a geodataframe's are on each
      // feature's properties, below.
      if (parsedInput.dataType == "dataframe") parsedInput.data.interacted = {};

      let objectsCounter = 0;

      if (parsedInput.dataType == "dataframe")
          objectsCounter = dfIndices.length;
      else if (parsedInput.dataType == "geodataframe")
          objectsCounter = parsedInput.data.features.length;

      // A selection names rows, so a building layer is flagged by row too:
      // each of its parts is a row, and the plot and the map name parts (#536).
      for (let i = 0; i < objectsCounter; i++) {
          if (interactedSet.has(i)) {
              if (parsedInput.dataType == "dataframe") {
                  parsedInput.data.interacted[dfIndices[i]] = "1"; // 1 -> interacted with

                  if (parsedInput.data.linked != undefined) {
                      for (const index of parsedInput.data.linked[
                          dfIndices[i]
                      ]) {
                          propagationObj.propagation[index] = "1";
                      }
                  }
              } else if (parsedInput.dataType == "geodataframe") {
                  parsedInput.data.features[i].properties.interacted = "1"; // 1 -> interacted with
                  if (parsedInput.data.features[i].properties.linked != undefined) {
                      for (const index of parsedInput.data.features[i].properties.linked) {
                          propagationObj.propagation[index] = "1";
                      }
                  }
              }
          } else {
              if (parsedInput.dataType == "dataframe") {
                  parsedInput.data.interacted[dfIndices[i]] = "0"; // 0 -> not interacted with
                  if (parsedInput.data.linked != undefined) {
                      for (const index of parsedInput.data.linked[dfIndices[i]]) {
                          propagationObj.propagation[index] = "0";
                      }
                  }
              } else if (parsedInput.dataType == "geodataframe") {
                  parsedInput.data.features[i].properties.interacted = "0";
                  if (parsedInput.data.features[i].properties.linked != undefined) {
                      for (const index of parsedInput.data.features[i].properties.linked) {
                          propagationObj.propagation[index] = "0";
                      }
                  }
              }
          }
      }

      if (interactedList.length > 0) anyInteractedThisEvent = true;
      }  // for layerIdx

      anyInteractedRef.current = anyInteractedThisEvent;

      setOutput({ code: "success", content: clonedOutput });
      if (typeof data.outputCallback === 'function') {
        // The same rows with new flags: linked charts swap them in and
        // highlight, they do not redraw (utils/selectionEcho). The echo names
        // the chart that just selected, under every mode: that chart already
        // shows its own selection, and a plot's brush IS its selection, so it
        // leaves the echo alone (#541) while the other charts show the rows
        // the modes resolved.
        const selectionSource = latest?.nodeId;
        data.outputCallback(data.nodeId, clonedOutput,
          selectionSource ? { selectionEcho: true, selectionSource } : { selectionEcho: true });
      }

      // call callback propagation
      if (typeof data.propagationCallback === 'function') {
        data.propagationCallback(propagationObj);
      }
    }
    // A mode chosen in the body resolves the selections the pool holds again.
  }, [data.interactions, insideChartMode, betweenChartsMode]);

  const tableData = useMemo(() => {
    // output.content is always a data object (never a JSON string) so we can
    // use it directly — mirroring the original DataPoolNode useEffect([output]).
    // For multi-input the content is {dataType:"outputs", data:[...]}: pick the
    // active tab's item; for single input use it as-is.
    if (output.content && output.content !== '') {
      const content = output.content as any;
      const source: ICodeDataContent =
        content.dataType === 'outputs'
          ? content.data[parseInt(activeTab)]
          : content;
      if (source) return createTableData(source);
    }
    // Fallback to tabData before output is first populated
    const displayTable = tabData[parseInt(activeTab)];
    if (displayTable) return createTableData(displayTable as ICodeDataContent);
    return [];
  }, [output, tabData, activeTab, createTableData]);

  // dev/138 (closes dev/137 F1): the pool is the node that DETECTS a bad
  // input — "this input is not tabular data" is its own sentence — and it
  // reported nothing to the journal, because its outcome lives in this
  // behavior's local state rather than in `nodeState.output`, so dev/135's
  // reporter never fired for it. In the owner's `edd71e67` the pool was the
  // only node that knew the upstream had produced something unusable.
  //
  // Only the two REAL failures are reported. A pool that is not wired yet owes
  // nothing, and one whose upstream has not run is waiting rather than broken
  // — its upstream reports its own outcome.
  useEffect(() => {
    const hasInput = data.input != null && data.input !== "";
    const reason = resolveNodeEmptyReason({
      connected,
      upstreamErrored,
      hasInput,
      tabular: tabData.length > 0,
      rowCount: tableData.length,
    });
    // An upstream failure is the upstream's to report, like a node that has
    // not run yet (#347).
    if (
      reason === "disconnected" ||
      reason === "upstream-not-run" ||
      reason === "upstream-errored"
    )
      return;
    const projectId = (data as { projectId?: string }).projectId ?? flowProjectId;
    if (!projectId) return;
    if (reason === null) {
      void reportNodeRuntime({
        dataflowId: projectId, nodeId: data.nodeId, status: "ok",
        outputType: (data.input as { dataType?: string } | null)?.dataType ?? "",
      });
      return;
    }
    const copy = NODE_EMPTY_COPY[reason];
    void reportNodeRuntime({
      dataflowId: projectId,
      nodeId: data.nodeId,
      status: "error",
      message: `${copy.title} — ${copy.hint}`,
      kind: `bad-input:${reason}`,
    });
  }, [connected, upstreamErrored, data, tabData.length, tableData.length, flowProjectId]);

  // Memoize so the JSX reference is stable across re-renders. NodeEditor
  // auto-switches to the "output" tab whenever `contentComponent` changes
  // identity — without this, any re-render (e.g. React Flow deselecting the
  // node on a pane click) would yank the user out of the code editor.
  const contentComponent = useMemo(
    () => (
      <DataPoolContent
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        tabData={tabData}
        tableData={tableData}
        data={data}
        connected={connected}
        upstreamErrored={upstreamErrored}
        insideChartMode={insideChartMode}
        betweenChartsMode={betweenChartsMode}
        onInsideChartModeChange={onInsideChartModeChange}
        onBetweenChartsModeChange={onBetweenChartsModeChange}
      />
    ),
    [
      activeTab, setActiveTab, tabData, tableData, data, connected, upstreamErrored,
      insideChartMode, betweenChartsMode, onInsideChartModeChange, onBetweenChartsModeChange,
    ],
  );

  return {
    contentComponent,
    sendCodeOverride,
    setOutputCallbackOverride: setOutput,
    outputOverride: output,
    setSendCodeCallbackOverride: () => {},
  };
}
