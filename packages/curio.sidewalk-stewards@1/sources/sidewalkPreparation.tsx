import React from 'react';
import type { SidewalkBehaviorData, SidewalkBehaviorResult, SidewalkNodeState } from './runtimeTypes';
import { prepareContext, readPreparedContext, contextOutput, withTileMeasurements, type PreparedContext } from './beforeAfterContext';
import { assetUrl } from './resourceResolver';
import { parseSidewalkEditConfig } from './SidewalkTileEditor';
import { sidewalkNodeStyles as ui } from './sidewalkNodeStyles';

export function usePreparedInput(input: unknown, enabled = true) {
  const [loaded, setLoaded] = React.useState<{ input: unknown; context: PreparedContext } | null>(null);
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    setLoaded(null); setError('');
    if (!enabled) return;
    const controller = new AbortController();
    readPreparedContext(input, controller.signal).then(context => {
      if (!controller.signal.aborted) setLoaded({ input, context });
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [input, enabled]);
  return { context: loaded && loaded.input === input ? loaded.context : null, error };
}
/** Async preparation participates in Run All through the existing package play override. */
export function useSidewalkPreparation(data: SidewalkBehaviorData, state: SidewalkNodeState): SidewalkBehaviorResult {
  const [message, setMessage] = React.useState('Connect satellite and network Data Loading inputs.');
  const refs = React.useRef({ data, state }); refs.current = { data, state };
  const pending = React.useRef<{ input: unknown; controller: AbortController; promise: Promise<PreparedContext> } | null>(null);
  const published = React.useRef('');
  const getContext = () => {
    const input = refs.current.data.input;
    if (!pending.current || pending.current.input !== input) {
      pending.current?.controller.abort();
      const controller = new AbortController();
      pending.current = { input, controller, promise: prepareContext(input, undefined, undefined, controller.signal) };
    }
    return pending.current;
  };
  const run = async (force = false) => {
    const request = getContext();
    try {
      const base = await request.promise;
      if (request.controller.signal.aborted) return;
      const raw = refs.current.state.code.trim();
      const options = raw ? JSON.parse(raw) : {};
      if (!options || typeof options !== 'object' || Array.isArray(options)) throw new Error('Sidewalk Prepare configuration must be a JSON object.');
      let context = base;
      if (options.measuredTileGridUrl) {
        if (typeof options.measuredTileGridUrl !== 'string' || !Array.isArray(options.measurementFields)) {
          throw new Error('Measured tile grid needs a URL and measurementFields array.');
        }
        const response = await fetch(assetUrl(options.measuredTileGridUrl), { signal: request.controller.signal });
        if (!response.ok) throw new Error(`Measured tile grid failed (HTTP ${response.status}).`);
        context = withTileMeasurements(base, await response.json(), options.measurementFields);
      }
      const publication = `${context.sourceIdentity}:${raw}`;
      if (force || published.current !== publication) {
        refs.current.data.outputCallback(data.nodeId, contextOutput(context, parseSidewalkEditConfig('')));
        published.current = publication;
      }
      refs.current.state.setOutput({ code: 'success', content: 'Prepared both source inputs; Before is independent of the editor.' });
      setMessage(`Prepared ${context.grid.features.length} tiles and ${context.network.features.length} original network features.`);
    } catch (e) {
      if (request.controller.signal.aborted) return;
      const message = e instanceof Error ? e.message : String(e);
      if (published.current) { refs.current.data.outputCallback(data.nodeId, null); published.current = ''; }
      refs.current.state.setOutput({ code: 'error', content: message }); setMessage(message);
    }
  };
  React.useEffect(() => { void run(); }, [data.input, state.code]);
  React.useEffect(() => () => pending.current?.controller.abort(), []);
  return { disablePlay: false, sendCodeOverride: async () => run(true), contentComponent:
    <div className="nodrag nopan nowheel" style={ui.body}>
      <div role="status" style={{ ...ui.panel, fontSize: 'var(--curio-font-size-xs)' }}>{message}</div>
    </div> };
}
