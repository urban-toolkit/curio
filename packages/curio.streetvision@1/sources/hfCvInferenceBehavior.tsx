import React, { useState, useEffect, useCallback, useRef } from 'react';
import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';

/**
 * HuggingFace CV Inference behavior.
 *
 * Receives a GEODATAFRAME of image points (each feature carrying
 * `image_url`, plus optional `latitude` / `longitude` / `pano_id`) from
 * any upstream node — typically the Street View Fetcher, but also Data
 * Loading (CSV of URLs), or any Python computation that emits the same
 * shape. Runs HuggingFace segmentation / detection inference on each
 * image, polls progress, and emits a JSON results payload downstream.
 *
 * Model + class config UI adapted from the model-selection and class-picker
 * sections of
 *   utk_curio/frontend/urban-workflows/src/adapters/node/streetVisionBehavior.tsx
 * in ManeeshJupalle/curio (feat/street-vision-cv-analysis, #120).
 */

// See streetViewFetcherBehavior for the rationale on runtime URL resolution.
const API_BASE = `${(typeof window !== 'undefined' && (window as any).curio?.backendUrl) || ''}/api/streetvision`;

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

interface ResultItem {
  image_id: string;
  image_url?: string;
  latitude?: number;
  longitude?: number;
  class_ratios?: Record<string, number>;
  object_counts?: Record<string, number>;
  detections?: { label: string; confidence: number; bbox: number[] }[];
}

type View = 'config' | 'running' | 'done';

const CLASS_SUGGESTIONS = [
  'building', 'road', 'sidewalk', 'vegetation',
  'pole', 'fence', 'wall', 'traffic sign',
];

const S: Record<string, React.CSSProperties> = {
  root: {
    padding: '12px 14px', fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
    fontSize: 13, color: '#333',
    display: 'flex', flexDirection: 'column', gap: 10,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 },
  logo: {
    width: 28, height: 28, borderRadius: 6,
    background: 'linear-gradient(135deg,#ec4899,#f472b6)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#fff', fontSize: 14, fontWeight: 700, flexShrink: 0,
  },
  title: { fontSize: 14, fontWeight: 600, color: '#1a1a2e', lineHeight: 1.2 },
  sub: { fontSize: 10, color: '#888', marginTop: 1 },
  row: { display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#666' },
  dot: { width: 8, height: 8, borderRadius: '50%', flexShrink: 0 },
  input: {
    width: '100%', padding: '7px 10px', border: '1px solid #e2e8f0', borderRadius: 6,
    fontSize: 12, outline: 'none', boxSizing: 'border-box',
  },
  btn: {
    padding: '8px 12px', border: 'none', borderRadius: 8, fontSize: 12,
    fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', gap: 6, width: '100%',
  },
  btnPrimary: { background: 'linear-gradient(135deg,#ec4899,#db2777)', color: '#fff' },
  btnDisabled: { background: '#f3f4f6', color: '#9ca3af', border: '1px solid #e5e7eb', cursor: 'not-allowed' },
  card: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', fontSize: 12 },
  label: { fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: 1, marginBottom: 4 },
  chip: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    padding: '3px 8px', borderRadius: 12, fontSize: 11, cursor: 'pointer',
    border: '1px solid #e2e8f0', background: '#fff',
  },
  chipActive: { background: '#fdf2f8', borderColor: '#f9a8d4', color: '#be185d' },
  progressOuter: { height: 6, background: '#e2e8f0', borderRadius: 3, overflow: 'hidden', marginTop: 6 },
  progressFill: { height: '100%', background: 'linear-gradient(90deg,#ec4899,#f472b6)', borderRadius: 3, transition: 'width 0.3s' },
  err: { color: '#991b1b', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: '6px 8px', fontSize: 11 },
  warn: { color: '#92400e', background: '#fef9c3', border: '1px solid #fde68a', borderRadius: 6, padding: '6px 8px', fontSize: 11 },
};

// Pull the image list out of whatever shape the upstream node emitted. We
// accept:
//   1. Curio's GEODATAFRAME wrapper: `{ data: FeatureCollection, dataType: 'geodataframe' }`
//   2. A bare FeatureCollection
//   3. An object with an `images` array (forward compat with custom shapes)
function extractImages(input: any): Array<{ image_id?: string; image_url?: string; pano_id?: string; latitude?: number; longitude?: number }> {
  if (!input) return [];
  // GEODATAFRAME wrapper
  if (typeof input === 'object' && input.dataType === 'geodataframe' && input.data) {
    return extractImages(input.data);
  }
  // Bare FeatureCollection
  if (input?.type === 'FeatureCollection' && Array.isArray(input.features)) {
    return input.features
      .map((f: any) => {
        const props = f?.properties || {};
        const coords = f?.geometry?.coordinates;
        const lon = props.longitude ?? (Array.isArray(coords) ? coords[0] : undefined);
        const lat = props.latitude ?? (Array.isArray(coords) ? coords[1] : undefined);
        return {
          image_id: props.image_id || props.pano_id || undefined,
          pano_id: props.pano_id,
          image_url: props.image_url,
          latitude: lat,
          longitude: lon,
        };
      })
      .filter((x: any) => !!x.image_url);
  }
  if (Array.isArray(input?.images)) {
    return input.images;
  }
  return [];
}

