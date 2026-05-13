import React, { useState, useEffect, useCallback, useRef } from 'react';
import { NodeLifecycleHook } from '../../registry/types';

const API_BASE = 'http://localhost:5002/api/streetvision';

// ─── Types ──────────────────────────────────────────────────────────
type ModelType = 'segmentation' | 'detection';

interface ModelSearchResult {
  model_id: string;
  name: string;
  downloads: number;
  task: string;
}

interface ModelInfo {
  model_id: string;
  model_type: ModelType;
  name: string;
  description: string;
}

interface DataSourceConfig {
  source_type: string;
  folder_path?: string;
  bbox?: number[];
  limit: number;
}

interface InferenceRequest {
  model: ModelInfo;
  data_source: DataSourceConfig;
  classes: { classes: string[]; source: string };
}

interface ResultItem {
  image_id: string;
  image_url: string;
  latitude?: number;
  longitude?: number;
  class_ratios?: Record<string, number>;
  object_counts?: Record<string, number>;
  demo_mode?: boolean;
}

// ─── Views ──────────────────────────────────────────────────────────
type View = 'config' | 'running' | 'done';

const CLASS_SUGGESTIONS = [
  'building', 'road', 'sidewalk', 'vegetation',
  'pole', 'fence', 'wall', 'traffic sign',
];

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
    background: 'linear-gradient(135deg,#3b82f6,#60a5fa)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#fff', fontSize: 14, fontWeight: 700, flexShrink: 0,
  },
  title: { fontSize: 14, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.2 },
  sub: { fontSize: 10, color: '#888', marginTop: 1 },
  row: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#666' },
  dot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  btn: {
    padding: '8px 12px', border: 'none', borderRadius: 8, fontSize: 12,
    fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', gap: 6, transition: 'all 0.15s', width: '100%',
  },
  btnPrimary: { background: 'linear-gradient(135deg,#3b82f6,#2563eb)', color: '#fff' },
  btnGreen: { background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0' },
  btnDisabled: { background: '#f3f4f6', color: '#9ca3af', border: '1px solid #e5e7eb', cursor: 'not-allowed' },
  card: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', fontSize: 12 },
  input: {
    width: '100%', padding: '7px 10px', border: '1px solid #e2e8f0', borderRadius: 6,
    fontSize: 12, outline: 'none', boxSizing: 'border-box' as const,
  },
  sectionLabel: { fontSize: 10, fontWeight: 600, textTransform: 'uppercase' as const, color: '#94a3b8', letterSpacing: 1, marginBottom: 4 },
  progressOuter: { height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden', marginTop: 6 },
  progressFill: { height: '100%', background: 'linear-gradient(90deg,#3b82f6,#60a5fa)', borderRadius: 3, transition: 'width 0.3s' },
  chip: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '3px 8px', borderRadius: 12, fontSize: 11, cursor: 'pointer',
    border: '1px solid #e2e8f0', background: '#fff', transition: 'all 0.15s',
  },
  chipActive: { background: '#eff6ff', borderColor: '#93c5fd', color: '#1d4ed8' },
  badge: { display: 'inline-block', padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 600 },
  link: {
    background: 'none', border: 'none', color: '#3b82f6',
    fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: '4px 8px',
  },
  summaryRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '6px 0', borderBottom: '1px solid #f1f5f9', fontSize: 12,
  },
};

/**
 * Street Vision lifecycle hook — Data Acquisition & Inference node.
 *
 * Handles: place/data selection, model selection, class selection, inference.
 * Pushes results downstream to CV Analysis node.
 */
