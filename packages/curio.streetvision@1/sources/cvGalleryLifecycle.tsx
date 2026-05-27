import React, { useState, useEffect, useCallback } from 'react';
import { NodeLifecycleHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';

/**
 * CV Gallery lifecycle.
 *
 * Receives the inference results JSON emitted by HF CV Inference upstream
 * (shape: `{type:'street_vision_results', results: ResultItem[], ...}`).
 * Renders a gallery + per-image inspector + aggregate stats panel, then
 * pushes the data downstream as a GEODATAFRAME-shaped FeatureCollection so
 * downstream nodes (Spatial Join, Vega-Lite, AUTK Map, …) consume it cleanly.
 *
 * Adapted from
 *   utk_curio/frontend/urban-workflows/src/adapters/node/cvAnalysisLifecycle.tsx
 * in ManeeshJupalle/curio (feat/street-vision-cv-analysis, #120). The
 * neighborhood-enrichment + Vega-Lite-template parts of the original have
 * been factored out — neighborhood tagging is now the separate generic
 * Spatial Join node (curio.builtin@1/spatial-join), and Vega-Lite specs
 * live in the user-facing docs example.
 */

// See streetViewFetcherLifecycle for the rationale on runtime URL resolution.
const API_BASE = `${(typeof window !== 'undefined' && (window as any).curio?.backendUrl) || ''}/api/streetvision`;

interface ResultItem {
  image_id: string;
  image_url: string;
  latitude?: number;
  longitude?: number;
  class_ratios?: Record<string, number>;
  object_counts?: Record<string, number>;
  detections?: { label: string; confidence: number; bbox: number[] }[];
  demo_mode?: boolean;
}

interface IncomingPayload {
  type?: string;
  job_id?: string;
  model_type?: string;
  total_images?: number;
  results?: ResultItem[];
}

type View = 'waiting' | 'gallery' | 'inspect';

// Cityscapes-flavored palette; kept in sync with the inference service's
// overlay PNG palette so colors in the gallery match colors in the overlays.
const CLASS_COLORS: Record<string, string> = {
  road: '#4A90D9', sidewalk: '#8B5CF6', building: '#2ECC71',
  wall: '#95A5A6', fence: '#BDC3C7', pole: '#E74C3C',
  'traffic light': '#F39C12', 'traffic sign': '#E67E22', vegetation: '#F5A623',
  terrain: '#1ABC9C', sky: '#3498DB', person: '#9B59B6',
  rider: '#C0392B', car: '#2C3E50', truck: '#7F8C8D',
  bus: '#D35400', train: '#16A085', motorcycle: '#8E44AD',
  bicycle: '#27AE60',
};
const DEFAULT_COLOR = '#94a3b8';

const S: Record<string, React.CSSProperties> = {
  root: { padding: '12px 14px', fontFamily: '"Roboto","Helvetica","Arial",sans-serif', fontSize: 13, color: '#333', display: 'flex', flexDirection: 'column', gap: 10 },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 },
  logo: {
    width: 28, height: 28, borderRadius: 6,
    background: 'linear-gradient(135deg,#8b5cf6,#a78bfa)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#fff', fontSize: 14, fontWeight: 700, flexShrink: 0,
  },
  title: { fontSize: 14, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.2 },
  sub: { fontSize: 10, color: '#888', marginTop: 1 },
  link: { background: 'none', border: 'none', color: '#8b5cf6', fontSize: 11, fontWeight: 600, cursor: 'pointer', marginLeft: 'auto', padding: '4px 8px' },
  btn: { padding: '8px 12px', border: 'none', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, width: '100%' },
  btnGreen: { background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0' },
  btnDisabled: { background: '#f3f4f6', color: '#9ca3af', border: '1px solid #e5e7eb', cursor: 'not-allowed' },
  card: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', fontSize: 12 },
  badge: { display: 'inline-block', padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600 },
  sectionLabel: { fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: 1, marginBottom: 4 },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginTop: 6 },
  gridCard: { border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden', cursor: 'pointer', background: '#fff' },
  gridImg: { width: '100%', height: 90, objectFit: 'cover', display: 'block', background: '#f1f5f9' },
  gridInfo: { padding: '6px 8px', fontSize: 10, color: '#64748b' },
  tabBar: { display: 'flex', gap: 2, marginBottom: 10 },
  tab: { padding: '5px 10px', fontSize: 11, fontWeight: 500, cursor: 'pointer', border: 'none', borderBottom: '2px solid transparent', background: 'none', color: '#64748b' },
  tabActive: { borderBottomColor: '#8b5cf6', color: '#8b5cf6', fontWeight: 600 },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6, marginTop: 6 },
  statCard: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '8px 10px', textAlign: 'center' },
  statValue: { fontSize: 18, fontWeight: 700, color: '#1a1a2e' },
  statLabel: { fontSize: 9, color: '#94a3b8', textTransform: 'uppercase', marginTop: 2 },
};