export const useHfCvInferenceBehavior: NodeBehaviorHook = (data, nodeState) => {
  // ── Health ──────────────────────────────────────────────────────────
  const [backendUp, setBackendUp] = useState(false);
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/health`).then(r => r.json())
        .then(() => setBackendUp(true))
        .catch(() => setBackendUp(false));
    };
    check();
    const iv = setInterval(check, 10_000);
    return () => clearInterval(iv);
  }, []);

  // ── Upstream images ────────────────────────────────────────────────
  const [images, setImages] = useState<ReturnType<typeof extractImages>>([]);
  useEffect(() => {
    const extracted = extractImages(data.input);
    setImages(extracted);
  }, [data.input]);

  // ── Model picker ───────────────────────────────────────────────────
  const [task, setTask] = useState<ModelType>('segmentation');
  const [query, setQuery] = useState('cityscapes');
  const [models, setModels] = useState<ModelSearchResult[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<ModelInfo | null>(null);
  const [autoPick, setAutoPick] = useState(true);
  const userPickedRef = useRef(false);

  useEffect(() => {
    if (query.length < 2) return;
    const t = setTimeout(() => {
      setModelsLoading(true);
      setModelsError(null);
      fetch(`${API_BASE}/models/search?task=${task}&query=${encodeURIComponent(query)}`)
        .then(async r => {
          const d = await r.json().catch(() => ({}));
          if (!r.ok) {
            // 503 = extras not installed (shows the pip-install hint);
            // 5xx = generic backend error; bubble both up to the UI.
            throw new Error(d.hint ? `${d.error}: ${d.hint}` : d.error || `HTTP ${r.status}`);
          }
          return d;
        })
        .then(d => {
          const list = d.models ?? [];
          setModels(list);
          if (autoPick && !userPickedRef.current && list.length > 0) {
            const top = list[0];
            setSelectedModel({ model_id: top.model_id, model_type: task, name: top.name, description: '' });
          }
        })
        .catch(e => {
          setModels([]);
          setModelsError(e?.message || String(e));
        })
        .finally(() => setModelsLoading(false));
    }, 400);
    return () => clearTimeout(t);
  }, [task, query, autoPick]);

  useEffect(() => { userPickedRef.current = false; }, [task]);

  // ── Target classes ─────────────────────────────────────────────────
  const [selectedClasses, setSelectedClasses] = useState<string[]>([]);
  const toggleClass = (cls: string) => {
    setSelectedClasses(prev => prev.includes(cls) ? prev.filter(c => c !== cls) : [...prev, cls]);
  };
  const csvInputRef = useRef<HTMLInputElement>(null);
  const [csvStatus, setCsvStatus] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);
  const handleCsvImport = (file: File) => {
    setCsvStatus(null);
    const reader = new FileReader();
    reader.onerror = () => setCsvStatus({ kind: 'err', msg: 'Could not read file.' });
    reader.onload = (e) => {
      try {
        const text = String(e.target?.result ?? '').replace(/\r/g, '');
        const lines = text.split('\n').map(l => l.split(',')[0].trim()).filter(Boolean);
        if (lines.length === 0) { setCsvStatus({ kind: 'err', msg: 'CSV is empty.' }); return; }
        const headerHints = ['class', 'classes', 'label', 'labels', 'name', 'category'];
        const skipHeader = headerHints.includes(lines[0].toLowerCase());
        const candidates = (skipHeader ? lines.slice(1) : lines)
          .map(s => s.replace(/^["']|["']$/g, '').trim())
          .filter(s => s.length > 0 && s.length <= 64);
        const existingLower = new Set(selectedClasses.map(c => c.toLowerCase()));
        const seenLower = new Set<string>();
        const fresh: string[] = [];
        for (const c of candidates) {
          const k = c.toLowerCase();
          if (existingLower.has(k) || seenLower.has(k)) continue;
          seenLower.add(k);
          fresh.push(c);
        }
        if (fresh.length === 0) { setCsvStatus({ kind: 'ok', msg: 'No new classes to import.' }); return; }
        setSelectedClasses(prev => [...prev, ...fresh]);
        setCsvStatus({ kind: 'ok', msg: `Imported ${fresh.length} class${fresh.length > 1 ? 'es' : ''}.` });
      } catch (err: any) {
        setCsvStatus({ kind: 'err', msg: `Parse error: ${err?.message || 'unknown'}.` });
      }
    };
    reader.readAsText(file);
  };

  // ── Job behavior ──────────────────────────────────────────────────
  const [view, setView] = useState<View>('config');
  const [jobId, setJobId] = useState<string | null>(null);
  const [processed, setProcessed] = useState(0);
  const [totalImages, setTotalImages] = useState(0);
  const [stageMessage, setStageMessage] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [results, setResults] = useState<ResultItem[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval>>();

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = undefined; }
  }, []);

  const pushResults = useCallback((jobResults: ResultItem[], jid: string) => {
    const payload = {
      type: 'street_vision_results',
      job_id: jid,
      model_type: task,
      total_images: jobResults.length,
      results: jobResults,
    };
    data.outputCallback(data.nodeId, JSON.stringify(payload));
    nodeState.setOutput({ code: 'success', content: '' });
  }, [data, task, nodeState]);

  const handleRun = useCallback(() => {
    if (!selectedModel || images.length === 0 || selectedClasses.length === 0) return;
    setJobError(null);
    setResults([]);
    setProcessed(0);
    setTotalImages(images.length);
    setView('running');

    fetch(`${API_BASE}/inference/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        images,
        model: selectedModel,
        classes: { classes: selectedClasses, source: 'prompt' },
      }),
    })
      .then(async r => { if (!r.ok) throw new Error((await r.json())?.hint || (await r.json())?.error || `HTTP ${r.status}`); return r.json(); })
      .then(d => {
        setJobId(d.job_id);
        pollRef.current = setInterval(() => {
          fetch(`${API_BASE}/inference/results/${d.job_id}`)
            .then(r => r.json())
            .then(s => {
              setProcessed(s.processed);
              setTotalImages(s.total_images);
              setStageMessage(s.stage_message ?? null);
              if (s.results?.length) setResults(s.results);
              if (s.status === 'completed' || s.status === 'failed') {
                stopPolling();
                if (s.status === 'failed') {
                  setJobError(s.error || 'Inference failed.');
                } else {
                  setView('done');
                  pushResults(s.results, d.job_id);
                }
              }
            })
            .catch(() => {
              stopPolling();
              setJobError('Lost connection to backend.');
            });
        }, 2000);
      })
      .catch(e => setJobError(e.message || 'Failed to start inference.'));
  }, [selectedModel, selectedClasses, images, stopPolling, pushResults]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const pct = totalImages > 0 ? Math.round((processed / totalImages) * 100) : 0;
  const allReady = !!selectedModel && selectedClasses.length > 0 && images.length > 0 && backendUp;

  const fmtDl = (n: number | null | undefined) =>
    typeof n === 'number' ? (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n)) : '—';

  const contentComponent = (
    <div style={S.root}>
      <div style={S.header}>
        <div style={S.logo}>HF</div>
        <div>
          <div style={S.title}>HF CV Inference</div>
          <div style={S.sub}>HuggingFace segmentation / detection</div>
        </div>
        {view === 'done' && (
          <button
            style={{ background: 'none', border: 'none', color: '#ec4899', fontSize: 11, fontWeight: 600, cursor: 'pointer', marginLeft: 'auto' }}
            onClick={() => setView('config')}
          >
            ← Reconfigure
          </button>
        )}
      </div>

      <div style={S.row}>
        <div style={{ ...S.dot, background: backendUp ? '#22c55e' : '#ef4444' }} />
        {backendUp ? 'Backend connected' : 'Backend offline'}
      </div>

      <div style={S.card}>
        <span style={{ fontWeight: 600 }}>Upstream:</span>{' '}
        {images.length > 0 ? `${images.length} image${images.length > 1 ? 's' : ''} received` : 'waiting for image points…'}
      </div>

      {view === 'config' && (
        <>
          <div>
            <div style={S.label}>1 · Task</div>
            <div style={{ display: 'flex', gap: 4 }}>
              {(['segmentation', 'detection'] as ModelType[]).map(t => (
                <button
                  key={t}
                  onClick={() => setTask(t)}
                  style={{
                    flex: 1, padding: '5px 0', border: 'none', borderRadius: 6,
                    fontSize: 11, fontWeight: 600, cursor: 'pointer',
                    ...(task === t
                      ? { background: 'linear-gradient(135deg,#ec4899,#db2777)', color: '#fff' }
                      : { background: '#f1f5f9', color: '#64748b', border: '1px solid #e2e8f0' }),
                  }}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div style={S.label}>2 · Model</div>
            {selectedModel && (
              <div style={{ ...S.card, background: '#fdf2f8', borderColor: '#f9a8d4', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: '#22c55e' }}>✓</span>
                <span style={{ fontSize: 12, color: '#9d174d', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedModel.name}</span>
              </div>
            )}
            <input
              style={S.input}
              value={query}
              onChange={e => { userPickedRef.current = false; setQuery(e.target.value); }}
              placeholder="Search HuggingFace models…"
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, fontSize: 11, color: '#475569', cursor: 'pointer' }}>
              <input type="checkbox" checked={autoPick}
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
              Auto-pick best model (top match by downloads)
            </label>
            <div style={{ maxHeight: 130, overflowY: 'auto', marginTop: 6 }}>
              {modelsLoading && <div style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', padding: 6 }}>Searching…</div>}
              {!modelsLoading && modelsError && (
                <div style={{ ...S.warn, padding: '6px 8px', fontSize: 11 }}>{modelsError}</div>
              )}
              {!modelsLoading && !modelsError && models.length === 0 && query.length >= 2 && (
                <div style={{ fontSize: 11, color: '#94a3b8', textAlign: 'center', padding: 6 }}>No models found</div>
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
                      padding: '5px 7px', borderRadius: 6, cursor: 'pointer', marginBottom: 2,
                      background: sel ? '#fdf2f8' : 'transparent',
                      border: sel ? '1px solid #f9a8d4' : '1px solid transparent',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                      <span style={{ color: '#334155', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>{m.name}</span>
                      <span style={{ color: '#94a3b8', fontSize: 10, marginLeft: 6, flexShrink: 0 }}>⬇ {fmtDl(m.downloads)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <div style={S.label}>3 · Target Classes</div>
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
                type="file" accept=".csv,text/csv" style={{ display: 'none' }}
                onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) handleCsvImport(f);
                  if (csvInputRef.current) csvInputRef.current.value = '';
                }}
              />
              <button
                type="button"
                onClick={() => csvInputRef.current?.click()}
                style={{ background: 'none', border: 'none', padding: 0, color: '#ec4899', fontSize: 11, fontWeight: 500, cursor: 'pointer', textDecoration: 'underline' }}
              >
                + Import CSV
              </button>
              {csvStatus && (
                <span style={{ marginLeft: 8, fontSize: 10, color: csvStatus.kind === 'ok' ? '#16a34a' : '#dc2626' }}>
                  {csvStatus.msg}
                </span>
              )}
            </div>
          </div>

          <button
            style={{ ...S.btn, ...(allReady ? S.btnPrimary : S.btnDisabled) }}
            onClick={handleRun}
            disabled={!allReady}
            title={!backendUp ? 'Backend offline' : (images.length === 0 ? 'Connect upstream image source' : (selectedModel == null ? 'Pick a model' : (selectedClasses.length === 0 ? 'Pick at least one class' : 'Ready')))}
          >
            ▶ Run Inference
          </button>
        </>
      )}

      {view === 'running' && (
        <div style={S.card}>
          <div style={{ fontWeight: 600, color: '#1a1a2e', marginBottom: 8 }}>Inference in progress</div>
          {stageMessage ? (
            <div style={{ color: '#64748b', marginBottom: 6, fontStyle: 'italic' }}>{stageMessage}</div>
          ) : (
            <div style={{ color: '#64748b', marginBottom: 6 }}>{processed}/{totalImages} images…</div>
          )}
          <div style={S.progressOuter}>
            <div style={{ ...S.progressFill, width: `${pct}%` }} />
          </div>
          <div style={{ textAlign: 'center', color: '#94a3b8', fontSize: 11, marginTop: 8 }}>{pct}%</div>
          {jobError && (
            <div style={{ marginTop: 10 }}>
              <div style={S.err}>{jobError}</div>
              <button
                style={{ ...S.btn, ...S.btnPrimary, marginTop: 8 }}
                onClick={() => { setJobError(null); setView('config'); }}
              >Back to Config</button>
            </div>
          )}
        </div>
      )}

      {view === 'done' && (
        <>
          <div style={{ ...S.card, background: '#f0fdf4', borderColor: '#bbf7d0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 20 }}>✓</span>
              <div>
                <div style={{ fontWeight: 600, color: '#166534', fontSize: 13 }}>Inference Complete</div>
                <div style={{ fontSize: 11, color: '#15803d' }}>{results.length} images processed</div>
              </div>
            </div>
          </div>
          <button
            style={{ ...S.btn, background: '#f0fdf4', color: '#166534', border: '1px solid #bbf7d0' }}
            onClick={() => jobId && pushResults(results, jobId)}
          >
            ⟳ Re-push Results Downstream
          </button>
        </>
      )}
    </div>
  );

  return { contentComponent };
};
