import React, { useState, useEffect, useCallback, useRef } from 'react';
import { NodeLifecycleHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';

/**
 * Street View Fetcher lifecycle.
 *
 * Owns the *acquisition* half of what was once the monolithic Street Vision
 * node in PR #120: geocode a place name, estimate Street View coverage in
 * its bounding box, and emit a GEODATAFRAME (FeatureCollection of points)
 * downstream. Each feature carries `image_url` so the next node (HF CV
 * Inference, Spatial Join, or anything else) can use the imagery directly.
 *
 * Place-search + coverage-estimate UI adapted from
 *   utk_curio/frontend/urban-workflows/src/adapters/node/streetVisionLifecycle.tsx
 * in ManeeshJupalle/curio (feat/street-vision-cv-analysis, #120).
 */

const API_BASE = `${process.env.BACKEND_URL || ''}/api/streetvision`;

const S: Record<string, React.CSSProperties> = {
  root: {
    padding: '12px 14px', fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
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
  input: {
    width: '100%', padding: '7px 10px', border: '1px solid #e2e8f0', borderRadius: 6,
    fontSize: 12, outline: 'none', boxSizing: 'border-box',
  },
  btn: {
    padding: '8px 12px', border: 'none', borderRadius: 8, fontSize: 12,
    fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center',
    justifyContent: 'center', gap: 6, transition: 'all 0.15s', width: '100%',
  },
  btnPrimary: { background: 'linear-gradient(135deg,#3b82f6,#2563eb)', color: '#fff' },
  btnDisabled: { background: '#f3f4f6', color: '#9ca3af', border: '1px solid #e5e7eb', cursor: 'not-allowed' },
  card: { background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 8, padding: '10px 12px', fontSize: 12 },
  label: { fontSize: 10, fontWeight: 600, textTransform: 'uppercase', color: '#94a3b8', letterSpacing: 1, marginBottom: 4 },
  warn: { color: '#92400e', background: '#fef9c3', borderColor: '#fde68a', fontSize: 11 },
  err: { color: '#991b1b', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, padding: '6px 8px', fontSize: 11 },
};

export const useStreetViewFetcherLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [backendUp, setBackendUp] = useState(false);
  const [hasGoogleKey, setHasGoogleKey] = useState(false);

  // Configuration
  const [query, setQuery] = useState('');
  const [bbox, setBbox] = useState<number[] | null>(null);
  const [coverage, setCoverage] = useState<number | null>(null);
  const [limit, setLimit] = useState(20);

  // Run state
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [resultCount, setResultCount] = useState<number | null>(null);

  // Poll the backend health endpoint periodically so the user sees connection
  // status + whether the Google API key is set without having to click Run.
  useEffect(() => {
    const check = () => {
      fetch(`${API_BASE}/health`)
        .then(r => r.json())
        .then(d => { setBackendUp(true); setHasGoogleKey(!!d.has_google_api_key); })
        .catch(() => setBackendUp(false));
    };
    check();
    const iv = setInterval(check, 10_000);
    return () => clearInterval(iv);
  }, []);

  const verifyCoverage = useCallback(() => {
    if (!query.trim()) return;
    setErr(null);
    setCoverage(null);
    setBbox(null);
    fetch(`${API_BASE}/data/streetview/search_place?query=${encodeURIComponent(query)}`)
      .then(async r => { if (!r.ok) throw new Error((await r.json())?.error || `HTTP ${r.status}`); return r.json(); })
      .then(place => {
        if (!place.bbox) throw new Error('No bbox returned');
        // Pad single-address geocodes — Nominatim returns ~10m bboxes for
        // street addresses which collapses all sampled points onto one spot.
        let bb: number[] = place.bbox;
        const [w, s, e, n] = bb;
        if ((e - w) < 0.005 || (n - s) < 0.005) {
          const cx = typeof place.lon === 'number' ? place.lon : (w + e) / 2;
          const cy = typeof place.lat === 'number' ? place.lat : (s + n) / 2;
          const pad = 0.005; // ~500 m at city latitudes
          bb = [cx - pad, cy - pad, cx + pad, cy + pad];
        }
        setBbox(bb);
        return fetch(`${API_BASE}/data/streetview/coverage`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bbox: bb }),
        });
      })
      .then(async r => { if (!r.ok) throw new Error((await r.json())?.error || `HTTP ${r.status}`); return r.json(); })
      .then(d => setCoverage(d.estimated_count))
      .catch(e => setErr(e.message || String(e)));
  }, [query]);

  const runFetch = useCallback(() => {
    if (!bbox) return;
    setBusy(true);
    setErr(null);
    setResultCount(null);
    fetch(`${API_BASE}/data/streetview/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bbox, limit }),
    })
      .then(async r => { if (!r.ok) throw new Error((await r.json())?.error || `HTTP ${r.status}`); return r.json(); })
      .then(fc => {
        data.outputCallback(data.nodeId, { data: fc, dataType: 'geodataframe' });
        nodeState.setOutput({ code: 'success', content: '' });
        setResultCount(Array.isArray(fc?.features) ? fc.features.length : 0);
      })
      .catch(e => setErr(e.message || String(e)))
      .finally(() => setBusy(false));
  }, [bbox, limit, data, nodeState]);

  const ready = backendUp && hasGoogleKey && !!bbox && limit > 0 && !busy;
  const statusColor = backendUp ? '#22c55e' : '#ef4444';
  const statusText = backendUp ? 'Backend connected' : 'Backend offline';

  const contentComponent = (
    <div style={S.root}>
      <div style={S.header}>
        <div style={S.logo}>SV</div>
        <div>
          <div style={S.title}>Street View Fetcher</div>
          <div style={S.sub}>Place → image points</div>
        </div>
      </div>

      <div style={S.row}>
        <div style={{ ...S.dot, background: statusColor }} />
        {statusText}
      </div>

      {backendUp && !hasGoogleKey && (
        <div style={{ ...S.card, ...S.warn }}>
          Google Maps API key required. Set <code>GOOGLE_MAPS_API_KEY</code> in your backend environment.
        </div>
      )}

      <div>
        <div style={S.label}>Place</div>
        <input
          style={S.input}
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') verifyCoverage(); }}
          placeholder="e.g. Lincoln Park, Chicago"
          disabled={!hasGoogleKey}
        />
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        <input
          style={{ ...S.input, width: 80 }}
          type="number" min={1} max={200}
          value={limit > 0 ? limit : ''}
          onChange={e => {
            const v = e.target.value;
            if (v === '') { setLimit(0); return; }
            const n = parseInt(v, 10);
            if (!isNaN(n)) setLimit(n);
          }}
          onBlur={() => { if (limit < 1) setLimit(20); else if (limit > 200) setLimit(200); }}
          title="Image limit (1–200)"
        />
        <button
          style={{ ...S.btn, width: 'auto', flex: 1, background: '#f1f5f9', color: '#334155', border: '1px solid #e2e8f0' }}
          onClick={verifyCoverage}
          disabled={!hasGoogleKey || !query.trim()}
        >
          Verify Coverage
        </button>
      </div>

      {coverage !== null && (
        <div style={{ ...S.card, display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ color: '#22c55e' }}>✓</span>
          <span>≈{coverage} panoramas available in this area</span>
        </div>
      )}

      <button
        style={{ ...S.btn, ...(ready ? S.btnPrimary : S.btnDisabled) }}
        onClick={runFetch}
        disabled={!ready}
      >
        {busy ? 'Fetching…' : '▶ Fetch Images'}
      </button>

      {resultCount !== null && (
        <div style={{ ...S.card, color: '#166534', background: '#f0fdf4', borderColor: '#bbf7d0' }}>
          ✓ {resultCount} image points emitted downstream
        </div>
      )}

      {err && <div style={S.err}>{err}</div>}
    </div>
  );

  return { contentComponent };
};
