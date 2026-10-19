import React from 'react';

type Point = [number, number];
function distanceMeters(a: Point, b: Point): number {
  const radians = Math.PI / 180;
  const latitudeA = a[1] * radians;
  const latitudeB = b[1] * radians;
  const halfLatitude = (b[1] - a[1]) * radians / 2;
  const halfLongitude = (b[0] - a[0]) * radians / 2;
  const value = Math.sin(halfLatitude) ** 2 + Math.cos(latitudeA) * Math.cos(latitudeB) * Math.sin(halfLongitude) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(value)));
}
type Listener = { remove: () => void };
type LatLng = { lat: () => number; lng: () => number };
type StreetViewLocation = { latLng?: LatLng; pano?: string; description?: string; shortDescription?: string };
type Panorama = {
  addListener: (name: string, callback: () => void) => Listener;
  getPosition: () => LatLng | null;
  getPov: () => { heading: number; pitch: number } | null;
  getPano: () => string;
  getLocation?: () => StreetViewLocation | null;
  getZoom?: () => number;
  setVisible: (visible: boolean) => void;
  setPano?: (pano: string) => void;
  setPosition?: (position: { lat: number; lng: number }) => void;
  setPov?: (pov: { heading: number; pitch: number }) => void;
};
type MapsApi = {
  StreetViewService: new () => { getPanorama: (request: unknown) => Promise<{ data: { location?: StreetViewLocation } }> };
  StreetViewPanorama: new (element: HTMLElement, options: unknown) => Panorama;
  StreetViewPreference?: { NEAREST: unknown };
  event?: { trigger: (instance: Panorama, name: string) => void };
};

declare global { interface Window { google?: { maps?: MapsApi } } }

