import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronDown } from '@fortawesome/free-solid-svg-icons/faChevronDown';
import { faChevronRight } from '@fortawesome/free-solid-svg-icons/faChevronRight';
import { faCopy } from '@fortawesome/free-solid-svg-icons/faCopy';
import { faCrosshairs } from '@fortawesome/free-solid-svg-icons/faCrosshairs';
import { faGear } from '@fortawesome/free-solid-svg-icons/faGear';
import { faLocationArrow } from '@fortawesome/free-solid-svg-icons/faLocationArrow';
import { faLocationDot } from '@fortawesome/free-solid-svg-icons/faLocationDot';
import { faReply } from '@fortawesome/free-solid-svg-icons/faReply';
import { faSliders } from '@fortawesome/free-solid-svg-icons/faSliders';
import type { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';
import { GoogleStreetView, type LiveCamera } from './googleStreetView';
import { nodeUiStyles as S } from './nodeUiStyles';
import {
  PANORAMA_CAMERA_CHANNEL, PANORAMA_CAMERA_SCHEMA, PANORAMA_REQUEST_SCHEMA,
  PANORAMA_STATUS_CHANNEL, PANORAMA_STATUS_SCHEMA,
  latestPanoramaContext, latestPanoramaRequest, validPoint, type PanoramaRequest,
} from './panoramaContract';

const panoramaUiCss = `
[data-curio-streetview-panorama] { container-type: inline-size; }
[data-curio-streetview-panorama] .sv-status-row,
[data-curio-streetview-panorama] .sv-info-row,
[data-curio-streetview-panorama] .sv-info-values,
[data-curio-streetview-panorama] .sv-info-item { display: flex; align-items: center; }
[data-curio-streetview-panorama] .sv-status-row,
[data-curio-streetview-panorama] .sv-info-row { justify-content: space-between; gap: 10px; }
[data-curio-streetview-panorama] .sv-status-row,
[data-curio-streetview-panorama] .sv-info-row,
[data-curio-streetview-panorama] .sv-disclosure { flex-shrink: 0; }
[data-curio-streetview-panorama] .sv-status-text { display: grid; gap: 3px; min-width: 0; }
[data-curio-streetview-panorama] .sv-status-text strong { font-size: var(--curio-font-size-sm, 13px); }
[data-curio-streetview-panorama] .sv-status-text small { color: var(--curio-text-muted, #64748b); }
[data-curio-streetview-panorama] .sv-status-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
[data-curio-streetview-panorama] .sv-status-line { display: flex; align-items: center; gap: 8px; }
[data-curio-streetview-panorama] .sv-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  width: auto; min-height: 32px; padding: 5px 10px; border-radius: var(--curio-radius-sm, 6px);
  border: 1px solid var(--curio-border, #d8dee8); background: var(--curio-card-bg, #fff);
  color: var(--curio-text-primary, #1f2937); font: inherit; font-weight: 600; cursor: pointer; white-space: nowrap; }
[data-curio-streetview-panorama] .sv-button:hover:not(:disabled),
[data-curio-streetview-panorama] .sv-disclosure summary:hover { background: var(--curio-surface-muted, #f1f5f9); }
[data-curio-streetview-panorama] .sv-button:focus-visible,
[data-curio-streetview-panorama] .sv-disclosure summary:focus-visible { outline: 2px solid var(--curio-focus-ring, #3b82f6); outline-offset: 2px; }
[data-curio-streetview-panorama] .sv-button:disabled { opacity: .5; cursor: not-allowed; }
[data-curio-streetview-panorama] .sv-button-primary { background: var(--curio-top-bar-bg, #24252a);
  color: var(--curio-text-on-dark, #fff); border-color: var(--curio-top-bar-bg, #24252a); }
[data-curio-streetview-panorama] .sv-button-primary:hover:not(:disabled) { filter: brightness(1.1); }
[data-curio-streetview-panorama] .sv-settings { padding: 9px 11px; border: 1px solid var(--curio-border, #d8dee8);
  border-radius: var(--curio-radius-md, 8px); background: var(--curio-surface-muted, #f8fafc); }
[data-curio-streetview-panorama] .sv-panorama-frame { min-height: 260px; flex: 1; overflow: hidden;
  border: 1px solid var(--curio-border, #d8dee8); border-radius: var(--curio-radius-md, 8px); }
[data-curio-streetview-panorama] .sv-info-row { flex-wrap: wrap; min-height: 32px; }
[data-curio-streetview-panorama] .sv-info-values { flex-wrap: wrap; gap: 10px; color: var(--curio-text-secondary, #475569); }
[data-curio-streetview-panorama] .sv-info-item { gap: 7px; white-space: nowrap; }
[data-curio-streetview-panorama] .sv-info-item svg,
[data-curio-streetview-panorama] .sv-disclosure summary svg,
[data-curio-streetview-panorama] .sv-button svg { width: 15px; height: 15px; flex: none; }
[data-curio-streetview-panorama] .sv-settings-button svg { width: 10px; height: 10px; }
[data-curio-streetview-panorama] .sv-settings-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
[data-curio-streetview-panorama] .sv-disclosure { border: 1px solid var(--curio-border, #d8dee8);
  border-radius: var(--curio-radius-md, 8px); background: var(--curio-card-bg, #fff); }
[data-curio-streetview-panorama] .sv-disclosure summary { display: flex; align-items: center; gap: 10px;
  padding: 9px 11px; font-weight: 600; cursor: pointer; list-style: none; border-radius: inherit; }
[data-curio-streetview-panorama] .sv-disclosure summary::-webkit-details-marker { display: none; }
[data-curio-streetview-panorama] .sv-disclosure summary .sv-chevron { margin-left: auto; }
[data-curio-streetview-panorama] .sv-disclosure:not([open]) .sv-chevron-down,
[data-curio-streetview-panorama] .sv-disclosure[open] .sv-chevron-right { display: none; }
[data-curio-streetview-panorama] .sv-section-body { display: grid; gap: 8px; padding: 0 11px 11px; }
[data-curio-streetview-panorama] .sv-detail-row { display: flex; justify-content: space-between;
  align-items: flex-start; gap: 8px; flex-wrap: wrap; }
[data-curio-streetview-panorama] .sv-detail-row span:first-child { color: var(--curio-text-secondary, #475569); }
[data-curio-streetview-panorama] .sv-detail-value { display: inline-flex; align-items: center; gap: 5px;
  min-width: 0; overflow-wrap: anywhere; }
[data-curio-streetview-panorama] .sv-copy { min-width: 28px; min-height: 28px; padding: 3px;
  color: var(--curio-text-secondary); }
[data-curio-streetview-panorama] .sv-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
[data-curio-streetview-panorama] .sv-field { display: grid; gap: 4px; min-width: 0; }
[data-curio-streetview-panorama] .sv-field input { width: 100%; box-sizing: border-box; min-height: 32px;
  padding: 5px 8px; border: 1px solid var(--curio-border, #d8dee8);
  border-radius: var(--curio-radius-sm, 6px); background: var(--curio-card-bg, #fff); color: var(--curio-text-primary, #1f2937); font: inherit; }
[data-curio-streetview-panorama] .sv-field input:focus-visible { outline: 2px solid var(--curio-focus-ring, #3b82f6); outline-offset: 1px; }
@container (max-width: 500px) {
  [data-curio-streetview-panorama] .sv-info-row { align-items: stretch; }
  [data-curio-streetview-panorama] .sv-info-row > div:last-child { width: 100%; }
  [data-curio-streetview-panorama] .sv-info-row .sv-button { width: 100%; }
  [data-curio-streetview-panorama] .sv-form-grid { grid-template-columns: 1fr; }
}
`;

function distanceMeters(a: [number, number], b: [number, number]): number {
  const radians = Math.PI / 180;
  const latitudeA = a[1] * radians; const latitudeB = b[1] * radians;
  const halfLatitude = (b[1] - a[1]) * radians / 2;
  const halfLongitude = (b[0] - a[0]) * radians / 2;
  const value = Math.sin(halfLatitude) ** 2 + Math.cos(latitudeA) * Math.cos(latitudeB) * Math.sin(halfLongitude) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(value)));
}

