import React, { useState, useEffect, useCallback } from 'react';
import { NodeLifecycleHook } from '../../registry/types';

const API_BASE = 'http://localhost:5002/api/streetvision';

// ─── Types ──────────────────────────────────────────────────────────
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
  type: string;
  job_id: string;
  model_type: string;
  total_images: number;
  results: ResultItem[];
}

type View = 'waiting' | 'gallery' | 'inspect';

// ─── Cityscapes color palette ───────────────────────────────────────
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

// ─── Styles ─────────────────────────────────────────────────────────
const S: Record<string, React.CSSProperties> = {
  root: {
    padding: '12px 14px',
    fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
    fontSize: 13, color: '#333',
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 },
  logo: {
    width: 28, height: 28, borderRadius: 6,
    background: 'linear-gradient(135deg,#8b5cf6,#a78bfa)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#fff', fontSize: 14, fontWeight: 700, flexShrink: 0,
  },
  title: { fontSize: 14, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.2 },
  sub: { fontSize: 10, color: '#888', marginTop: 1 },
  link: {
    background: 'none', border: 'none', color: '#8b5cf6',
    fontSize: 11, fontWeight: 600, cursor: 'pointer', marginLeft: 'auto', padding: '4px 8px',
  },
  btn: {
    padding: '8px 12px', border: 'none', borderRadius: 8, fontSize: 12,
    fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', gap: 6, transition: 'all 0.15s', width: '100%',
  },
  btnPrimary: { background: 'linear-gradient(135deg,#8b5cf6,#7c3aed)', color: '#fff' },
  btnGreen: { background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0' },
  btnDisabled: { background: '#f3f4f6', color: '#9ca3af', border: '1px solid #e5e7eb', cursor: 'not-allowed' },
  card: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', fontSize: 12 },
  badge: { display: 'inline-block', padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600 },
  sectionLabel: { fontSize: 10, fontWeight: 600, textTransform: 'uppercase' as const, color: '#94a3b8', letterSpacing: 1, marginBottom: 4 },
  // Gallery grid
  grid: { display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, marginTop: 6 },
  gridCard: {
    border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden',
    cursor: 'pointer', transition: 'box-shadow 0.15s', background: '#fff',
  },
  gridImg: { width: '100%', height: 90, objectFit: 'cover' as const, display: 'block', background: '#f1f5f9' },
  gridInfo: { padding: '6px 8px', fontSize: 10, color: '#64748b' },
  // Tabs
  tabBar: { display: 'flex', gap: 2, marginBottom: 10 },
  tab: {
    padding: '5px 10px', fontSize: 11, fontWeight: 500, cursor: 'pointer',
    border: 'none', borderBottom: '2px solid transparent', background: 'none', color: '#64748b',
  },
  tabActive: { borderBottomColor: '#8b5cf6', color: '#8b5cf6', fontWeight: 600 },
  // Stats
  statsGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6, marginTop: 6,
  },
  statCard: {
    background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8,
    padding: '8px 10px', textAlign: 'center' as const,
  },
  statValue: { fontSize: 18, fontWeight: 700, color: '#1a1a2e' },
  statLabel: { fontSize: 9, color: '#94a3b8', textTransform: 'uppercase' as const, marginTop: 2 },
};

/**
 * CV Analysis lifecycle hook — Visualization & Analysis node.
 *
 * Receives inference results from Street Vision node.
 * Displays: gallery, overlays, class breakdowns, aggregate stats.
 * Pushes structured data downstream for Vega-Lite / UTK nodes.
 */
