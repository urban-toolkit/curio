import { useEffect, useRef, useState } from 'react';
import type { SidewalkTileEditConfig } from './SidewalkTileEditor';
import { contextOutput, type PreparedContext } from './beforeAfterContext';
import type { FeatureCollection } from './geojson';
import { assetUrl } from './resourceResolver';
import { buildOverview, committedSignature, overviewIdentity, stableJson, validateOverview, type OverviewContext } from './overviewData';

/** Publishes committed geometry independently of active tile and transient selection echoes. */
export function useSidewalkOverview(config: SidewalkTileEditConfig, emit: (output: unknown) => void, supplied?: PreparedContext | null) {
  const identity = config.overview ? overviewIdentity(config) : '';
  const [loaded, setLoaded] = useState<{ identity: string; context: OverviewContext } | null>(null);
  const [error, setError] = useState('');
  const refs = useRef({ config, emit });
  refs.current = { config, emit };
  const published = useRef('');
  const latestOutput = useRef<unknown>(undefined);
  useEffect(() => {
    setLoaded(null); setError(''); published.current = ''; latestOutput.current = undefined;
    if (!identity) return;
    if (supplied) { setLoaded({ identity, context: supplied }); return; }
    if (refs.current.config.mode === 'input-overview') return;
    const controller = new AbortController();
    const overview = refs.current.config.overview!;
    if (Object.values(overview).some(value => !value.trim())) {
      setError('Overview dataset ID and all three resource paths are required.');
      return () => controller.abort();
    }
    const load = async (path: string): Promise<FeatureCollection> => {
      const response = await fetch(assetUrl(path), { signal: controller.signal });
      if (!response.ok) throw new Error(`Overview resource failed (HTTP ${response.status}): ${path}`);
      const value = await response.json();
      if (value?.type !== 'FeatureCollection' || !Array.isArray(value.features)) throw new Error(`Overview resource is not a GeoJSON FeatureCollection: ${path}`);
      return value;
    };
    Promise.all([load(overview.gridUrl), load(overview.networkUrl), load(overview.boundariesUrl)])
      .then(([grid, network, boundaries]) => {
        if (controller.signal.aborted) return;
        const context = { grid, network, boundaries };
        validateOverview(context); setLoaded({ identity, context });
      }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e)); });
    return () => controller.abort();
  }, [identity, supplied]);
  const context = loaded?.identity === identity ? loaded.context : null;
  const signature = context ? committedSignature(config, context.grid) : '';
  const publish = (next: SidewalkTileEditConfig, latest?: unknown) => {
    if (!context) return;
    if (latest !== undefined) latestOutput.current = latest;
    const output = supplied ? contextOutput(supplied, next, latestOutput.current) : buildOverview(context, next, latestOutput.current);
    const content = stableJson(output);
    if (content === published.current) return;
    published.current = content;
    refs.current.emit(output);
  };
  useEffect(() => {
    if (context) publish(refs.current.config);
  // Selection, drafts, and callback identity do not change committed geometry.
  }, [context, signature]);
  return { context, error, loading: !!identity && !context && !error, publish };
}