/** A pasted workflow address is not a Maps JavaScript API key. Reject it before loading Google. */
export function browserKeyInputIssue(value: string): string | null {
  const key = value.trim();
  if (!key) return null;
  return /^(?:https?:\/\/|www\.|localhost(?:[:/]|$))/i.test(key) || /[/?#\s]/.test(key)
    ? 'Enter a Maps JavaScript API key here, not a workflow URL.' : null;
}

/** Ordinary data input accepts a WGS84 point, GeoJSON Point or point FeatureCollection. */
export function pointFromInput(input: any): [number, number] | null {
  let value = input;
  for (let depth = 0; depth < 6; depth += 1) {
    if (typeof value === 'string') {
      try { value = JSON.parse(value); } catch { return null; }
    } else if (value?.dataType && value.data !== undefined) value = value.data;
    else if (value?.data !== undefined) value = value.data;
    else if (value?.content !== undefined) value = value.content;
    else break;
  }
  // A collection with several rows is not an explicit point selection.
  if (value?.type === 'FeatureCollection') {
    if (!Array.isArray(value.features) || value.features.length !== 1) return null;
    value = value.features[0];
  }
  if (value?.type === 'Feature') value = value.geometry;
  const point = value?.type === 'Point' ? value.coordinates
    : value?.location ?? value?.coordinates ?? value;
  return validPoint(point) ? [point[0], point[1]] : null;
}

async function resolveInput(input: unknown, signal: AbortSignal): Promise<[number, number] | null> {
  let value: any = input;
  for (let depth = 0; depth < 8; depth += 1) {
    const point = pointFromInput(value);
    if (point) return point;
    let reference: string | null = null;
    if (typeof value === 'string') {
      if (!value.trim()) return null;
      try { value = JSON.parse(value); continue; }
      catch { reference = value; }
    } else if (typeof value?.path === 'string' && value.data === undefined) reference = value.path;
    else if (value?.data !== undefined) { value = value.data; continue; }
    else return null;
    const backend = (window as any).curio?.backendUrl || 'http://localhost:5002';
    const cookie = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
    if (!reference) return null;
    const headers: Record<string, string> = cookie ? { Authorization: `Bearer ${decodeURIComponent(cookie[1])}` } : {};
    const response = await fetch(`${backend}/get?fileName=${encodeURIComponent(reference)}`, { headers, signal });
    if (!response.ok) throw new Error(`Could not load point input (HTTP ${response.status}).`);
    value = await response.json();
  }
  throw new Error('Point input contains too many nested references.');
}

/** Generic interactive node. The viewer has no knowledge of Sidewalk tiles or edits. */
export const useStreetViewPanoramaBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [browserKey, setBrowserKey] = React.useState('');
  const [draftBrowserKey, setDraftBrowserKey] = React.useState('');
  const [longitude, setLongitude] = React.useState('');
  const [latitude, setLatitude] = React.useState('');
  const [radius, setRadius] = React.useState('60');
  const [heading, setHeading] = React.useState('');
  const [request, setRequest] = React.useState<PanoramaRequest | null>(null);
  const [inputError, setInputError] = React.useState('');
  const [manualError, setManualError] = React.useState('');
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [source, setSource] = React.useState<'connected' | 'manual' | 'waiting'>('waiting');
  const [viewerStatus, setViewerStatus] = React.useState<'loading' | 'ready' | 'unavailable' | 'error'>('loading');
  const [viewerMessage, setViewerMessage] = React.useState('');
  const [camera, setCamera] = React.useState<LiveCamera | null>(null);
  const [cameraKey, setCameraKey] = React.useState('');
  const [retryRevision, setRetryRevision] = React.useState(0);
  const [contextCurrent, setContextCurrent] = React.useState(true);
  const [copyNotice, setCopyNotice] = React.useState('');
  const keyIssue = browserKeyInputIssue(browserKey);
  const draftKeyIssue = browserKeyInputIssue(draftBrowserKey);
  const usableKey = !!browserKey.trim() && !keyIssue;
  const revision = React.useRef(0);
  const cameraRevision = React.useRef(0);
  const activeRequest = React.useRef<PanoramaRequest | null>(null);
  const lastIncomingKey = React.useRef('');
  const lastInputPoint = React.useRef('');
  const callback = React.useRef(data.interactionsCallback);
  callback.current = data.interactionsCallback;
  const incoming = latestPanoramaRequest(data.interactions);
  const context = latestPanoramaContext(data.interactions);
  const incomingKey = incoming ? `${incoming.requestId}:${incoming.revision}` : '';

  React.useEffect(() => {
    if (!incoming) return;
    if (lastIncomingKey.current === incomingKey) return;
    lastIncomingKey.current = incomingKey;
    activeRequest.current = incoming;
    cameraRevision.current = 0;
    setRequest(incoming);
    setSource('connected');
    setViewerStatus('loading');
    setContextCurrent(true);
  }, [incomingKey]);

  React.useEffect(() => {
    if (context && activeRequest.current?.requestId === context.requestId
      && activeRequest.current.revision === context.revision) setContextCurrent(false);
  }, [context]);

  React.useEffect(() => {
    const controller = new AbortController();
    setInputError('');
    if (incoming) return () => controller.abort();
    if (data.input === null || data.input === undefined || data.input === '') {
      lastInputPoint.current = '';
      return () => controller.abort();
    }
    resolveInput(data.input, controller.signal).then(point => {
      if (!controller.signal.aborted) {
        if (!point) { setInputError('Input must contain a WGS84 point in [longitude, latitude] order.'); return; }
        const signature = point.join(',');
        if (signature === lastInputPoint.current) return;
        lastInputPoint.current = signature;
        const next: PanoramaRequest = { schema: PANORAMA_REQUEST_SCHEMA,
          requestId: `${data.nodeId}:input:${++revision.current}`, revision: revision.current,
          location: point, crs: 'EPSG:4326' };
        activeRequest.current = next; cameraRevision.current = 0;
        setRequest(next); setSource('connected'); setViewerStatus('loading');
        setContextCurrent(true);
      }
    }).catch(error => {
      if (!controller.signal.aborted) setInputError(error instanceof Error ? error.message : String(error));
    });
    return () => controller.abort();
  }, [data.input, incomingKey]);

  const manualPoint: [number, number] | null = validPoint([Number(longitude), Number(latitude)])
    && longitude.trim() && latitude.trim() ? [Number(longitude), Number(latitude)] : null;
  const radiusValue = Number(radius);
  const validRadius = Number.isFinite(radiusValue) && radiusValue >= 1 && radiusValue <= 1000;
  const headingValue = heading.trim() ? Number(heading) : undefined;
  const validHeading = headingValue === undefined || Number.isFinite(headingValue);
  const openPoint = (point: [number, number] | null) => {
    if (!point || !validRadius || !validHeading) { setManualError('Enter valid WGS84 coordinates, a search radius from 1 to 1000 m, and a numeric initial heading.'); return; }
    setManualError('');
    const next: PanoramaRequest = {
      schema: PANORAMA_REQUEST_SCHEMA, requestId: `${data.nodeId}:manual:${++revision.current}`,
      revision: revision.current, location: point, crs: 'EPSG:4326', radiusMetres: radiusValue,
      ...(headingValue !== undefined ? { initialHeadingDegrees: headingValue } : {}),
    };
    activeRequest.current = next;
    cameraRevision.current = 0;
    setRequest(next);
    setSource('manual'); setViewerStatus('loading');
    setContextCurrent(true);
  };
  const currentRequest = request;
  const currentRequestKey = currentRequest ? `${currentRequest.requestId}:${currentRequest.revision}` : '';
  const reuseCurrent = !!currentRequest?.reuseCurrent
    && currentRequest.reuseCurrent.viewerId === data.nodeId;
  const onCamera = (nextCamera: LiveCamera, loadedKey?: string) => {
    if (!currentRequest || !contextCurrent || activeRequest.current?.requestId !== currentRequest.requestId
      || activeRequest.current.revision !== currentRequest.revision || (loadedKey && loadedKey !== currentRequestKey)) return;
    setCamera(nextCamera); setCameraKey(currentRequestKey);
    callback.current?.({ [PANORAMA_CAMERA_CHANNEL]: {
      schema: PANORAMA_CAMERA_SCHEMA, requestId: currentRequest.requestId,
      revision: currentRequest.revision, viewerId: data.nodeId,
      cameraRevision: ++cameraRevision.current,
      requestedLocation: currentRequest.location, actualLocation: nextCamera.location,
      panoId: nextCamera.panoId, headingDegrees: nextCamera.headingDegrees,
      headingReference: 'clockwise-from-true-north',
      pitchDegrees: nextCamera.pitchDegrees, zoom: nextCamera.zoom,
    } }, data.nodeId);
  };

  const actual = cameraKey === currentRequestKey ? camera : null;
  const inspectionState = !currentRequest || !contextCurrent ? null : keyIssue ? 'invalid-key'
    : !usableKey ? 'missing-key' : actual ? 'confirmed'
      : viewerStatus === 'error' || viewerStatus === 'unavailable' ? viewerStatus : 'loading';
  React.useEffect(() => {
    if (!currentRequest || !inspectionState) return;
    callback.current?.({ [PANORAMA_STATUS_CHANNEL]: {
      schema: PANORAMA_STATUS_SCHEMA, requestId: currentRequest.requestId,
      revision: currentRequest.revision, viewerId: data.nodeId, state: inspectionState,
      ...((inspectionState === 'error' || inspectionState === 'unavailable') && viewerMessage ? { message: viewerMessage } : {}),
    } }, data.nodeId);
  }, [currentRequestKey, inspectionState, viewerMessage, data.nodeId]);
  const distance = actual && currentRequest ? distanceMeters(actual.location, currentRequest.location) : null;
  const statusText = !currentRequest ? 'Waiting for a location' : !contextCurrent ? 'Previous tile panorama'
    : keyIssue ? 'Browser key is not an API key' : !usableKey ? 'API key required to load Street View.'
    : viewerStatus === 'loading' ? 'Loading panorama' : viewerStatus === 'ready'
      ? source === 'manual' ? 'Manual location' : 'Following connected input'
      : viewerStatus === 'unavailable' ? 'No nearby panorama' : 'Panorama error';
  const canRetry = !!currentRequest && contextCurrent && usableKey && (viewerStatus === 'error' || viewerStatus === 'unavailable');
  const canReturn = !!currentRequest && contextCurrent && usableKey && viewerStatus !== 'loading';
  const copyValue = async (value: string, label: string) => {
    if (!navigator.clipboard?.writeText) return;
    try { await navigator.clipboard.writeText(value); setCopyNotice(`${label} copied`); }
    catch { setCopyNotice(`Could not copy ${label.toLowerCase()}`); }
  };
  const coordinateText = (point: [number, number] | null | undefined) => point
    ? `lon ${point[0].toFixed(6)}°, lat ${point[1].toFixed(6)}°` : 'unavailable';
  const detail = (label: string, value: string, copyable: boolean) => <div className="sv-detail-row">
    <span>{label}</span><span className="sv-detail-value">{value}
      {copyable && !!navigator.clipboard?.writeText && <button type="button" className="sv-button sv-copy"
        aria-label={`Copy ${label.toLowerCase()}`} title={`Copy ${label.toLowerCase()}`}
        onClick={() => void copyValue(value, label)}><FontAwesomeIcon icon={faCopy} aria-hidden="true" /></button>}
    </span>
  </div>;
  const statusColor = !usableKey ? 'var(--curio-text-muted)'
    : viewerStatus === 'ready' && contextCurrent ? '#16a34a'
    : viewerStatus === 'loading' && currentRequest ? '#d97706'
      : viewerStatus === 'error' || viewerStatus === 'unavailable' ? '#dc2626' : '#94a3b8';
  return { disablePlay: true, contentComponent: <div className="nodrag nopan nowheel" role="region"
    data-curio-streetview-panorama="" aria-label="Street View Panorama"
    style={{ ...S.root, height: '100%', minHeight: 0, padding: '6px 0', gap: 8,
      boxSizing: 'border-box', overflowY: 'auto', fontFamily: 'var(--curio-font-family)',
      fontSize: 'var(--curio-font-size-sm)', color: 'var(--curio-text-primary)', background: 'var(--curio-card-bg)' }}>
    <style>{panoramaUiCss}</style>
    <div className="sv-status-row">
      <div className="sv-status-text">
        <div className="sv-status-line"><span className="sv-status-dot" style={{ background: statusColor }} />
          <strong role="status">{statusText}</strong></div>
        <small>{usableKey ? 'Google Maps key configured' : 'Google Maps key not configured'}</small>
      </div>
      <button type="button" className="sv-button sv-settings-button" aria-label="Panorama settings" title="Panorama settings"
        aria-expanded={settingsOpen} onClick={() => { setDraftBrowserKey(browserKey); setSettingsOpen(value => !value); }}>
        <FontAwesomeIcon icon={faGear} aria-hidden="true" /> Settings</button>
    </div>
    {settingsOpen && <div className="sv-settings">
      <label className="sv-field"><span>Maps JavaScript browser key</span>
        <input type="password" aria-label="Maps JavaScript browser key"
          value={draftBrowserKey} onChange={event => setDraftBrowserKey(event.target.value)} autoComplete="off"
          spellCheck={false} placeholder="Browser-restricted key" /></label>
      <div style={S.helper}>Session memory only. A configured key does not confirm provider access.</div>
      {draftKeyIssue && <div role="alert" style={S.err}>{draftKeyIssue}</div>}
      <div className="sv-settings-actions">
        <button type="button" className="sv-button" onClick={() => setSettingsOpen(false)}>Cancel</button>
        <button type="button" className="sv-button sv-button-primary"
          disabled={!draftBrowserKey.trim() || !!draftKeyIssue}
          onClick={() => { setBrowserKey(draftBrowserKey.trim()); setSettingsOpen(false); }}>Add configuration</button>
      </div>
    </div>}
    <div className="sv-panorama-frame" style={{ display: 'flex', flexDirection: 'column' }}>
      {currentRequest && usableKey ? <GoogleStreetView browserKey={browserKey.trim()}
        request={currentRequest.location} requestKey={currentRequestKey} retryRevision={retryRevision}
        reuseCurrent={reuseCurrent} expectedPanoId={currentRequest.reuseCurrent?.panoId}
        radiusMetres={currentRequest.radiusMetres ?? radiusValue}
        initialHeadingDegrees={currentRequest.initialHeadingDegrees} onCamera={onCamera}
        active={contextCurrent} onStatus={(status, message) => { setViewerStatus(status); setViewerMessage(message ?? ''); }} />
        : <div role="status" style={{ minHeight: 260, display: 'grid', placeItems: 'center', padding: 12,
          color: 'var(--curio-text-secondary)' }}>
          {currentRequest ? keyIssue || 'Open Settings to configure a browser key.'
            : 'Connect a point or enter coordinates to inspect a location.'}
        </div>}
    </div>
    <div className="sv-info-row">
      <div className="sv-info-values">
        <span className="sv-info-item"><FontAwesomeIcon icon={faLocationArrow} aria-hidden="true" />
          {actual && Number.isFinite(actual.headingDegrees) ? `Heading ${Math.round(actual.headingDegrees)}°` : 'Heading unavailable'}</span>
        <span aria-hidden="true">·</span>
        <span className="sv-info-item"><FontAwesomeIcon icon={faLocationDot} aria-hidden="true" />
          {distance === null ? 'Distance unavailable' : `${Math.round(distance)} m from requested point`}</span>
        {camera && !actual && <span>Previous location visible</span>}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {canRetry && <button type="button" className="sv-button"
          onClick={() => setRetryRevision(value => value + 1)}>Retry</button>}
        <button type="button" className="sv-button" disabled={!canReturn}
          onClick={() => { setViewerStatus('loading'); setRetryRevision(value => value + 1); }}>
          <FontAwesomeIcon icon={faReply} aria-hidden="true" /> Return to requested location</button>
      </div>
    </div>
    {!contextCurrent && <div role="status" style={S.helper}>This view belongs to the previous editor tile. Inspect a point in the current tile to update it.</div>}
    {inputError && <div role="alert" style={S.err}>{inputError}</div>}
    <details className="sv-disclosure"><summary><FontAwesomeIcon icon={faLocationDot} aria-hidden="true" />
      Location details <FontAwesomeIcon className="sv-chevron sv-chevron-right" icon={faChevronRight} aria-hidden="true" />
      <FontAwesomeIcon className="sv-chevron sv-chevron-down" icon={faChevronDown} aria-hidden="true" /></summary>
      <div className="sv-section-body">
        {detail('Current location', actual?.description || 'Location description unavailable', !!actual?.description)}
        {detail('Camera coordinates', coordinateText(actual?.location), !!actual)}
        {detail('Requested coordinates', coordinateText(currentRequest?.location), !!currentRequest)}
        {copyNotice && <div role="status" style={S.helper}>{copyNotice}</div>}
      </div>
    </details>
    <details className="sv-disclosure"><summary><FontAwesomeIcon icon={faCrosshairs} aria-hidden="true" />
      Enter coordinates <FontAwesomeIcon className="sv-chevron sv-chevron-right" icon={faChevronRight} aria-hidden="true" />
      <FontAwesomeIcon className="sv-chevron sv-chevron-down" icon={faChevronDown} aria-hidden="true" /></summary>
      <div className="sv-section-body">
        <div className="sv-form-grid">
          <label className="sv-field"><span>Longitude</span><input aria-label="Longitude" type="number" min="-180" max="180" step="any"
            value={longitude} onChange={event => setLongitude(event.target.value)} /></label>
          <label className="sv-field"><span>Latitude</span><input aria-label="Latitude" type="number" min="-90" max="90" step="any"
            value={latitude} onChange={event => setLatitude(event.target.value)} /></label>
        </div>
        {manualError && <div role="alert" style={S.err}>{manualError}</div>}
        <button type="button" className="sv-button sv-button-primary" onClick={() => openPoint(manualPoint)}>View location</button>
      </div>
    </details>
    <details className="sv-disclosure"><summary><FontAwesomeIcon icon={faSliders} aria-hidden="true" />
      Advanced options <FontAwesomeIcon className="sv-chevron sv-chevron-right" icon={faChevronRight} aria-hidden="true" />
      <FontAwesomeIcon className="sv-chevron sv-chevron-down" icon={faChevronDown} aria-hidden="true" /></summary>
      <div className="sv-section-body">
        <div className="sv-form-grid">
          <label className="sv-field"><span>Search radius (m)</span><input aria-label="Search radius metres" type="number" min="1" max="1000"
            value={radius} onChange={event => setRadius(event.target.value)} /></label>
          <label className="sv-field"><span>Initial heading (°)</span><input aria-label="Initial heading degrees" type="number" step="any"
            value={heading} onChange={event => setHeading(event.target.value)} /></label>
        </div>
        <div style={S.helper}>Maximum distance from the requested point to search for available imagery.</div>
      </div>
    </details>
  </div> };
};