export const useCvAnalysisLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [view, setView] = useState<View>('waiting');
  const [payload, setPayload] = useState<IncomingPayload | null>(null);
  const [results, setResults] = useState<ResultItem[]>([]);
  const [inspectIdx, setInspectIdx] = useState<number | null>(null);
  const [inspectTab, setInspectTab] = useState<'source' | 'overlay' | 'side'>('source');
  const [pushed, setPushed] = useState(false);
  const [activeGalleryTab, setActiveGalleryTab] = useState<'gallery' | 'stats'>('gallery');

  // ── Receive input from upstream Street Vision node ──────────────────
  useEffect(() => {
    if (data.input == null || data.input === '') return;
    try {
      const raw = typeof data.input === 'string' ? JSON.parse(data.input) : data.input;
      if (raw.type === 'street_vision_results' && raw.results) {
        setPayload(raw);
        setResults(raw.results);
        setView('gallery');
        setPushed(false);
      }
    } catch {
      // Not valid JSON — ignore
    }
  }, [data.input]);

  // ── Image helpers ───────────────────────────────────────────────────
  const imgSrc = (item: ResultItem) => {
    const raw = item.image_url || '';
    if (raw.startsWith('/api/'))
      return `${API_BASE}/${raw.slice(5)}`;
    return raw;
  };

  const overlayUrl = (item: ResultItem) =>
    !item.demo_mode && item.class_ratios
      ? `${API_BASE}/inference/overlay/${encodeURIComponent(item.image_id)}`
      : null;

  // ── Compute aggregate stats ─────────────────────────────────────────
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
    allClasses.forEach((vals, key) => {
      averages[key] = vals.reduce((a, b) => a + b, 0) / vals.length;
    });
    const withGeo = results.filter(r => r.latitude != null).length;
    return { averages, classCount: allClasses.size, geoCount: withGeo };
  })() : null;

  // ── Push data downstream (for Vega-Lite / UTK) ─────────────────────
  const [pushError, setPushError] = useState<string | null>(null);

  const buildFeatureCollection = useCallback(() => {
    // GeoJSON FeatureCollection — matches what Curio's parseGeoDataframe expects.
    // Properties are formatted for the Table view: lat/lon rounded, class
    // ratios converted to percent (0-100, 1 decimal), image_url omitted as
    // visual noise. Vega-Lite reads the same percent values via .0 axis format.
    const round = (n: number | null | undefined, places: number) =>
      n == null ? null : Number(n.toFixed(places));

    // Collect the union of all class keys across rows so the Table doesn't
    // show "null" for a class that simply wasn't detected in one image.
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
        latitude: lat,
        longitude: lon,
      };
      // Ensure every class column exists on every row, defaulting to 0.
      allClassKeys.forEach(k => { props[k] = 0; });
      if (r.class_ratios) {
        Object.entries(r.class_ratios).forEach(([k, v]) => {
          props[k] = round((v as number) * 100, 1);
        });
        props.analysis_type = 'segmentation';
      }
      if (r.object_counts) {
        Object.entries(r.object_counts).forEach(([k, v]) => { props[k] = v; });
        props.analysis_type = 'detection';
      }
      // Compute dominant class (highest-percentage class) — used by the
      // Map View template for color encoding and as a useful Table column.
      let dominantClass: string | null = null;
      let dominantPct = -Infinity;
      allClassKeys.forEach(k => {
        const v = props[k] as number;
        if (typeof v === 'number' && v > dominantPct) {
          dominantPct = v;
          dominantClass = k;
        }
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
      metadata: { name: 'street_vision_results' },
    };
  }, [results]);

  // Best-effort enrichment: tag each point with its Chicago neighborhood and
  // attach per-neighborhood aggregates (used by the Map View polygon coloring
  // and the Linked template's vconcat). Falls back gracefully — if the
  // endpoint is down or the points are outside Chicago, we still push the
  // base FC so Vega-Lite + Table keep working.
  const enrichWithNeighborhoods = useCallback(async (fc: any) => {
    const points = fc.features.map((f: any) => ({
      latitude: f.properties?.latitude ?? null,
      longitude: f.properties?.longitude ?? null,
      image_id: f.properties?.image_id ?? null,
      dominant_class: f.properties?.dominant_class ?? null,
      dominant_pct: f.properties?.dominant_pct ?? null,
    }));
    try {
      const res = await fetch(`${API_BASE}/data/basemap/enrich_with_neighborhoods`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ points }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      const enriched = body.points || [];
      fc.features.forEach((f: any, i: number) => {
        const e = enriched[i];
        if (!e) return;
        f.properties.neighborhood_name = e.neighborhood_name ?? null;
        f.properties.nbhd_dominant_class = e.nbhd_dominant_class ?? null;
        f.properties.nbhd_dominant_pct = e.nbhd_dominant_pct ?? null;
        f.properties.nbhd_image_count = e.nbhd_image_count ?? null;
      });
      // Stash aggregates on metadata for any downstream consumer that wants them.
      fc.metadata = { ...(fc.metadata || {}), aggregates: body.aggregates || [] };
      return fc;
    } catch (err: any) {
      // Silent fallback — Map View polygons will just stay flat-fill,
      // bar/table still render fine.
      return fc;
    }
  }, []);

  const pushDownstream = useCallback(async () => {
    if (!payload) return;
    setPushError(null);

    // Push the FeatureCollection inline. Both Vega-Lite (parses
    // parsedInput.data when path is absent) and Table (only reads
    // parsedOutput.data.features) consume this shape directly — no .data
    // file write or fetch round-trip needed at our scale (≤200 rows).
    try {
      const fc = buildFeatureCollection();
      const enriched = await enrichWithNeighborhoods(fc);
      data.outputCallback(data.nodeId, {
        data: enriched,
        dataType: 'geodataframe',
      });
      setPushed(true);
      // Mark this node as successfully completed so playNodesUpTo from a
      // downstream Vega-Lite Play does not re-trigger us.
      nodeState.setOutput({ code: 'success', content: '' });
    } catch (e: any) {
      setPushError(`Push failed: ${e.message}`);
    }
  }, [payload, data, buildFeatureCollection, enrichWithNeighborhoods, nodeState]);

  // ── Inspected item ──────────────────────────────────────────────────
  const inspectedItem = inspectIdx !== null ? results[inspectIdx] : null;
  const isSegmentation = payload?.model_type === 'segmentation';

  // ══════════════════════════════════════════════════════════════════════
  //  RENDER
  // ══════════════════════════════════════════════════════════════════════
  const contentComponent = (
    <div style={S.root}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.logo}>CV</div>
        <div>
          <div style={S.title}>CV Analysis</div>
          <div style={S.sub}>Results &amp; visualization</div>
        </div>
        {view === 'inspect' && (
          <button style={S.link} onClick={() => { setInspectIdx(null); setView('gallery'); }}>
            &#8592; Gallery
          </button>
        )}
      </div>

      {/* ═══════ WAITING VIEW ═════════════════════════════════════ */}
      {view === 'waiting' && (
        <div style={{ ...S.card, textAlign: 'center', padding: '24px 16px' }}>
          <div style={{ fontSize: 32, marginBottom: 8, opacity: 0.3 }}>&#128269;</div>
          <div style={{ fontWeight: 600, color: '#334155', marginBottom: 4 }}>
            Waiting for Data
          </div>
          <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.5 }}>
            Connect a <strong>Street Vision</strong> node upstream and run analysis.
            Results will appear here automatically.
          </div>
        </div>
      )}

      {/* ═══════ GALLERY VIEW ═════════════════════════════════════ */}
      {view === 'gallery' && (
        <>
          {/* Info bar */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <span style={{ ...S.badge, background: '#f3e8ff', color: '#7c3aed' }}>
              {payload?.model_type}
            </span>
            <span style={{ color: '#334155', fontWeight: 600 }}>
              {results.length} result{results.length !== 1 ? 's' : ''}
            </span>
          </div>

          {/* Gallery / Stats tabs */}
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
                    src={imgSrc(item)}
                    alt={item.image_id}
                    style={S.gridImg}
                    onError={e => { (e.target as HTMLImageElement).style.background = '#e2e8f0'; }}
                  />
                  <div style={S.gridInfo}>
                    {/* Display only — first 6 chars + ellipsis. Full ID stays
                        in the underlying data and the hover tooltip. */}
                    <div
                      title={item.image_id}
                      style={{ fontWeight: 600, color: '#334155', marginBottom: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}
                    >
                      {item.image_id && item.image_id.length > 6
                        ? item.image_id.slice(0, 6) + '…'
                        : item.image_id}
                    </div>
                    {item.class_ratios && Object.entries(item.class_ratios).slice(0, 3).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 6 }}>
                        <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: CLASS_COLORS[k] || DEFAULT_COLOR, marginRight: 2, verticalAlign: 'middle' }} />
                        {k}: {(v * 100).toFixed(0)}%
                      </span>
                    ))}
                    {item.object_counts && Object.entries(item.object_counts).slice(0, 3).map(([k, v]) => (
                      <span key={k} style={{ marginRight: 6 }}>
                        {k}: {v}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeGalleryTab === 'stats' && aggStats && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {/* Summary cards */}
              <div style={S.statsGrid}>
                <div style={S.statCard}>
                  <div style={S.statValue}>{results.length}</div>
                  <div style={S.statLabel}>Images</div>
                </div>
                <div style={S.statCard}>
                  <div style={S.statValue}>{aggStats.classCount}</div>
                  <div style={S.statLabel}>Classes</div>
                </div>
                <div style={S.statCard}>
                  <div style={S.statValue}>{aggStats.geoCount}</div>
                  <div style={S.statLabel}>Geo-located</div>
                </div>
                <div style={S.statCard}>
                  <div style={S.statValue}>{payload?.model_type === 'segmentation' ? 'Seg' : 'Det'}</div>
                  <div style={S.statLabel}>Analysis</div>
                </div>
              </div>

              {/* Average class distribution bar chart */}
              <div>
                <div style={S.sectionLabel}>
                  {isSegmentation ? 'Avg. Class Distribution' : 'Avg. Object Counts'}
                </div>
                {Object.entries(aggStats.averages)
                  .sort(([, a], [, b]) => b - a)
                  .map(([cls, avg]) => (
                    <div key={cls} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <span style={{
                        display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                        background: CLASS_COLORS[cls] || DEFAULT_COLOR, flexShrink: 0,
                      }} />
                      <span style={{ fontSize: 11, color: '#64748b', width: 70, textAlign: 'right' }}>{cls}</span>
                      <div style={{ flex: 1, height: 8, background: '#e2e8f0', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%',
                          width: isSegmentation ? `${avg * 100}%` : `${Math.min(avg / Math.max(...Object.values(aggStats.averages)) * 100, 100)}%`,
                          background: CLASS_COLORS[cls] || DEFAULT_COLOR,
                          borderRadius: 4,
                          transition: 'width 0.3s',
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

          {/* Push downstream */}
          <button
            style={{ ...S.btn, ...(results.length > 0 ? S.btnGreen : S.btnDisabled) }}
            onClick={pushDownstream}
            disabled={results.length === 0}
          >
            {pushed ? '✓ Data Pushed — Re-push' : '▶ Push to Visualization Nodes'}
          </button>

          {pushed && !pushError && (
            <div style={{ fontSize: 10, color: '#22c55e', textAlign: 'center' }}>
              {results.length} features pushed to downstream Vega-Lite / UTK nodes
            </div>
          )}
          {pushError && (
            <div style={{ fontSize: 10, color: '#92400e', textAlign: 'center', padding: '6px 8px', background: '#fef9c3', border: '1px solid #fde68a', borderRadius: 6 }}>
              {pushError}
            </div>
          )}
        </>
      )}

      {/* ═══════ INSPECT VIEW ═════════════════════════════════════ */}
      {view === 'inspect' && inspectedItem && (
        <div style={{ position: 'relative' as const }}>
          {/* Tab bar */}
          <div style={S.tabBar}>
            {([['source', 'Source'], ['overlay', 'CV Overlay'], ['side', 'Side by Side']] as const).map(([k, label]) => (
              <button
                key={k}
                style={{ ...S.tab, ...(inspectTab === k ? { ...S.tabActive, borderBottomColor: '#8b5cf6', color: '#8b5cf6' } : {}) }}
                onClick={() => setInspectTab(k)}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Images */}
          <div style={{ display: inspectTab === 'side' ? 'grid' : 'block', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
            {(inspectTab === 'source' || inspectTab === 'side') && (
              <img
                src={imgSrc(inspectedItem)}
                alt="source"
                style={{ width: '100%', borderRadius: 6, background: '#f1f5f9' }}
                onError={e => { (e.target as HTMLImageElement).style.background = '#e2e8f0'; }}
              />
            )}
            {(inspectTab === 'overlay' || inspectTab === 'side') && (
              <div style={{ position: 'relative' as const }}>
                <img
                  src={imgSrc(inspectedItem)}
                  alt="base"
                  style={{ width: '100%', borderRadius: 6, background: '#f1f5f9' }}
                  onError={e => { (e.target as HTMLImageElement).style.background = '#e2e8f0'; }}
                />
                {overlayUrl(inspectedItem) && (
                  <img
                    src={overlayUrl(inspectedItem)!}
                    alt="overlay"
                    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'contain', mixBlendMode: 'multiply', opacity: 0.6 }}
                  />
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

          {/* Class breakdown */}
          {inspectedItem.class_ratios && (
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#334155', marginBottom: 4 }}>Class Breakdown</div>
              {Object.entries(inspectedItem.class_ratios)
                .sort(([, a], [, b]) => b - a)
                .map(([cls, ratio]) => (
                  <div key={cls} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                    <span style={{
                      display: 'inline-block', width: 8, height: 8, borderRadius: 2,
                      background: CLASS_COLORS[cls] || DEFAULT_COLOR, flexShrink: 0,
                    }} />
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

          {/* Detection details */}
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

          {/* Metadata */}
          <div style={{ marginTop: 8, fontSize: 10, color: '#94a3b8' }}>
            {inspectedItem.image_id}
            {inspectedItem.latitude != null && ` · ${inspectedItem.latitude.toFixed(4)}, ${inspectedItem.longitude?.toFixed(4)}`}
          </div>

          {/* Nav */}
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
            <button
              style={{ ...S.link, marginLeft: 0, opacity: inspectIdx! > 0 ? 1 : 0.3 }}
              onClick={() => inspectIdx! > 0 && setInspectIdx(inspectIdx! - 1)}
              disabled={inspectIdx === 0}
            >
              &#8592; Prev
            </button>
            <button style={S.link} onClick={() => { setInspectIdx(null); setView('gallery'); }}>
              Back to Gallery
            </button>
            <button
              style={{ ...S.link, marginLeft: 0, opacity: inspectIdx! < results.length - 1 ? 1 : 0.3 }}
              onClick={() => inspectIdx! < results.length - 1 && setInspectIdx(inspectIdx! + 1)}
              disabled={inspectIdx === results.length - 1}
            >
              Next &#8594;
            </button>
          </div>
        </div>
      )}
    </div>
  );

  return { contentComponent };
};
