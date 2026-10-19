import React from 'react';
import type { SidewalkBehaviorData, SidewalkNodeState, SidewalkBehaviorResult } from './runtimeTypes';
import { SidewalkTileEditor, parseSidewalkEditConfig } from './SidewalkTileEditor';
import { latestAutkSelection } from './autkSelection';
import { usePreparedInput } from './sidewalkPreparation';
import { contextConfig, contextOutput, readPreparedContext } from './beforeAfterContext';
import { useSidewalkOverview } from './useSidewalkOverview';
import { sourceFingerprint as makeSourceFingerprint } from './streetViewContract';
import { sidewalkNodeStyles as ui } from './sidewalkNodeStyles';
import { buildTileNeighborIndex } from './tileNeighbors';

/** Dedicated review/edit behavior for one selected prepared Stewards tile. */
export function useSidewalkTileEditBehavior(data: SidewalkBehaviorData, nodeState: SidewalkNodeState): SidewalkBehaviorResult {
  // Keep the active edit tile independently of analytical brush candidates.
  const activeTile = React.useRef<{ seen: boolean; index: number | null; featureId: string | null; feature: any | null; sourceFingerprint: string; viaNavigation: boolean }>({
    seen: false, index: null, featureId: null, feature: null, sourceFingerprint: '', viaNavigation: false,
  });
  const lastMapPick = React.useRef<unknown>(null);
  const [, refreshNavigation] = React.useState(0);
  const [legacyChoice, setLegacyChoice] = React.useState<number | null>(null);
  const persistedConfig = parseSidewalkEditConfig(nodeState.code);
  const inputMode = persistedConfig.mode === 'input-overview';
  const prepared = usePreparedInput(data.input, inputMode);
  const config = prepared.context ? contextConfig(prepared.context, persistedConfig) : inputMode ? { ...persistedConfig, overview: undefined } : persistedConfig;
  const fingerprint = makeSourceFingerprint(config.overview?.sourceIdentity, config.imageUrlTemplate, config.networkUrlTemplate, data.input);
  const emit = (output: any) => data.outputCallback(data.nodeId, output);
  const overview = useSidewalkOverview(config, emit, inputMode ? prepared.context : undefined);
  const grid = inputMode ? prepared.context?.grid : config.overview ? overview.context?.grid : data.input;
  const neighborIndex = React.useMemo(() => grid?.type === 'FeatureCollection' && Array.isArray(grid.features)
    ? buildTileNeighborIndex(grid) : null, [grid, fingerprint]);
  // Curio delivers the most recent *source* over a mutual edge. A camera
  // event can therefore replace the incoming Autark payload without clearing
  // the editor's selection. Only another Autark selection may supersede it.
  const incomingSelection = latestAutkSelection(data.interactions);
  const rememberedSelection = React.useRef(incomingSelection);
  if (incomingSelection) rememberedSelection.current = incomingSelection;
  const picked = incomingSelection ?? rememberedSelection.current;
  React.useEffect(() => {
    if (legacyChoice !== null && (picked?.kind !== 'legacy' || !picked.indices.includes(legacyChoice))) {
      setLegacyChoice(null);
    }
  }, [picked, legacyChoice]);
  if (picked?.kind === 'map-pick' && picked.event !== lastMapPick.current) {
    lastMapPick.current = picked.event;
    activeTile.current = {
      seen: true,
      index: picked.activeIndex,
      featureId: picked.activeIndex === null ? null : picked.featureId,
      feature: picked.activeIndex === null ? null : picked.feature,
      sourceFingerprint: fingerprint, viaNavigation: false,
    };
  }
  const activeForSource = activeTile.current.sourceFingerprint === fingerprint ? activeTile.current : null;
  const legacy = picked?.kind === 'legacy';
  const selectionIndex = legacy
    ? legacyChoice !== null && picked.indices.includes(legacyChoice) ? legacyChoice : null
    : activeForSource?.seen ? activeForSource.index : null;
  const selectionFeatureId = legacy ? null : activeForSource?.seen ? activeForSource.featureId
    : config.activeSelection?.sourceFingerprint === fingerprint ? config.activeSelection.tileId : null;
  const selectionFeature = legacy ? null : activeForSource?.feature;
  const persist = (next: typeof config) => {
    // Curio persists node.data.code with the workflow. Store corrections and
    // their undo/redo journal here so drafts survive closing and reopening.
    nodeState.setCode(JSON.stringify(next));
  };
  const interactionsCallback = (interactions: any, nodeId: string) => data.interactionsCallback(interactions, nodeId);
  const navigateToTile = (tileId: string) => {
    const feature = neighborIndex?.features.get(tileId);
    const index = neighborIndex?.positions.get(tileId);
    if (!feature || index === undefined) return;
    activeTile.current = { seen: true, index, featureId: tileId, feature, sourceFingerprint: fingerprint, viaNavigation: true };
    refreshNavigation(revision => revision + 1);
    // The prepared context publishes this complete grid as the upstream layer.
    // This highlights one editor tile through the existing mutual edge; the
    // PCP's own brushed candidate state is neither cleared nor rewritten.
    interactionsCallback({ autk_selection: { type: 'POINT', data: [{ tile_id: tileId }], priority: 1,
      source: 'SIDEWALK_TILE_EDIT', layerRef: picked?.layerRef ?? 'upstream',
      selectionOrigin: { version: 1, kind: 'map-pick', activeIndex: index },
      featureId: tileId, feature } }, data.nodeId);
  };
  const setStatus = (status: { code: string; content: string }) => nodeState.setOutput(status);
  const contentComponent = (
    <>
    {inputMode && !prepared.context && !prepared.error && <div role="status" style={ui.panel}>Loading prepared input context…</div>}
    {inputMode && prepared.error && <div role="alert" style={ui.error}>{prepared.error}</div>}
    {config.overview && overview.loading && <div role="status" style={ui.panel}>Loading complete overview context…</div>}
    {config.overview && overview.error && <div role="alert" style={ui.error}>{overview.error}</div>}
    {legacy && <label style={{ ...ui.field, padding: '6px 0' }}>Legacy selection: choose the active tile
      <select aria-label="Active tile from legacy selection" value={selectionIndex ?? ''} style={ui.input}
        onChange={event => setLegacyChoice(event.target.value === '' ? null : Number(event.target.value))}>
        <option value="">Choose a tile</option>
        {picked.indices.map(index => <option key={index} value={index}>Selected row {index + 1}</option>)}
      </select>
    </label>}
    <SidewalkTileEditor
      nodeId={data.nodeId}
      input={inputMode ? prepared.context?.grid ?? null : config.overview ? overview.context?.grid ?? null : data.input}
      originalNetwork={inputMode ? prepared.context?.network : undefined}
      selectionIndex={selectionIndex}
      allowSingleTile={!picked}
      selectionFeatureId={selectionFeatureId}
      selectionFeature={activeForSource?.viaNavigation || !inputMode ? selectionFeature : null}
      neighborIndex={neighborIndex}
      onNavigate={navigateToTile}
      sourceFingerprint={fingerprint}
      incomingInteractions={data.interactions}
      config={config}
      persist={persist}
      emit={emit}
      onCommitted={config.overview ? overview.publish : undefined}
      interactionsCallback={interactionsCallback}
      setStatus={setStatus}
    />
    </>
  );
  return { contentComponent, disablePlay: !inputMode, ...(inputMode ? { sendCodeOverride: async () => {
    try {
      const current = await readPreparedContext(data.input);
      emit(contextOutput(current, parseSidewalkEditConfig(nodeState.code)));
      setStatus({ code: 'success', content: 'Published the complete confirmed network from prepared input.' });
    } catch (e) { setStatus({ code: 'error', content: e instanceof Error ? e.message : String(e) }); }
  } } : {}) };
}