// Convert results → GEODATAFRAME-shaped FeatureCollection. The Table view +
// Vega-Lite both read `feature.properties.*` and `feature.geometry`.
function buildFeatureCollection(results: ResultItem[]): any {
  const round = (n: number | null | undefined, places: number) =>
    n == null ? null : Number(n.toFixed(places));
  // Union of all detected class keys so the table doesn't show holes when
  // one image didn't surface a class that another did.
  const allClassKeys = new Set<string>();
  results.forEach(r => {
    if (r.class_ratios) Object.keys(r.class_ratios).forEach(k => allClassKeys.add(k));
    if (r.object_counts) Object.keys(r.object_counts).forEach(k => allClassKeys.add(k));
  });

  const features = results.map(r => {
    const lat = round(r.latitude, 5);
    const lon = round(r.longitude, 5);
    const props: Record<string, any> = {
      image_id: r.image_id,
      image_url: r.image_url,
      latitude: lat,
      longitude: lon,
    };
    allClassKeys.forEach(k => { props[k] = 0; });
    if (r.class_ratios) {
      Object.entries(r.class_ratios).forEach(([k, v]) => { props[k] = round((v as number) * 100, 1); });
      props.analysis_type = 'segmentation';
    }
    if (r.object_counts) {
      Object.entries(r.object_counts).forEach(([k, v]) => { props[k] = v; });
      props.analysis_type = 'detection';
    }
    let dominantClass: string | null = null;
    let dominantPct = -Infinity;
    allClassKeys.forEach(k => {
      const v = props[k] as number;
      if (typeof v === 'number' && v > dominantPct) { dominantPct = v; dominantClass = k; }
    });
    props.dominant_class = dominantClass;
    props.dominant_pct = dominantPct === -Infinity ? 0 : dominantPct;
    return {
      type: 'Feature',
      geometry: lat != null && lon != null
        ? { type: 'Point', coordinates: [lon, lat] }
        : null,
      properties: props,
    };
  });
  return {
    type: 'FeatureCollection',
    features,
    metadata: { name: 'cv_inference_results' },
  };
}