let pending: Promise<MapsApi> | null = null;
/** A browser-intended key is supplied by the viewer UI and never persisted by this loader. */
export function loadGoogleStreetView(browserKey: string): Promise<MapsApi> {
  if (window.google?.maps?.StreetViewPanorama && window.google.maps.StreetViewService) return Promise.resolve(window.google.maps);
  if (pending) return pending;
  pending = new Promise<MapsApi>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(browserKey)}`;
    script.async = true;
    script.onload = () => {
      const maps = window.google?.maps;
      if (maps?.StreetViewPanorama && maps.StreetViewService) resolve(maps);
      else reject(new Error('Google Maps JavaScript API did not provide Street View. Check that the API is enabled for this browser key.'));
    };
    script.onerror = () => { script.remove(); reject(new Error('Google Maps JavaScript API could not be loaded. Check the browser key and its referrer restrictions.')); };
    document.head.appendChild(script);
  }).catch(error => { pending = null; throw error; });
  return pending;
}

/** Bearing from the panorama to the clicked point, clockwise from north. */
export function bearingToward(from: Point, to: Point): number {
  const radians = Math.PI / 180;
  const deltaLongitude = (to[0] - from[0]) * radians;
  const fromLatitude = from[1] * radians;
  const toLatitude = to[1] * radians;
  const y = Math.sin(deltaLongitude) * Math.cos(toLatitude);
  const x = Math.cos(fromLatitude) * Math.sin(toLatitude)
    - Math.sin(fromLatitude) * Math.cos(toLatitude) * Math.cos(deltaLongitude);
  return (Math.atan2(y, x) / radians + 360) % 360;
}

export interface LiveCamera { location: Point; headingDegrees: number; panoId: string; pitchDegrees?: number; zoom?: number;
  description?: string }

function matchingDescription(viewer: Panorama, position: Point, panoId: string, lookup?: StreetViewLocation | null): string | undefined {
  const matches = (location?: StreetViewLocation | null) => location && location.pano === panoId
    && (!location.latLng || distanceMeters(position, [location.latLng.lng(), location.latLng.lat()]) < 5);
  const current = viewer.getLocation?.();
  const location = matches(current) ? current : matches(lookup) ? lookup : null;
  return location?.description?.trim() || location?.shortDescription?.trim() || undefined;
}
interface Props {
  browserKey: string;
  request: Point;
  requestKey?: string;
  retryRevision?: number;
  reuseCurrent?: boolean;
  expectedPanoId?: string;
  radiusMetres: number;
  initialHeadingDegrees?: number;
  onCamera: (camera: LiveCamera, requestKey?: string) => void;
  active?: boolean;
  onStatus?: (status: 'loading' | 'ready' | 'unavailable' | 'error', message?: string) => void;
}

/** Keep the native panorama mounted while public service lookups change target. */
export function GoogleStreetView({ browserKey, request, requestKey, retryRevision = 0, reuseCurrent = false, expectedPanoId,
  radiusMetres, initialHeadingDegrees, onCamera, onStatus, active = true }: Props) {
  const container = React.useRef<HTMLDivElement>(null);
  const callback = React.useRef(onCamera);
  callback.current = onCamera;
  const statusCallback = React.useRef(onStatus);
  statusCallback.current = onStatus;
  const panoramaRef = React.useRef<Panorama | null>(null);
  const mapsRef = React.useRef<MapsApi | null>(null);
  const listenersRef = React.useRef<Listener[]>([]);
  const observerRef = React.useRef<ResizeObserver | null>(null);
  const generation = React.useRef(0);
  const loadedKey = React.useRef<string | undefined>(undefined);
  const adoptedKey = React.useRef<string | undefined>(undefined);
  const awaitingCamera = React.useRef<{ key: string; location: Point; panoId?: string } | null>(null);
  const lookupLocation = React.useRef<StreetViewLocation | null>(null);
  const [status, setStatus] = React.useState<'loading' | 'ready' | 'unavailable' | 'error'>('loading');
  const [error, setError] = React.useState('');
  const [camera, setCamera] = React.useState<LiveCamera | null>(null);
  const longitude = request[0];
  const latitude = request[1];
  const targetKey = requestKey ?? `${longitude},${latitude}`;

  const changeStatus = (next: 'loading' | 'ready' | 'unavailable' | 'error', message?: string) => {
    setStatus(next); statusCallback.current?.(next, message);
  };

  // A service result identifies the target; only the native viewer can confirm it.
  // Ignore events from the previous panorama while that target is still loading.
  const publishViewer = (viewer: Panorama) => {
    const key = loadedKey.current;
    const position = viewer.getPosition(); const pov = viewer.getPov();
    if (!key || !position || !pov || !Number.isFinite(pov.heading)) return;
    const location: Point = [position.lng(), position.lat()];
    if (!location.every(Number.isFinite)) return;
    const pending = awaitingCamera.current;
    if (pending && (pending.key !== key || (pending.panoId && viewer.getPano() !== pending.panoId)
      || distanceMeters(location, pending.location) > 1)) return;
    if (pending) { awaitingCamera.current = null; changeStatus('ready'); }
    const next: LiveCamera = { location,
      headingDegrees: (pov.heading % 360 + 360) % 360, panoId: viewer.getPano() || '',
      pitchDegrees: Number.isFinite(pov.pitch) ? pov.pitch : undefined,
      ...(viewer.getZoom && Number.isFinite(viewer.getZoom()) ? { zoom: viewer.getZoom() } : {}),
      description: matchingDescription(viewer, location, viewer.getPano() || '', lookupLocation.current),
    };
    setCamera(next); callback.current(next, key);
  };

  React.useEffect(() => () => {
    generation.current += 1;
    observerRef.current?.disconnect();
    listenersRef.current.forEach(listener => listener.remove());
    panoramaRef.current?.setVisible(false);
  }, []);

  React.useEffect(() => {
    const currentGeneration = ++generation.current;
    const current = () => currentGeneration === generation.current;
    loadedKey.current = undefined;
    awaitingCamera.current = null;
    if (!active) return;
    if (reuseCurrent && adoptedKey.current !== targetKey) {
      if (!panoramaRef.current || panoramaRef.current.getPano() !== expectedPanoId) {
        setError('The panorama changed before its tile could be opened. Inspect the camera location again.');
        changeStatus('error', 'The panorama changed before its tile could be opened. Inspect the camera location again.');
        return;
      }
      adoptedKey.current = targetKey;
      loadedKey.current = targetKey;
      changeStatus('ready');
      const position = panoramaRef.current.getPosition(); const pov = panoramaRef.current.getPov();
      if (position && pov && Number.isFinite(pov.heading)) {
        const next: LiveCamera = { location: [position.lng(), position.lat()], headingDegrees: pov.heading,
          panoId: panoramaRef.current.getPano() || '', pitchDegrees: pov.pitch,
          description: matchingDescription(panoramaRef.current, [position.lng(), position.lat()], panoramaRef.current.getPano() || '', lookupLocation.current) };
        setCamera(next); callback.current(next, targetKey);
      }
      return;
    }
    changeStatus('loading');
    setError('');
    lookupLocation.current = null;
    const start = async () => {
      try {
        const maps = await loadGoogleStreetView(browserKey);
        if (!current()) return;
        const response = await new maps.StreetViewService().getPanorama({
          location: { lat: latitude, lng: longitude }, radius: radiusMetres,
          ...(maps.StreetViewPreference ? { preference: maps.StreetViewPreference.NEAREST } : {}),
        });
        if (!current()) return;
        const location = response.data.location?.latLng;
        if (!location || !container.current) throw new Error('Street View returned no panorama position.');
        const actual: Point = [location.lng(), location.lat()];
        if (distanceMeters([longitude, latitude], actual) > radiusMetres + 1) {
          changeStatus('unavailable', `No live Street View panorama is available within ${radiusMetres} m of this point.`);
          return;
        }
        lookupLocation.current = response.data.location ?? null;
        const heading = initialHeadingDegrees !== undefined && Number.isFinite(initialHeadingDegrees)
          ? (initialHeadingDegrees % 360 + 360) % 360
          : distanceMeters([longitude, latitude], actual) > 1
            ? bearingToward(actual, [longitude, latitude]) : 0;
        awaitingCamera.current = { key: targetKey, location: actual, panoId: response.data.location?.pano };
        loadedKey.current = targetKey;
        let viewer = panoramaRef.current;
        if (viewer?.setPosition && viewer.setPov) {
          if (response.data.location?.pano && viewer.setPano) viewer.setPano(response.data.location.pano);
          viewer.setPosition({ lat: actual[1], lng: actual[0] });
          viewer.setPov({ heading, pitch: 0 });
          viewer.setVisible(true);
        } else {
          listenersRef.current.forEach(listener => listener.remove());
          observerRef.current?.disconnect();
          viewer?.setVisible(false);
          viewer = new maps.StreetViewPanorama(container.current, {
            pano: response.data.location?.pano,
            position: { lat: actual[1], lng: actual[0] },
            pov: { heading, pitch: 0 }, visible: true,
            addressControl: false, fullscreenControl: false, linksControl: true,
            motionTracking: false, motionTrackingControl: false,
          });
          panoramaRef.current = viewer;
          const installed = viewer;
          const publish = () => publishViewer(installed);
          listenersRef.current = [installed.addListener('position_changed', publish),
            installed.addListener('pov_changed', publish), installed.addListener('pano_changed', publish)];
          if (typeof ResizeObserver !== 'undefined') {
            observerRef.current = new ResizeObserver(() => maps.event?.trigger(installed, 'resize'));
            observerRef.current.observe(container.current);
          }
          mapsRef.current = maps;
        }
        publishViewer(viewer);
      } catch (cause) {
        if (!current()) return;
        loadedKey.current = undefined;
        awaitingCamera.current = null;
        // Only expose recognized status codes, never raw exceptions or credentials.
        const raw = cause instanceof Error ? cause.message : String((cause as any)?.code ?? '');
        if (/ZERO_RESULTS|no panorama|not found/i.test(raw)) {
          changeStatus('unavailable', `No live Street View panorama is available within ${radiusMetres} m of this point.`);
        } else {
          const code = raw.match(/REQUEST_DENIED|OVER_QUERY_LIMIT|INVALID_REQUEST|UNKNOWN_ERROR|InvalidKeyMapError|RefererNotAllowedMapError|ApiNotActivatedMapError/i)?.[0];
          const message = code ? `Street View request failed (${code}). Check the browser key, API access, and restrictions.`
            : /Maps JavaScript API could not be loaded/i.test(raw)
              ? 'Google Maps JavaScript API could not be loaded. Check the browser key and its referrer restrictions.'
              : 'Street View could not open. Check the browser key, Maps JavaScript API access, and network connection.';
          setError(message); changeStatus('error', message);
        }
      }
    };
    void start();
    return () => { generation.current += 1; };
  }, [browserKey, targetKey, retryRevision, active]);

  return <div style={{ display: 'flex', flexDirection: 'column', gap: 5, minHeight: 0, flex: 1 }}>
    {status === 'loading' && <div role="status">Looking for a live Street View panorama within {radiusMetres} m…{camera ? ' Showing the previous location until this request is confirmed.' : ''}</div>}
    {status === 'unavailable' && <div role="status">No live Street View panorama is available within {radiusMetres} m of this point.{camera ? ' Showing the previous location.' : ''}</div>}
    {status === 'error' && <div role="alert">{error}{camera ? ' Showing the previous location.' : ''}</div>}
    <div ref={container} aria-label="Interactive Google Street View panorama"
      style={{ minHeight: 200, flex: 1, display: (status === 'error' || status === 'unavailable') && !camera ? 'none' : 'block', background: '#e5e7eb' }} />
  </div>;
}