export const useStreetVisionLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [view, setView] = useState<View>('config');

  // ── Backend health ──────────────────────────────────────────────────
  const [backendUp, setBackendUp] = useState(false);
  const [hasGoogleKey, setHasGoogleKey] = useState(false);

  // ── Config state ────────────────────────────────────────────────────
  const [task, setTask] = useState<ModelType>('segmentation');
  const [query, setQuery] = useState('cityscapes');
  const [models, setModels] = useState<ModelSearchResult[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [selectedModel, setSelectedModel] = useState<ModelInfo | null>(null);
  const [autoPick, setAutoPick] = useState(true);
  const userPickedRef = useRef(false);
  const [dataSource, setDataSource] = useState<DataSourceConfig>({
    source_type: 'google_streetview', bbox: [-87.66, 41.91, -87.62, 41.94], limit: 20,
  });
  const [selectedClasses, setSelectedClasses] = useState<string[]>([]);
  const [gsvLocation, setGsvLocation] = useState('');
  const [gsvBbox, setGsvBbox] = useState<number[] | null>(null);
  const [gsvCoverage, setGsvCoverage] = useState<number | null>(null);
  const [gsvLimit, setGsvLimit] = useState(20);

  // ── Inference state ─────────────────────────────────────────────────
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobRunning, setJobRunning] = useState(false);
  const [processed, setProcessed] = useState(0);
  const [totalImages, setTotalImages] = useState(0);
  const [jobError, setJobError] = useState<string | null>(null);
  const [results, setResults] = useState<ResultItem[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  // ── Push state ──────────────────────────────────────────────────────
  const [pushed, setPushed] = useState(false);

  // ── Health check ────────────────────────────────────────────────────
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/health`).then(r => r.json())
        .then(d => { setBackendUp(true); setHasGoogleKey(!!d.has_google_api_key); })
        .catch(() => setBackendUp(false));
    };
    check();
    const iv = setInterval(check, 10000);
    return () => clearInterval(iv);
  }, []);

  // ── Model search (debounced) ────────────────────────────────────────
  useEffect(() => {
    if (query.length < 2) return;
    const t = setTimeout(() => {
      setModelsLoading(true);
      fetch(`${API_BASE}/models/search?task=${task}&query=${encodeURIComponent(query)}`)
        .then(r => r.json())
        .then(d => {
          const list = d.models ?? [];
          setModels(list);
          // Auto-pick top match if enabled and user hasn't manually overridden
          if (autoPick && !userPickedRef.current && list.length > 0) {
            const top = list[0];
            setSelectedModel({ model_id: top.model_id, model_type: task, name: top.name, description: '' });
          }
        })
        .catch(() => setModels([]))
        .finally(() => setModelsLoading(false));
    }, 400);
    return () => clearTimeout(t);
  }, [task, query, autoPick]);

  // Reset manual-override flag when task changes (different task → re-auto-pick top)
  useEffect(() => {
    userPickedRef.current = false;
  }, [task]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = undefined; }
  }, []);

  // ── Push results downstream ─────────────────────────────────────────
  const pushResults = useCallback((jobResults: ResultItem[], jid: string) => {
    const payload = JSON.stringify({
      type: 'street_vision_results',
      job_id: jid,
      model_type: task,
      total_images: jobResults.length,
      results: jobResults,
    });
    data.outputCallback(data.nodeId, payload);
    setPushed(true);
    // Mark node as successfully completed so playNodesUpTo from a downstream
    // node (e.g. Vega-Lite Play) does not re-trigger us.
    nodeState.setOutput({ code: 'success', content: '' });
  }, [data, task, nodeState]);

  // ── Run inference ───────────────────────────────────────────────────
  const handleRun = useCallback(() => {
    if (!selectedModel || selectedClasses.length === 0) return;
    const req: InferenceRequest = {
      model: selectedModel,
      data_source: dataSource,
      classes: { classes: selectedClasses, source: 'prompt' },
    };
    setJobError(null);
    setResults([]);
    setProcessed(0);
    setTotalImages(dataSource.limit);
    setJobRunning(true);
    setPushed(false);
    setView('running');

    fetch(`${API_BASE}/inference/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
      .then(r => r.json())
      .then(d => {
        setJobId(d.job_id);
        pollRef.current = setInterval(() => {
          fetch(`${API_BASE}/inference/results/${d.job_id}`)
            .then(r => r.json())
            .then(s => {
              setProcessed(s.processed);
              setTotalImages(s.total_images);
              if (s.results?.length) setResults(s.results);
              if (s.status === 'completed' || s.status === 'failed') {
                stopPolling();
                setJobRunning(false);
                if (s.status === 'failed') {
                  setJobError(s.error || 'Inference failed.');
                } else {
                  setView('done');
                  // Auto-push results downstream
                  pushResults(s.results, d.job_id);
                }
              }
            })
            .catch(() => {
              stopPolling();
              setJobRunning(false);
              setJobError('Lost connection to backend.');
            });
        }, 2000);
      })
      .catch(e => {
        setJobRunning(false);
        setJobError(e.message || 'Failed to start inference.');
      });
  }, [selectedModel, selectedClasses, dataSource, stopPolling, pushResults]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // ── Helpers ─────────────────────────────────────────────────────────
  const fmtDl = (n: number) => n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
  const pct = totalImages > 0 ? Math.round((processed / totalImages) * 100) : 0;
  const allReady = !!selectedModel && selectedClasses.length > 0;
  const statusColor = backendUp ? '#22c55e' : '#ef4444';
  const statusText = backendUp ? 'Backend connected' : 'Backend offline';

  const toggleClass = (cls: string) => {
    setSelectedClasses(prev =>
      prev.includes(cls) ? prev.filter(c => c !== cls) : [...prev, cls],
    );
  };

  // ── CSV import for target classes ───────────────────────────────────
  // Accepts a single-column CSV. Auto-detects a header row by checking if the
  // first non-empty cell looks more like a column header ("class", "label",
  // "name", "category") than a class value. Deduplicates against existing
  // selections; surfaces a status message inline.
  const csvInputRef = useRef<HTMLInputElement>(null);
  const [csvStatus, setCsvStatus] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);

  const handleCsvImport = (file: File) => {
    setCsvStatus(null);
    const reader = new FileReader();
    reader.onerror = () => setCsvStatus({ kind: 'err', msg: 'Could not read file.' });
    reader.onload = (e) => {
      try {
        const text = String(e.target?.result ?? '').replace(/\r/g, '');
        // Pull the first non-empty cell of every line — handles single-column
        // CSVs and the first column of multi-column CSVs gracefully.
        const lines = text.split('\n').map(l => l.split(',')[0].trim()).filter(Boolean);
        if (lines.length === 0) {
          setCsvStatus({ kind: 'err', msg: 'CSV is empty.' });
          return;
        }
        const headerHints = ['class', 'classes', 'label', 'labels', 'name', 'category'];
        const skipHeader = headerHints.includes(lines[0].toLowerCase());
        const candidates = (skipHeader ? lines.slice(1) : lines)
          .map(s => s.replace(/^["']|["']$/g, '').trim())
          .filter(s => s.length > 0 && s.length <= 64);
        if (candidates.length === 0) {
          setCsvStatus({ kind: 'err', msg: 'No usable class names found in CSV.' });
          return;
        }
        // Deduplicate against existing selections (case-insensitive).
        const existingLower = new Set(selectedClasses.map(c => c.toLowerCase()));
        const fresh: string[] = [];
        const seenLower = new Set<string>();
        for (const c of candidates) {
          const k = c.toLowerCase();
          if (existingLower.has(k) || seenLower.has(k)) continue;
          seenLower.add(k);
          fresh.push(c);
        }
        if (fresh.length === 0) {
          setCsvStatus({ kind: 'ok', msg: 'No new classes to import (all duplicates).' });
          return;
        }
        setSelectedClasses(prev => [...prev, ...fresh]);
        setCsvStatus({ kind: 'ok', msg: `Imported ${fresh.length} class${fresh.length > 1 ? 'es' : ''}.` });
      } catch (err: any) {
        setCsvStatus({ kind: 'err', msg: `Parse error: ${err?.message || 'unknown'}.` });
      }
    };
    reader.readAsText(file);
  };

  // ── Compute summary stats for done view ─────────────────────────────
  const summaryStats = results.length > 0 ? (() => {
    const classKeys = new Set<string>();
    results.forEach(r => {
      if (r.class_ratios) Object.keys(r.class_ratios).forEach(k => classKeys.add(k));
      if (r.object_counts) Object.keys(r.object_counts).forEach(k => classKeys.add(k));
    });
    const withGeo = results.filter(r => r.latitude != null).length;
    return { classCount: classKeys.size, geoCount: withGeo };
  })() : null;

  // ══════════════════════════════════════════════════════════════════════
  //  RENDER
  // ══════════════════════════════════════════════════════════════════════
  const contentComponent = (
    <div style={S.root}>
      {/* Header */}
      <div style={S.header}>
        <div style={S.logo}>SV</div>
        <div>
          <div style={S.title}>Street Vision</div>
          <div style={S.sub}>Data acquisition &amp; inference</div>
        </div>
        {view === 'done' && (
          <button style={{ ...S.link, marginLeft: 'auto' }} onClick={() => setView('config')}>
            &#8592; Reconfigure
          </button>
        )}
      </div>

      {/* Connection status */}
      <div style={S.row}>
        <div style={{ ...S.dot, background: statusColor }} />
        {statusText}
      </div>

      {/* ═══════ CONFIG VIEW ═══════════════════════════════════════ */}
      {view === 'config' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Step 1: Model */}
          <div>
            <div style={S.sectionLabel}>1 &middot; Select Model</div>

            {selectedModel && (
              <div style={{ ...S.card, background: '#eff6ff', borderColor: '#93c5fd', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: '#22c55e' }}>✓</span>
                <span style={{ fontSize: 12, color: '#1e40af', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const }}>{selectedModel.name}</span>
                <span style={{ ...S.badge, background: '#dbeafe', color: '#1d4ed8' }}>{selectedModel.model_type}</span>
              </div>
            )}

            <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
              {(['segmentation', 'detection'] as ModelType[]).map(t => (
                <button key={t} onClick={() => setTask(t)} style={{
                  ...S.btn, width: 'auto', flex: 1, fontSize: 11, padding: '5px 0',
                  ...(task === t ? S.btnPrimary : { background: '#f1f5f9', color: '#64748b', border: '1px solid #e2e8f0' }),
                }}>
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>

            <input
              style={S.input}
              value={query}
              onChange={e => { userPickedRef.current = false; setQuery(e.target.value); }}
              placeholder="Search HuggingFace models..."
            />

            <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 11, color: '#475569', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={autoPick}
                onChange={e => {
                  setAutoPick(e.target.checked);
                  if (e.target.checked) {
                    userPickedRef.current = false;
                    if (models.length > 0) {
                      const top = models[0];
                      setSelectedModel({ model_id: top.model_id, model_type: task, name: top.name, description: '' });
                    }
                  }
                }}
              />
              Auto-pick best model (top HuggingFace match by downloads)
            </label>

            <div style={{ maxHeight: 150, overflowY: 'auto', marginTop: 6 }}>
              {modelsLoading && <div style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', padding: 8 }}>Searching...</div>}
              {!modelsLoading && models.length === 0 && query.length >= 2 && (
                <div style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', padding: 8 }}>No models found</div>
              )}
              {models.map(m => {
                const sel = selectedModel?.model_id === m.model_id;
                return (
                  <div
                    key={m.model_id}
                    onClick={() => {
                      userPickedRef.current = true;
                      setSelectedModel({ model_id: m.model_id, model_type: task, name: m.name, description: '' });
                    }}
                    style={{
                      padding: '6px 8px', borderRadius: 6, cursor: 'pointer', marginBottom: 2,
                      background: sel ? '#eff6ff' : 'transparent',
                      border: sel ? '1px solid #93c5fd' : '1px solid transparent',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                      <span style={{ color: '#334155', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const, flex: 1 }}>{m.name}</span>
                      <span style={{ color: '#94a3b8', fontSize: 10, marginLeft: 6, flexShrink: 0 }}>&#x2B07; {fmtDl(m.downloads)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Step 2: Data Source */}
          <div>
            <div style={S.sectionLabel}>2 &middot; Data Source (Google Street View)</div>
            {!hasGoogleKey && (
              <div style={{ ...S.card, color: '#92400e', background: '#fef9c3', borderColor: '#fde68a', fontSize: 11 }}>
                Google Maps API key required. Set GOOGLE_MAPS_API_KEY in backend .env.
              </div>
            )}
            {hasGoogleKey && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <input
                  style={S.input}
                  value={gsvLocation}
                  onChange={e => setGsvLocation(e.target.value)}
                  placeholder="Search location (e.g. Manhattan, NYC)"
                />
                <div style={{ display: 'flex', gap: 4 }}>
                  <input
                    style={{ ...S.input, width: 70 }}
                    type="number"
                    // Show empty when value is 0 so the user can clear and
                    // retype without the input snapping back mid-edit.
                    value={gsvLimit > 0 ? gsvLimit : ''}
                    onChange={e => {
                      const v = e.target.value;
                      if (v === '') { setGsvLimit(0); return; }
                      const n = parseInt(v, 10);
                      if (!isNaN(n)) setGsvLimit(n);
                    }}
                    onBlur={() => {
                      // Snap into 1..100 only when the user finishes editing.
                      if (gsvLimit < 1) setGsvLimit(20);
                      else if (gsvLimit > 100) setGsvLimit(100);
                    }}
                    min={1} max={100}
                  />
                  <button style={{ ...S.btn, width: 'auto', flex: 1, fontSize: 11, padding: '5px 8px', background: '#f1f5f9', color: '#334155', border: '1px solid #e2e8f0' }}
                    onClick={() => {
                      fetch(`${API_BASE}/data/streetview/search_place?query=${encodeURIComponent(gsvLocation)}`)
                        .then(r => r.json())
                        .then(d => {
                          if (!d.bbox) return;
                          // Auto-expand tiny bboxes (single-address geocodes
                          // return bboxes ~10 m across, which leaves all
                          // points overlapping on a city-scale map). If the
                          // bbox is smaller than ~0.005° (~500 m), pad it
                          // out around the geocoded center so we sample a
                          // walkable neighborhood instead of one building.
                          let bbox: number[] = d.bbox;
                          const [w, s, e, n] = bbox;
                          const lonSpan = e - w;
                          const latSpan = n - s;
                          if (lonSpan < 0.005 || latSpan < 0.005) {
                            const cx = typeof d.lon === 'number' ? d.lon : (w + e) / 2;
                            const cy = typeof d.lat === 'number' ? d.lat : (s + n) / 2;
                            const pad = 0.005; // ~500 m at Chicago latitude
                            bbox = [cx - pad, cy - pad, cx + pad, cy + pad];
                          }
                          setGsvBbox(bbox);
                          setDataSource({ source_type: 'google_streetview', bbox, limit: gsvLimit });
                          fetch(`${API_BASE}/data/streetview/coverage`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ bbox, limit: gsvLimit }),
                          }).then(r => r.json()).then(c => setGsvCoverage(c.estimated_count)).catch(() => {});
                        }).catch(() => {});
                    }}
                  >
                    Verify Coverage
                  </button>
                </div>
                {gsvCoverage !== null && (
                  <div style={{ ...S.card, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ color: '#22c55e' }}>✓</span>
                    <span style={{ fontSize: 12, color: '#334155' }}>
                      ~{gsvCoverage} images available
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Step 3: Classes */}
          <div>
            <div style={S.sectionLabel}>3 &middot; Target Classes</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {CLASS_SUGGESTIONS.map(cls => {
                const active = selectedClasses.includes(cls);
                return (
                  <span
                    key={cls}
                    onClick={() => toggleClass(cls)}
                    style={{ ...S.chip, ...(active ? S.chipActive : {}) }}
                  >
                    {cls}
                  </span>
                );
              })}
            </div>
            {selectedClasses.length > 0 && (
              <div style={{ fontSize: 10, color: '#64748b', marginTop: 4 }}>
                {selectedClasses.length} class{selectedClasses.length > 1 ? 'es' : ''} selected
              </div>
            )}
            <div style={{ marginTop: 6 }}>
              <input
                ref={csvInputRef}
                type="file"
                accept=".csv,text/csv"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleCsvImport(f);
                  // Reset so re-uploading the same file fires onChange again
                  if (csvInputRef.current) csvInputRef.current.value = '';
                }}
              />
              <button
                type="button"
                onClick={() => csvInputRef.current?.click()}
                style={{
                  background: 'none', border: 'none', padding: 0,
                  color: '#3b82f6', fontSize: 11, fontWeight: 500,
                  cursor: 'pointer', textDecoration: 'underline',
                }}
              >
                + Import CSV
              </button>
              {csvStatus && (
                <span style={{
                  marginLeft: 8, fontSize: 10,
                  color: csvStatus.kind === 'ok' ? '#16a34a' : '#dc2626',
                }}>
                  {csvStatus.msg}
                </span>
              )}
            </div>
          </div>

          {/* Run button */}
          <button
            style={{ ...S.btn, ...(allReady ? S.btnPrimary : S.btnDisabled) }}
            onClick={handleRun}
            disabled={!allReady}
          >
            ▶ Run Analysis
          </button>
        </div>
      )}

      {/* ═══════ RUNNING VIEW ══════════════════════════════════════ */}
      {view === 'running' && (
        <div style={S.card}>
          <div style={{ fontWeight: 600, color: '#1a1a2e', marginBottom: 8 }}>
            Analysis in progress
          </div>
          <div style={{ color: '#64748b', marginBottom: 6 }}>
            Processing {processed}/{totalImages} images&hellip;
          </div>
          <div style={S.progressOuter}>
            <div style={{ ...S.progressFill, width: `${pct}%` }} />
          </div>
          <div style={{ textAlign: 'center', color: '#94a3b8', fontSize: 11, marginTop: 8 }}>
            {pct}% complete
          </div>

          {jobError && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 8 }}>{jobError}</div>
              <button
                style={{ ...S.btn, ...S.btnPrimary }}
                onClick={() => { setJobRunning(false); setJobError(null); setView('config'); }}
              >
                Back to Config
              </button>
            </div>
          )}
        </div>
      )}

      {/* ═══════ DONE VIEW ═════════════════════════════════════════ */}
      {view === 'done' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Success banner */}
          <div style={{ ...S.card, background: '#f0fdf4', borderColor: '#bbf7d0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 20 }}>✓</span>
              <div>
                <div style={{ fontWeight: 600, color: '#166534', fontSize: 13 }}>Analysis Complete</div>
                <div style={{ fontSize: 11, color: '#15803d' }}>{results.length} images processed</div>
              </div>
            </div>

            {/* Summary stats */}
            {summaryStats && (
              <div style={{ borderTop: '1px solid #dcfce7', paddingTop: 8 }}>
                <div style={S.summaryRow}>
                  <span style={{ color: '#64748b' }}>Model</span>
                  <span style={{ fontWeight: 600, color: '#334155' }}>{selectedModel?.name}</span>
                </div>
                <div style={S.summaryRow}>
                  <span style={{ color: '#64748b' }}>Type</span>
                  <span style={{ ...S.badge, background: '#dbeafe', color: '#1d4ed8' }}>{task}</span>
                </div>
                <div style={S.summaryRow}>
                  <span style={{ color: '#64748b' }}>Source</span>
                  <span style={{ fontWeight: 600, color: '#334155' }}>Google Street View</span>
                </div>
                <div style={S.summaryRow}>
                  <span style={{ color: '#64748b' }}>Classes</span>
                  <span style={{ fontWeight: 600, color: '#334155' }}>{summaryStats.classCount} detected</span>
                </div>
                <div style={{ ...S.summaryRow, borderBottom: 'none' }}>
                  <span style={{ color: '#64748b' }}>Geo-located</span>
                  <span style={{ fontWeight: 600, color: '#334155' }}>{summaryStats.geoCount}/{results.length}</span>
                </div>
              </div>
            )}
          </div>

          {/* Data flow indicator */}
          <div style={{
            textAlign: 'center', padding: '8px 12px', borderRadius: 8,
            background: pushed ? '#f0fdf4' : '#fef9c3',
            border: `1px solid ${pushed ? '#bbf7d0' : '#fde68a'}`,
            fontSize: 11,
            color: pushed ? '#166534' : '#92400e',
          }}>
            {pushed
              ? `✓ Data pushed downstream (${results.length} features)`
              : 'Preparing data...'}
          </div>

          {/* Re-push button */}
          <button
            style={{ ...S.btn, ...S.btnGreen }}
            onClick={() => jobId && pushResults(results, jobId)}
          >
            &#8635; Re-push Results Downstream
          </button>
        </div>
      )}
    </div>
  );

  return { contentComponent };
};