export const useCvGalleryLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [view, setView] = useState<View>('waiting');
  const [payload, setPayload] = useState<IncomingPayload | null>(null);
  const [results, setResults] = useState<ResultItem[]>([]);
  const [inspectIdx, setInspectIdx] = useState<number | null>(null);
  const [inspectTab, setInspectTab] = useState<'source' | 'overlay' | 'side'>('source');
  const [pushed, setPushed] = useState(false);
  const [activeGalleryTab, setActiveGalleryTab] = useState<'gallery' | 'stats'>('gallery');
  const [pushError, setPushError] = useState<string | null>(null);

  // Receive results from upstream.
  useEffect(() => {
    if (data.input == null || data.input === '') return;
    try {
      const raw = typeof data.input === 'string' ? JSON.parse(data.input) : data.input;
      // Accept either the explicit `street_vision_results` envelope OR a bare
      // ResultItem[] (forward-compat for users wiring custom inference nodes).
      let nextResults: ResultItem[] = [];
      let nextPayload: IncomingPayload | null = null;
      if (Array.isArray(raw)) {
        nextResults = raw as ResultItem[];
        nextPayload = { results: nextResults, total_images: nextResults.length };
      } else if (raw && raw.type === 'street_vision_results' && Array.isArray(raw.results)) {
        nextResults = raw.results;
        nextPayload = raw;
      } else if (raw && Array.isArray(raw.results)) {
        nextResults = raw.results;
        nextPayload = raw;
      }
      if (nextResults.length > 0) {
        setPayload(nextPayload);
        setResults(nextResults);
        setView('gallery');
        setPushed(false);
      }
    } catch {
      // Not parseable — ignore. The waiting view stays up.
    }
  }, [data.input]);

  const imgSrc = (item: ResultItem) => {
    const raw = item.image_url || '';
    if (raw.startsWith('/api/')) return `${API_BASE.replace(/\/api\/streetvision$/, '')}${raw}`;
    return raw;
  };
  const overlayUrl = (item: ResultItem) =>
    !item.demo_mode && item.class_ratios
      ? `${API_BASE}/inference/overlay/${encodeURIComponent(item.image_id)}`
      : null;

  const aggStats = results.length > 0 ? (() => {
    const allClasses = new Map<string, number[]>();
    results.forEach(r => {
      if (r.class_ratios) {
        Object.entries(r.class_ratios).forEach(([k, v]) => {
          if (!allClasses.has(k)) allClasses.set(k, []);
          allClasses.get(k)!.push(v);
        });
      }
      if (r.object_counts) {
        Object.entries(r.object_counts).forEach(([k, v]) => {
          if (!allClasses.has(k)) allClasses.set(k, []);
          allClasses.get(k)!.push(v);
        });
      }
    });
    const averages: Record<string, number> = {};
    allClasses.forEach((vals, key) => { averages[key] = vals.reduce((a, b) => a + b, 0) / vals.length; });
    const withGeo = results.filter(r => r.latitude != null).length;
    return { averages, classCount: allClasses.size, geoCount: withGeo };
  })() : null;

  const pushDownstream = useCallback(() => {
    if (results.length === 0) return;
    setPushError(null);
    try {
      const fc = buildFeatureCollection(results);
      data.outputCallback(data.nodeId, { data: fc, dataType: 'geodataframe' });
      nodeState.setOutput({ code: 'success', content: '' });
      setPushed(true);
    } catch (e: any) {
      setPushError(`Push failed: ${e.message}`);
    }
  }, [results, data, nodeState]);

  const inspectedItem = inspectIdx !== null ? results[inspectIdx] : null;
  const isSegmentation = payload?.model_type === 'segmentation';

  const contentComponent = (
    <div style={S.root}>
      <div style={S.header}>
        <div style={S.logo}>CV</div>
        <div>
          <div style={S.title}>CV Gallery</div>
          <div style={S.sub}>Inference results inspector</div>
        </div>
        {view === 'inspect' && (
          <button style={S.link} onClick={() => { setInspectIdx(null); setView('gallery'); }}>
            ← Gallery
          </button>
        )}
      </div>

      {view === 'waiting' && (
        <div style={{ ...S.card, textAlign: 'center', padding: '24px 16px' }}>
          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.3 }}>🔍</div>
          <div style={{ fontWeight: 600, color: '#334155', marginBottom: 4 }}>Waiting for Data</div>
          <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.5 }}>
            Connect an <strong>HF CV Inference</strong> node upstream and run it.
            Results will appear here automatically.
          </div>
        </div>
      )}

      {view === 'gallery' && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            {payload?.model_type && (
              <span style={{ ...S.badge, background: '#f3e8ff', color: '#7c3aed' }}>{payload.model_type}</span>
            )}
            <span style={{ color: '#334155', fontWeight: 600 }}>
              {results.length} result{results.length !== 1 ? 's' : ''}
            </span>
          </div>

          <div style={S.tabBar}>
            {([['gallery', 'Gallery'], ['stats', 'Aggregate Stats']] as const).map(([k, label]) => (
              <button
                key={k}
                style={{ ...S.tab, ...(activeGalleryTab === k ? S.tabActive : {}) }}
                onClick={() => setActiveGalleryTab(k)}
              >
                {label}
              </button>
            ))}
          </div>

          {activeGalleryTab === 'gallery' && (
            <div style={{ ...S.grid, maxHeight: 360, overflowY: 'auto' }}>
              {results.map((item, i) => (
                <div
                  key={item.image_id || i}
                  style={S.gridCard}
                  onClick={() => { setInspectIdx(i); setInspectTab('source'); setView('inspect'); }}
                >
                  <img
                    src={imgSrc(item)} alt={item.image_id}
                    style={S.gridImg}
                    onError={e => { (e.target as HTMLImageElement).style.background = '#e2e8f0'; }}
                  />
                  <div style={S.gridInfo}>
                    <div title={item.image_id} style={{ fontWeight: 600, color: '#334155', marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.image_id && item.image_id.length > 6 ? item.image_id.slice(0, 6) + '…' : item.image_id}
                    </div>
                    {item.class_ratios && Object.entries(item.class_ratios).slice(0, 3).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 6 }}>
                        <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: CLASS_COLORS[k] || DEFAULT_COLOR, marginRight: 2, verticalAlign: 'middle' }} />
                        {k}: {(v * 100).toFixed(0)}%
                      </span>
                    ))}
                    {item.object_counts && Object.entries(item.object_counts).slice(0, 3).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 6 }}>{k}: {v}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeGalleryTab === 'stats' && aggStats && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={S.statsGrid}>
                <div style={S.statCard}><div style={S.statValue}>{results.length}</div><div style={S.statLabel}>Images</div></div>
                <div style={S.statCard}><div style={S.statValue}>{aggStats.classCount}</div><div style={S.statLabel}>Classes</div></div>
                <div style={S.statCard}><div style={S.statValue}>{aggStats.geoCount}</div><div style={S.statLabel}>Geo-located</div></div>
                <div style={S.statCard}><div style={S.statValue}>{payload?.model_type === 'segmentation' ? 'Seg' : 'Det'}</div><div style={S.statLabel}>Analysis</div></div>
              </div>
              <div>
                <div style={S.sectionLabel}>{isSegmentation ? 'Avg. Class Distribution' : 'Avg. Object Counts'}</div>
                {Object.entries(aggStats.averages)
                  .sort(([, a], [, b]) => b - a)
                  .map(([cls, avg]) => (
                    <div key={cls} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: CLASS_COLORS[cls] || DEFAULT_COLOR, flexShrink: 0 }} />
                      <span style={{ fontSize: 11, color: '#64748b', width: 70, textAlign: 'right' }}>{cls}</span>
                      <div style={{ flex: 1, height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%',
                          width: isSegmentation ? `${avg * 100}%` : `${Math.min(avg / Math.max(...Object.values(aggStats.averages)) * 100, 100)}%`,
                          background: CLASS_COLORS[cls] || DEFAULT_COLOR,
                          borderRadius: 4, transition: 'width 0.3s',
                        }} />
                      </div>
                      <span style={{ fontSize: 10, color: '#334155', width: 40, textAlign: 'right', fontWeight: 600 }}>
                        {isSegmentation ? `${(avg * 100).toFixed(1)}%` : avg.toFixed(1)}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          <button
            style={{ ...S.btn, ...(results.length > 0 ? S.btnGreen : S.btnDisabled) }}
            onClick={pushDownstream}
            disabled={results.length === 0}
          >
            {pushed ? '✓ Data Pushed — Re-push' : '▶ Push to Downstream'}
          </button>
          {pushed && !pushError && (
            <div style={{ fontSize: 10, color: '#22c55e', textAlign: 'center' }}>
              {results.length} features pushed as GEODATAFRAME
            </div>
          )}
          {pushError && (
            <div style={{ fontSize: 10, color: '#92400e', textAlign: 'center', padding: '6px 8px', background: '#fef9c3', border: '1px solid #fde68a', borderRadius: 6 }}>
              {pushError}
            </div>
          )}
        </>
      )}

      {view === 'inspect' && inspectedItem && (
        <div style={{ position: 'relative' }}>
          <div style={S.tabBar}>
            {([['source', 'Source'], ['overlay', 'CV Overlay'], ['side', 'Side by Side']] as const).map(([k, label]) => (
              <button
                key={k}
                style={{ ...S.tab, ...(inspectTab === k ? S.tabActive : {}) }}
                onClick={() => setInspectTab(k)}
              >
                {label}
              </button>
            ))}
          </div>
          <div style={{ display: inspectTab === 'side' ? 'grid' : 'block', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
            {(inspectTab === 'source' || inspectTab === 'side') && (
              <img src={imgSrc(inspectedItem)} alt="source" style={{ width: '100%', borderRadius: 6, background: '#f1f5f9' }} onError={e => { (e.target as HTMLImageElement).style.background = '#e2e8f0'; }} />
            )}
            {(inspectTab === 'overlay' || inspectTab === 'side') && (
              <div style={{ position: 'relative' }}>
                <img src={imgSrc(inspectedItem)} alt="base" style={{ width: '100%', borderRadius: 6, background: '#f1f5f9' }} onError={e => { (e.target as HTMLImageElement).style.background = '#e2e8f0'; }} />
                {overlayUrl(inspectedItem) && (
                  <img src={overlayUrl(inspectedItem)!} alt="overlay" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', mixBlendMode: 'multiply', opacity: 0.6 }} />
                )}
                {!overlayUrl(inspectedItem) && (
                  <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.25)', borderRadius: 6 }}>
                    <span style={{ color: '#fff', fontSize: 11, background: 'rgba(0,0,0,0.5)', padding: '4px 10px', borderRadius: 6 }}>
                      {inspectedItem.demo_mode ? 'Demo — no real overlay' : 'Overlay unavailable'}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
          {inspectedItem.class_ratios && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#334155', marginBottom: 4 }}>Class Breakdown</div>
              {Object.entries(inspectedItem.class_ratios)
                .sort(([, a], [, b]) => b - a)
                .map(([cls, ratio]) => (
                  <div key={cls} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 2, background: CLASS_COLORS[cls] || DEFAULT_COLOR, flexShrink: 0 }} />
                    <span style={{ fontSize: 10, color: '#64748b', width: 65, textAlign: 'right' }}>{cls}</span>
                    <div style={{ flex: 1, height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden' }}>
                      <div style={{ height: '100%', width: `${ratio * 100}%`, background: CLASS_COLORS[cls] || DEFAULT_COLOR, borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: 10, color: '#334155', width: 32, textAlign: 'right' }}>{(ratio * 100).toFixed(0)}%</span>
                  </div>
                ))}
            </div>
          )}
          {inspectedItem.object_counts && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#334155', marginBottom: 4 }}>Object Counts</div>
              {Object.entries(inspectedItem.object_counts)
                .sort(([, a], [, b]) => b - a)
                .map(([cls, count]) => (
                  <div key={cls} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#64748b', marginBottom: 2 }}>
                    <span>{cls}</span>
                    <span style={{ fontWeight: 600, color: '#334155' }}>{count}</span>
                  </div>
                ))}
            </div>
          )}
          {inspectedItem.detections && inspectedItem.detections.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#334155', marginBottom: 4 }}>Detections</div>
              <div style={{ maxHeight: 100, overflowY: 'auto' }}>
                {inspectedItem.detections.map((det, i) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#64748b', marginBottom: 2 }}>
                    <span>{det.label}</span>
                    <span style={{ ...S.badge, background: det.confidence > 0.7 ? '#dcfce7' : '#fef9c3', color: det.confidence > 0.7 ? '#166534' : '#92400e' }}>
                      {(det.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div style={{ marginTop: 8, fontSize: 10, color: '#94a3b8' }}>
            {inspectedItem.image_id}
            {inspectedItem.latitude != null && ` · ${inspectedItem.latitude.toFixed(4)}, ${inspectedItem.longitude?.toFixed(4)}`}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
            <button
              style={{ ...S.link, marginLeft: 0, opacity: inspectIdx! > 0 ? 1 : 0.3 }}
              onClick={() => inspectIdx! > 0 && setInspectIdx(inspectIdx! - 1)}
              disabled={inspectIdx === 0}
            >← Prev</button>
            <button style={S.link} onClick={() => { setInspectIdx(null); setView('gallery'); }}>Back to Gallery</button>
            <button
              style={{ ...S.link, marginLeft: 0, opacity: inspectIdx! < results.length - 1 ? 1 : 0.3 }}
              onClick={() => inspectIdx! < results.length - 1 && setInspectIdx(inspectIdx! + 1)}
              disabled={inspectIdx === results.length - 1}
            >Next →</button>
          </div>
        </div>
      )}
    </div>
  );

  return { contentComponent };
};
