import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { faCircleInfo } from '@fortawesome/free-solid-svg-icons/faCircleInfo';
import { faCopy } from '@fortawesome/free-solid-svg-icons/faCopy';
import { faXmark } from '@fortawesome/free-solid-svg-icons/faXmark';
import type { Feature, FeatureCollection, Position } from './geojson';
import { assetUrl, fetchData } from './resourceResolver';
import { resolveSelectedResourceTemplate } from './selectedResources';
import {
  Bounds, clipNetworkToBounds, connectNetworkNodes, deleteNetworkNode,
  deleteNetworkNodesInBounds, featureBounds, networkNodes,
  moveNetworkNode, splitNetworkEdge, validateNetwork,
} from './sidewalkEditOperations';
import { validateSidewalkTopology } from './sidewalkTopology';
import { makeNetworkEditEnvelope, SIDEWALK_NETWORK_EDIT_CHANNEL } from './networkEditContract';
import type { SidewalkNetworkEdit } from './networkEditContract';
import { buildEditProvenance } from './provenance';
import { savedTile, scopeLegacyTiles, tileStorageKey, type OverviewConfig } from './overviewData';
import {
  ACTIVE_TILE_CHANNEL, ACTIVE_TILE_SCHEMA, CAMERA_CONTEXT_SCHEMA, cameraMatchesTile, latestActiveTileRequest,
  INSPECTION_REQUEST_CHANNEL, INSPECTION_REQUEST_SCHEMA, latestCameraContext, pointFromWgs84,
  pointToWgs84, sourceFingerprint as makeSourceFingerprint, tileGeometryWgs84,
  type ActiveTileEvent, type CameraContextEvent, type InspectionRequest,
} from './streetViewContract';
import { pointInPolygon } from './streetViewImages';
import { cameraBoundary } from './cameraBoundary';
import { TILE_DIRECTIONS, tileAtPoint, type TileNeighborIndex, type TileDirection } from './tileNeighbors';
import { sidewalkNodeStyles as ui } from './sidewalkNodeStyles';
import { nodeUiStyles as S } from '../../curio.streetvision@1/sources/nodeUiStyles';
import {
  PANORAMA_REQUEST_CHANNEL, PANORAMA_REQUEST_SCHEMA, PANORAMA_CONTEXT_CHANNEL, PANORAMA_CONTEXT_SCHEMA,
  latestPanoramaCamera, latestPanoramaStatus, type PanoramaStatus,
} from '../../curio.streetvision@1/sources/panoramaContract';

function panoramaRequestForInspection(inspection: InspectionRequest, reuseCurrent?: { viewerId: string; panoId: string }) {
  return {
    schema: PANORAMA_REQUEST_SCHEMA,
    requestId: `${inspection.editorId}:${inspection.selectionEpoch}:${inspection.selectionRevision}:${inspection.requestRevision}`,
    revision: inspection.requestRevision,
    location: inspection.location,
    crs: 'EPSG:4326' as const,
    ...(reuseCurrent ? { reuseCurrent } : {}),
  };
}

/** Match Stewards' shortest rotation across north (for example 350° → 10°). */
export function shortestHeadingDelta(from: number, to: number): number {
  return ((to - from) % 360 + 540) % 360 - 180;
}

export const SIDEWALK_EDIT_SCHEMA = 'curio.sidewalk-tile-edit/v1';
// Resources must come from Prepare, explicit templates, or selected feature properties.
export const DEFAULT_IMAGE_TEMPLATE = '';
export const DEFAULT_NETWORK_TEMPLATE = '';

type EditToolIconName = 'draw' | 'move' | 'delete' | 'undo' | 'redo' | 'inspect';

/** Use the same Font Awesome icon definitions as Curio's Details and Copy buttons. */
function CurioUtilityIcon({ name }: { name: 'circle-info' | 'copy' | 'close' }) {
  const icon = name === 'circle-info' ? faCircleInfo : name === 'copy' ? faCopy : faXmark;
  const paths = icon.icon[4];
  return <svg aria-hidden="true" data-icon={icon.iconName}
    viewBox={`0 0 ${icon.icon[0]} ${icon.icon[1]}`} width="1em" height="1em" fill="currentColor">
    {Array.isArray(paths) ? paths.map((path, index) => <path key={index} d={path} />) : <path d={paths} />}
  </svg>;
}

/** One centered chevron geometry for every direction, independent of font metrics. */
function TileNavigationChevron({ direction }: { direction: TileDirection }) {
  const rotation = { north: '180deg', south: '0deg', east: '-90deg', west: '90deg' }[direction];
  return <svg aria-hidden="true" data-tile-chevron={direction} viewBox="0 0 24 24"
    width="20" height="20" fill="none" style={{ display: 'block', transform: `rotate(${rotation})` }}>
    <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.5"
      strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

function EditToolIcon({ name }: { name: EditToolIconName }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  if (name === 'draw') return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" {...common}><path d="M4 19 12 12 20 4" /><circle cx="4" cy="19" r="2" fill="currentColor" /><circle cx="12" cy="12" r="2" fill="currentColor" /><circle cx="20" cy="4" r="2" fill="currentColor" /></svg>;
  if (name === 'move') return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" {...common}><path d="M12 2v20M2 12h20m-10-10-3 3m3-3 3 3m-3 17-3-3m3 3 3-3M2 12l3-3m-3 3 3 3m17-3-3-3m3 3-3 3" /></svg>;
  if (name === 'delete') return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" {...common}><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" /></svg>;
  if (name === 'inspect') return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" {...common}><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2" fill="currentColor" /><path d="M12 2v3m0 14v3M2 12h3m14 0h3" /></svg>;
  if (name === 'undo') return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" {...common}><path d="m9 7-5 5 5 5M4 12h9a6 6 0 0 1 6 6" /></svg>;
  return <svg aria-hidden="true" viewBox="0 0 24 24" width="24" height="24" {...common}><path d="m15 7 5 5-5 5m5-5h-9a6 6 0 0 0-6 6" /></svg>;
}

export interface SidewalkTileEditConfig {
  schema: typeof SIDEWALK_EDIT_SCHEMA;
  mode?: 'input-overview';
  imageUrlTemplate: string;
  networkUrlTemplate: string;
  overview?: OverviewConfig;
  activeSelection?: { tileId: string; sourceFingerprint: string };
  byTile: Record<string, { network: FeatureCollection; originalNetwork?: FeatureCollection; past: FeatureCollection[]; future: FeatureCollection[]; futureOperations?: string[]; operations: string[]; revision?: number; committedNetwork?: FeatureCollection; provenance?: Record<string, unknown>; committedEdit?: SidewalkNetworkEdit; [key: string]: unknown }>;
}

export function parseSidewalkEditConfig(raw: unknown): SidewalkTileEditConfig {
  try {
    const value = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
    if (value && typeof value === 'object' && (value as any).schema === SIDEWALK_EDIT_SCHEMA) {
      return {
        schema: SIDEWALK_EDIT_SCHEMA,
        ...((value as any).mode === 'input-overview' ? { mode: 'input-overview' as const } : {}),
        imageUrlTemplate: String((value as any).imageUrlTemplate || DEFAULT_IMAGE_TEMPLATE),
        networkUrlTemplate: String((value as any).networkUrlTemplate || DEFAULT_NETWORK_TEMPLATE),
        ...((value as any).overview ? { overview: { ...((value as any).overview.sourceIdentity ? { sourceIdentity: String((value as any).overview.sourceIdentity) } : {}), datasetId: String((value as any).overview.datasetId ?? ''), gridUrl: String((value as any).overview.gridUrl ?? ''), networkUrl: String((value as any).overview.networkUrl ?? ''), boundariesUrl: String((value as any).overview.boundariesUrl ?? '') } } : {}),
        ...((value as any).activeSelection?.tileId && (value as any).activeSelection?.sourceFingerprint
          ? { activeSelection: { tileId: String((value as any).activeSelection.tileId), sourceFingerprint: String((value as any).activeSelection.sourceFingerprint) } } : {}),
        byTile: (value as any).byTile && typeof (value as any).byTile === 'object' ? (value as any).byTile : {},
      };
    }
  } catch { /* an empty or old code buffer uses defaults */ }
  return { schema: SIDEWALK_EDIT_SCHEMA, imageUrlTemplate: DEFAULT_IMAGE_TEMPLATE, networkUrlTemplate: DEFAULT_NETWORK_TEMPLATE, byTile: {} };
}

function unwrap(value: any): any {
  if (!value || typeof value !== 'object') return value;
  if (value.type === 'FeatureCollection') return value;
  if (value.dataType === 'geodataframe' || value.dataType === 'geojson') return unwrap(value.data);
  if (value.data && typeof value.data === 'object') return unwrap(value.data);
  if (value.content && typeof value.content === 'object') return unwrap(value.content);
  return value;
}

async function resolveSelection(value: any, signal: AbortSignal): Promise<FeatureCollection | null> {
  let raw = unwrap(value);
  if (typeof raw === 'string' && raw.trim()) {
    const reference = raw.trim();
    try {
      raw = unwrap(JSON.parse(reference));
    } catch {
      raw = unwrap(await fetchData(reference, signal));
    }
  }
  if (raw?.path && !raw.features) {
    const result = await fetchData(raw.path, signal);
    raw = unwrap(result);
  }
  if (raw?.type === 'Feature' && raw.geometry) return { type: 'FeatureCollection', features: [raw] };
  if (raw?.type === 'FeatureCollection' && Array.isArray(raw.features)) return raw as FeatureCollection;
  return null;
}

function fileUrl(path: string): string {
  return assetUrl(path);
}

async function loadNetwork(path: string, signal: AbortSignal): Promise<FeatureCollection> {
  const response = await fetch(fileUrl(path), { signal });
  if (!response.ok) throw new Error(`Network data could not be loaded (${response.status}).`);
  const raw = unwrap(await response.json());
  if (raw?.type !== 'FeatureCollection' || !Array.isArray(raw.features)) {
    throw new Error('The network asset must be a GeoJSON FeatureCollection.');
  }
  return raw as FeatureCollection;
}

const VIEW = 1000;
const OUTSIDE_CAMERA_TAG_WIDTH = 485;
const OUTSIDE_CAMERA_TAG_HEIGHT = 52;
// Marker dimensions are in the editor's 1000-unit image coordinate space.
// React Flow zoom scales the image and its markers together.
const STEWARDS_CAMERA_SIZE = 40;
const CAMERA_CUE_MARGIN = STEWARDS_CAMERA_SIZE / 2 + 6;
const NETWORK_NODE_RADIUS = 10;
const NETWORK_STROKE = '#f07800';
const NETWORK_STROKE_WIDTH = 3;
const coordinateKey = (point: Position) => `${Math.round(point[0] * 1e8) / 1e8},${Math.round(point[1] * 1e8) / 1e8}`;
const emptyFC: FeatureCollection = { type: 'FeatureCollection', features: [] };

function pointToView(p: Position, bounds: Bounds): [number, number] {
  const width = Math.max(bounds[2] - bounds[0], 1e-12);
  const height = Math.max(bounds[3] - bounds[1], 1e-12);
  return [(p[0] - bounds[0]) / width * VIEW, VIEW - (p[1] - bounds[1]) / height * VIEW];
}
export function viewToPoint(x: number, y: number, bounds: Bounds): Position {
  return [bounds[0] + (x / VIEW) * (bounds[2] - bounds[0]), bounds[3] - (y / VIEW) * (bounds[3] - bounds[1])];
}
/** The image and SVG occupy the same aspect-preserving canvas. */
export function clientToViewPoint(rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
  clientX: number, clientY: number): [number, number] {
  if (rect.width <= 0 || rect.height <= 0) throw new Error('Editor image has no visible area.');
  return [(clientX - rect.left) / rect.width * VIEW, (clientY - rect.top) / rect.height * VIEW];
}
function linePath(feature: Feature, bounds: Bounds): string {
  if (feature.geometry?.type !== 'LineString') return '';
  return feature.geometry.coordinates.map((p: Position, i: number) => {
    const [x, y] = pointToView(p, bounds);
    return `${i ? 'L' : 'M'}${x},${y}`;
  }).join(' ');
}
function closestLineSegment(fc: FeatureCollection, p: Position): { featureIndex: number; segmentIndex: number; point: Position; distance: number } | null {
  let best: { featureIndex: number; segmentIndex: number; point: Position; distance: number } | null = null;
  fc.features.forEach((f, featureIndex) => {
    if (f.geometry?.type !== 'LineString') return;
    for (let i = 1; i < f.geometry.coordinates.length; i += 1) {
      const a = f.geometry.coordinates[i - 1]; const b = f.geometry.coordinates[i];
      const dx = b[0] - a[0]; const dy = b[1] - a[1];
      const d2 = dx * dx + dy * dy || 1;
      const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / d2));
      const distance = Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
      if (!best || distance < best.distance) best = { featureIndex, segmentIndex: i - 1, distance, point: [a[0] + t * dx, a[1] + t * dy] };
    }
  });
  return best;
}

interface Props {
  nodeId: string;
  input: unknown;
  originalNetwork?: FeatureCollection;
  selectionIndex: number | null;
  allowSingleTile?: boolean;
  selectionFeatureId: string | null;
  selectionFeature?: Feature | null;
  sourceFingerprint?: string;
  incomingInteractions?: unknown;
  config: SidewalkTileEditConfig;
  persist: (config: SidewalkTileEditConfig) => void;
  emit: (output: any) => void;
  onCommitted?: (config: SidewalkTileEditConfig, output: unknown) => void;
  interactionsCallback?: (interactions: any, nodeId: string) => void;
  setStatus: (status: { code: string; content: string }) => void;
  neighborIndex?: TileNeighborIndex | null;
  onNavigate?: (tileId: string) => void;
}

export function SidewalkTileEditor({ nodeId, input, originalNetwork, selectionIndex, allowSingleTile = true, selectionFeatureId, selectionFeature, sourceFingerprint, incomingInteractions, config, persist, emit, onCommitted, interactionsCallback, setStatus, neighborIndex, onNavigate }: Props) {
  const [selection, setSelection] = useState<FeatureCollection | null>(null);
  const [network, setNetwork] = useState<FeatureCollection>(emptyFC);
  const [sourceNetwork, setSourceNetwork] = useState<FeatureCollection>(emptyFC);
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [tileCrs, setTileCrs] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [imageReady, setImageReady] = useState(false);
  const [imageAspect, setImageAspect] = useState(1);
  const [imageGeneration, setImageGeneration] = useState(0);
  const imageSvg = useRef<SVGSVGElement>(null);
  const [markerAspect, setMarkerAspect] = useState(1);
  const requestGeneration = useRef(0);
  const selectionEpoch = useRef(`${new Date().toISOString()}:${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`);
  const selectionRevision = useRef(0);
  const currentActiveTile = useRef<ActiveTileEvent | null>(null);
  const callbackRef = useRef(interactionsCallback);
  callbackRef.current = interactionsCallback;
  const [camera, setCamera] = useState<CameraContextEvent | null>(null);
  const [displayHeading, setDisplayHeading] = useState<number | null>(null);
  const accumulatedHeading = useRef<number | null>(null);
  const cameraRevisions = useRef(new Map<string, number>());
  const fingerprint = sourceFingerprint ?? makeSourceFingerprint(config.overview?.sourceIdentity, config.imageUrlTemplate, config.networkUrlTemplate, input);
  const request = useMemo(() => ({ input, originalNetwork, selectionIndex, selectionFeatureId, selectionFeature,
    allowSingleTile, imageTemplate: config.imageUrlTemplate, networkTemplate: config.networkUrlTemplate }),
    [input, originalNetwork, selectionIndex, selectionFeatureId, selectionFeature, allowSingleTile, config.imageUrlTemplate, config.networkUrlTemplate]);
  const [loadedRequest, setLoadedRequest] = useState<typeof request | null>(null);
  const configRef = useRef(config);
  useEffect(() => { configRef.current = config; }, [config]);
  const persistConfig = (next: SidewalkTileEditConfig) => { const scoped = scopeLegacyTiles(next); configRef.current = scoped; persist(scoped); };
  const [mode, setMode] = useState<'select' | 'draw' | 'move' | 'delete-area' | 'inspect'>('select');
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [warningsOpen, setWarningsOpen] = useState(false);
  const [copyStatus, setCopyStatus] = useState('');
  const sourcesButton = useRef<HTMLButtonElement>(null);
  const sourcesPanel = useRef<HTMLDivElement>(null);
  const suppressOutsideClick = useRef(false);
  const [navigationTarget, setNavigationTarget] = useState<string | null>(null);
  const [movementNotice, setMovementNotice] = useState('');
  const [requestedPoint, setRequestedPoint] = useState<[number, number] | null>(null);
  const [inspectionStatus, setInspectionStatus] = useState<PanoramaStatus | null>(null);
  const inspectionRevision = useRef(0);
  const currentInspection = useRef<InspectionRequest | null>(null);
  const pendingCameraAdoption = useRef<{ tileId: string; camera: CameraContextEvent;
    requestId: string; revision: number; cameraRevision: number } | null>(null);
  const [drawing, setDrawing] = useState<Position[]>([]);
  const drawingRef = useRef<Position[]>([]);
  const pendingDraw = useRef<{ clicks: Array<{ point: Position; screen: [number, number] }>; timer: ReturnType<typeof setTimeout> } | null>(null);
  const [drawingCursor, setDrawingCursor] = useState<Position | null>(null);
  const [marqueeStart, setMarqueeStart] = useState<[number, number] | null>(null);
  const [marqueeEnd, setMarqueeEnd] = useState<[number, number] | null>(null);
  const [selectedNode, setSelectedNode] = useState<Position | null>(null);
  const [past, setPast] = useState<FeatureCollection[]>([]);
  const [future, setFuture] = useState<FeatureCollection[]>([]);
  const [futureOperations, setFutureOperations] = useState<string[]>([]);
  const [operations, setOperations] = useState<string[]>([]);
  const [drag, setDrag] = useState<{ from: Position; pointer: number; original: FeatureCollection } | null>(null);
  const dragMoved = useRef(false);
  drawingRef.current = drawing;
  const tileFeature = selection?.features?.[0];
  const tileId = String(tileFeature?.properties?.tile_id ?? tileFeature?.properties?.tileId ?? '');
  useEffect(() => setWarningsOpen(false), [tileId]);
  const ready = !!tileId && loadedRequest === request && !loading && !error && imageReady;
  useEffect(() => {
    if (navigationTarget && tileId === navigationTarget && (ready || error)) setNavigationTarget(null);
  }, [navigationTarget, tileId, ready, error]);
  const tileBounds = featureBounds(tileFeature);
  const viewBounds = bounds ?? tileBounds;
  useEffect(() => {
    const svg = imageSvg.current;
    if (!svg) return;
    // The image overlay stretches its 1000-unit viewBox to the editor panel.
    // Correct marker shapes for that aspect ratio, without counter-scaling zoom.
    const measure = () => {
      const { width, height } = svg.getBoundingClientRect();
      if (width > 0 && height > 0) {
        const aspect = width / height;
        setMarkerAspect(previous => Math.abs(previous - aspect) > 0.001 ? aspect : previous);
      }
    };
    measure();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
    observer?.observe(svg);
    window.addEventListener('resize', measure);
    return () => { observer?.disconnect(); window.removeEventListener('resize', measure); };
  }, [ready, tileId]);
  const sendActiveTile = useCallback((feature: Feature | null, crs?: string | null) => {
    const previousInspection = currentInspection.current;
    const id = feature ? String(feature.properties?.tile_id ?? feature.properties?.tileId ?? '') : null;
    if (feature && !id) throw new Error('Selected tile has no tile ID.');
    const next: ActiveTileEvent = {
      schema: ACTIVE_TILE_SCHEMA, editorId: nodeId, sourceFingerprint: fingerprint,
      selectionEpoch: selectionEpoch.current, selectionRevision: ++selectionRevision.current,
      tileId: id, geometry: feature ? tileGeometryWgs84(feature, crs) : null, crs: 'EPSG:4326',
    };
    currentActiveTile.current = next;
    // A panorama continues to report its location while the editor switches tiles.
    // Keep that accepted camera context so every tile can show whether it contains it.
    // A new inspection supersedes this request; clearing the tile removes it.
    if (!id || previousInspection?.sourceFingerprint !== fingerprint) {
      currentInspection.current = null;
      setRequestedPoint(null);
      setInspectionStatus(null);
      cameraRevisions.current.clear();
      setCamera(null);
      accumulatedHeading.current = null;
      setDisplayHeading(null);
    }
    callbackRef.current?.({ [ACTIVE_TILE_CHANNEL]: next,
      ...(!id && previousInspection ? { [PANORAMA_CONTEXT_CHANNEL]: {
        schema: PANORAMA_CONTEXT_SCHEMA,
        requestId: panoramaRequestForInspection(previousInspection).requestId,
        revision: previousInspection.requestRevision, active: false as const,
      } } : {}),
    }, nodeId);
    const adoption = pendingCameraAdoption.current;
    if (id && adoption?.tileId === id && adoption.camera.location) {
      pendingCameraAdoption.current = null;
      const inspection: InspectionRequest = {
        schema: INSPECTION_REQUEST_SCHEMA, editorId: next.editorId, sourceFingerprint: next.sourceFingerprint,
        selectionEpoch: next.selectionEpoch, selectionRevision: next.selectionRevision,
        requestRevision: ++inspectionRevision.current, tileId: id,
        location: adoption.camera.location, crs: 'EPSG:4326',
      };
      currentInspection.current = inspection;
      setRequestedPoint(inspection.location);
      setInspectionStatus(null);
      callbackRef.current?.({ [ACTIVE_TILE_CHANNEL]: next, [INSPECTION_REQUEST_CHANNEL]: inspection,
        [PANORAMA_REQUEST_CHANNEL]: panoramaRequestForInspection(inspection, {
          viewerId: adoption.camera.viewerId, panoId: adoption.camera.imageId,
        }) }, nodeId);
    }
  }, [nodeId, fingerprint]);
  const incomingRequest = latestActiveTileRequest(incomingInteractions);
  const lastRepliedRequest = useRef('');
  useEffect(() => {
    if (!incomingRequest || !currentActiveTile.current) return;
    // A request may arrive while restoration has only published the empty
    // tile. Reply again when the restored active tile gets its own revision.
    const key = `${incomingRequest.viewerId}:${incomingRequest.viewerEpoch ?? ''}:${incomingRequest.requestRevision}:${currentActiveTile.current.selectionRevision}`;
    if (lastRepliedRequest.current === key) return;
    lastRepliedRequest.current = key;
    callbackRef.current?.({
      [ACTIVE_TILE_CHANNEL]: currentActiveTile.current,
      ...(currentInspection.current ? { [INSPECTION_REQUEST_CHANNEL]: currentInspection.current } : {}),
      ...(currentInspection.current ? { [PANORAMA_REQUEST_CHANNEL]: panoramaRequestForInspection(currentInspection.current) } : {}),
    }, nodeId);
  }, [incomingRequest, nodeId, tileId]);
  const incomingCamera = latestCameraContext(incomingInteractions);
  const incomingPanoramaCamera = latestPanoramaCamera(incomingInteractions);
  const incomingPanoramaStatus = latestPanoramaStatus(incomingInteractions);
  useEffect(() => {
    const inspection = currentInspection.current;
    if (!inspection || !incomingPanoramaStatus
      || incomingPanoramaStatus.requestId !== panoramaRequestForInspection(inspection).requestId
      || incomingPanoramaStatus.revision !== inspection.requestRevision) return;
    setInspectionStatus(previous => previous?.requestId === incomingPanoramaStatus.requestId
      && previous.revision === incomingPanoramaStatus.revision
      && previous.viewerId === incomingPanoramaStatus.viewerId
      && previous.state === incomingPanoramaStatus.state
      && previous.message === incomingPanoramaStatus.message ? previous : incomingPanoramaStatus);
  }, [incomingPanoramaStatus]);
  useEffect(() => {
    const pending = pendingCameraAdoption.current;
    if (!pending || !incomingPanoramaCamera || incomingPanoramaCamera.requestId !== pending.requestId
      || incomingPanoramaCamera.revision !== pending.revision
      || incomingPanoramaCamera.viewerId !== pending.camera.viewerId
      || incomingPanoramaCamera.cameraRevision <= pending.cameraRevision) return;
    // Native movement may continue while the destination image/network loads.
    // Follow that same viewer, but never silently change the chosen destination.
    pending.cameraRevision = incomingPanoramaCamera.cameraRevision;
    pending.camera = { ...pending.camera, imageId: incomingPanoramaCamera.panoId,
      location: incomingPanoramaCamera.actualLocation,
      headingDegrees: incomingPanoramaCamera.headingDegrees };
  }, [incomingPanoramaCamera]);
  const acceptCamera = (next: CameraContextEvent | null) => {
    if (next?.headingDegrees != null && next.headingMeaning) {
      const heading = ((next.headingDegrees % 360) + 360) % 360;
      const previous = accumulatedHeading.current;
      const continuous = previous === null ? heading : previous + shortestHeadingDelta(previous, heading);
      accumulatedHeading.current = continuous;
      setDisplayHeading(continuous);
    } else {
      accumulatedHeading.current = null;
      setDisplayHeading(null);
    }
    setCamera(next);
  };
  useEffect(() => {
    if (!incomingCamera || !currentActiveTile.current || !cameraMatchesTile(incomingCamera, currentActiveTile.current)) return;
    const expectedRequest = currentInspection.current?.requestRevision ?? null;
    if ((incomingCamera.requestRevision ?? null) !== expectedRequest) return;
    const previous = cameraRevisions.current.get(incomingCamera.viewerId) ?? -1;
    if (incomingCamera.displayRevision < previous) return;
    cameraRevisions.current.set(incomingCamera.viewerId, incomingCamera.displayRevision);
    acceptCamera(incomingCamera.location ? incomingCamera : null);
  }, [incomingCamera]);
  useEffect(() => {
    const inspection = currentInspection.current;
    const active = currentActiveTile.current;
    if (!incomingPanoramaCamera || !inspection || !active?.tileId
      || incomingPanoramaCamera.requestId !== panoramaRequestForInspection(inspection).requestId
      || incomingPanoramaCamera.revision !== inspection.requestRevision) return;
    const previous = cameraRevisions.current.get(incomingPanoramaCamera.viewerId) ?? -1;
    if (incomingPanoramaCamera.cameraRevision <= previous) return;
    cameraRevisions.current.set(incomingPanoramaCamera.viewerId, incomingPanoramaCamera.cameraRevision);
    acceptCamera({
      schema: CAMERA_CONTEXT_SCHEMA, editorId: active.editorId,
      sourceFingerprint: active.sourceFingerprint, selectionEpoch: active.selectionEpoch,
      selectionRevision: active.selectionRevision, tileId: active.tileId,
      viewerId: incomingPanoramaCamera.viewerId, imageId: incomingPanoramaCamera.panoId,
      displayRevision: incomingPanoramaCamera.cameraRevision,
      requestRevision: inspection.requestRevision,
      location: incomingPanoramaCamera.actualLocation,
      headingDegrees: incomingPanoramaCamera.headingDegrees,
      headingMeaning: 'live-view-direction',
    });
  }, [incomingPanoramaCamera]);
  const issues = useMemo(() => network.features.length && viewBounds ? validateNetwork(network, viewBounds) : [], [network, viewBounds]);
  const topologyWarnings = useMemo(() => network.features.length && viewBounds ? validateSidewalkTopology(network, viewBounds) : [], [network, viewBounds]);
  const endpoints = useMemo(() => networkNodes(network), [network]);
  const drawingAnchor = drawing[drawing.length - 1];
  const drawingAnchorIsNetworkNode = drawingAnchor && endpoints.some(point => coordinateKey(point) === coordinateKey(drawingAnchor));

  useEffect(() => {
    if (!sourcesOpen) return;
    const outside = (target: EventTarget | null) => target instanceof Node
      && !sourcesButton.current?.contains(target) && !sourcesPanel.current?.contains(target);
    const onPointerDown = (event: PointerEvent) => {
      if (!outside(event.target)) return;
      setSourcesOpen(false);
      setCopyStatus('');
      suppressOutsideClick.current = true;
      event.preventDefault();
      event.stopPropagation();
    };
    const onClick = (event: MouseEvent) => {
      if (!suppressOutsideClick.current) return;
      suppressOutsideClick.current = false;
      event.preventDefault();
      event.stopPropagation();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      setSourcesOpen(false);
      setCopyStatus('');
      sourcesButton.current?.focus();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('click', onClick, true);
    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('click', onClick, true);
      document.removeEventListener('keydown', onKeyDown, true);
    };
  }, [sourcesOpen]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    const controller = new AbortController();
    const current = () => !controller.signal.aborted && generation === requestGeneration.current;
    setLoading(true); setError(''); setImageReady(false); setImageAspect(1); setLoadedRequest(null);
    setSelection(null); setNetwork(emptyFC); setSourceNetwork(emptyFC); setBounds(null); setTileCrs(null); setImageUrl('');
    setPast([]); setFuture([]); setFutureOperations([]); setOperations([]);
    if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
    pendingDraw.current = null; drawingRef.current = [];
    setDrawing([]); setDrawingCursor(null); setSelectedNode(null); setDrag(null);
    setMarqueeStart(null); setMarqueeEnd(null); dragMoved.current = false;
    Promise.resolve(selectionFeature?.type === 'Feature' && selectionFeature.geometry
      ? ({ type: 'FeatureCollection', features: [selectionFeature] } as FeatureCollection)
      : resolveSelection(input, controller.signal)).then(async fc => {
      if (!current()) return;
      if (!fc?.features?.length) { sendActiveTile(null); setLoading(false); return; }
      const directFeature = selectionFeature?.type === 'Feature' && selectionFeature.geometry ? selectionFeature : null;
      const idIndex = selectionFeatureId == null ? -1 : fc.features.findIndex(feature => {
        const properties = feature.properties as Record<string, unknown> | null;
        const id = properties?.tile_id ?? properties?.tileId ?? properties?.id;
        return id != null && String(id) === selectionFeatureId;
      });
      const index = directFeature ? 0 : selectionFeatureId != null ? idIndex
        : selectionIndex == null && allowSingleTile && fc.features.length === 1 ? 0 : selectionIndex;
      if (index == null) {
        sendActiveTile(null);
        if (configRef.current.activeSelection) persistConfig({ ...configRef.current, activeSelection: undefined });
        setLoading(false); return;
      }
      if (index < 0 || index >= fc.features.length) throw new Error('The selected tile is no longer present. Pick a tile again.');
      const selected: FeatureCollection = { type: 'FeatureCollection', features: [directFeature ?? fc.features[index]] };
      const nextBounds = featureBounds(selected.features[0]);
      if (!nextBounds) throw new Error('The selected tile has no polygon bounds.');
      const id = String(selected.features[0].properties?.tile_id ?? selected.features[0].properties?.tileId ?? '');
      if (!id) throw new Error('The selected feature must include a tile_id property.');
      const image = resolveSelectedResourceTemplate(String(selected.features[0].properties?.image_url ?? configRef.current.imageUrlTemplate), selected);
      const networkPath = resolveSelectedResourceTemplate(String(selected.features[0].properties?.network_url ?? configRef.current.networkUrlTemplate), selected);
      const imageAvailable = selected.features[0].properties?.image_available !== false;
      const declaredCrs = (fc as any).crs?.properties?.name ?? (fc as any).crs ?? (selected.features[0] as any).crs ?? null;
      sendActiveTile(selected.features[0], typeof declaredCrs === 'string' ? declaredCrs : null);
      setSelection(selected); setBounds(nextBounds); setTileCrs(typeof declaredCrs === 'string' ? declaredCrs : null);
      setImageUrl(imageAvailable ? fileUrl(image) : ''); setImageReady(!imageAvailable); setImageGeneration(generation);
      if (configRef.current.activeSelection?.tileId !== id || configRef.current.activeSelection?.sourceFingerprint !== fingerprint) {
        persistConfig({ ...configRef.current, activeSelection: { tileId: id, sourceFingerprint: fingerprint } });
      }
      const saved = savedTile(configRef.current, id);
      const loadedNetwork = saved?.originalNetwork ?? clipNetworkToBounds(originalNetwork ?? await loadNetwork(networkPath, controller.signal), nextBounds);
      if (!current()) return;
      setSourceNetwork(loadedNetwork); setNetwork(saved?.network ?? loadedNetwork);
      setPast(saved?.past ?? []); setFuture(saved?.future ?? []);
      setFutureOperations(saved?.futureOperations ?? (saved?.future ?? []).map(() => 'redo'));
      setOperations(saved?.operations ?? []); setLoadedRequest(request); setLoading(false);
      if (saved?.committedNetwork) {
        const provenance = saved.provenance ?? buildEditProvenance({ tileId: id, operations: saved.operations ?? [], before: loadedNetwork, after: saved.committedNetwork, editRevision: saved.revision ?? 1, validationWarnings: [] });
        const replay = saved.committedEdit ?? makeNetworkEditEnvelope({ tileId: id,
          editRevision: saved.revision ?? 1, operationTypes: saved.operations ?? [], tileFeature: selected.features[0],
          before: loadedNetwork, after: saved.committedNetwork, provenance });
        interactionsCallback?.({ [SIDEWALK_NETWORK_EDIT_CHANNEL]: replay }, nodeId);
      }
    }).catch(e => {
      if (!current()) return;
      sendActiveTile(null);
      setNetwork(emptyFC); setSourceNetwork(emptyFC); setLoadedRequest(null);
      setError(e instanceof Error ? e.message : String(e)); setLoading(false);
    });
    return () => { controller.abort(); if (pendingDraw.current) clearTimeout(pendingDraw.current.timer); pendingDraw.current = null; };
  // Saved code changes must not reload a tile or discard its current draft.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request]);

  const persistNetwork = useCallback((next: FeatureCollection, operation: string, before: FeatureCollection = network) => {
    if (!ready || !tileId || next === before) return;
    const nextPast = [...past.slice(-49), before];
    const nextOps = [...operations, operation];
    const saved = { ...savedTile(configRef.current, tileId), network: next, past: nextPast, future: [], futureOperations: [], operations: nextOps };
    const nextConfig = { ...configRef.current, byTile: { ...configRef.current.byTile, [tileStorageKey(configRef.current, tileId)]: saved } };
    setNetwork(next); setPast(nextPast); setFuture([]); setFutureOperations([]); setOperations(nextOps); persistConfig(nextConfig);
  }, [ready, tileId, network, past, future, operations, config, persist]);
  const currentDrawing = useRef({ network, persistNetwork });
  currentDrawing.current = { network, persistNetwork };

  const undo = () => {
    if (!ready || !past.length || !tileId) return;
    const previous = past[past.length - 1]; const nextPast = past.slice(0, -1);
    const nextFuture = [network, ...future];
    const nextFutureOperations = [operations.at(-1) ?? 'edit', ...futureOperations];
    const nextOps = operations.slice(0, -1);
    setNetwork(previous); setPast(nextPast); setFuture(nextFuture); setFutureOperations(nextFutureOperations); setOperations(nextOps);
    persistConfig({ ...configRef.current, byTile: { ...configRef.current.byTile, [tileStorageKey(configRef.current, tileId)]: { ...savedTile(configRef.current, tileId), network: previous, past: nextPast, future: nextFuture, futureOperations: nextFutureOperations, operations: nextOps } } });
  };
  const redo = () => {
    if (!ready || !future.length || !tileId) return;
    const next = future[0]; const nextFuture = future.slice(1); const nextFutureOperations = futureOperations.slice(1); const nextPast = [...past.slice(-49), network];
    const nextOps = [...operations, futureOperations[0] ?? 'redo'];
    setNetwork(next); setPast(nextPast); setFuture(nextFuture); setFutureOperations(nextFutureOperations); setOperations(nextOps);
    persistConfig({ ...configRef.current, byTile: { ...configRef.current.byTile, [tileStorageKey(configRef.current, tileId)]: { ...savedTile(configRef.current, tileId), network: next, past: nextPast, future: nextFuture, futureOperations: nextFutureOperations, operations: nextOps } } });
  };

  const svgPoint = (event: React.PointerEvent<SVGSVGElement> | React.MouseEvent<SVGSVGElement>): [number, number] => {
    return clientToViewPoint(event.currentTarget.getBoundingClientRect(), event.clientX, event.clientY);
  };
  const snapEndpoint = (point: Position, exclude?: Position): Position => {
    if (!viewBounds) return point;
    const rect = imageSvg.current?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return point;
    // Stewards snaps through rendered node hits. The SVG equivalent is a
    // stable eight CSS-pixel hit radius at the current editor zoom.
    let best: Position | null = null; let distance = 8;
    for (const endpoint of endpoints) {
      if (exclude && coordinateKey(endpoint) === coordinateKey(exclude)) continue;
      const a = pointToView(endpoint, viewBounds);
      const b = pointToView(point, viewBounds);
      const nextDistance = Math.hypot((a[0] - b[0]) * rect.width / VIEW, (a[1] - b[1]) * rect.height / VIEW);
      if (nextDistance <= distance) { best = endpoint; distance = nextDistance; }
    }
    return best ?? point;
  };
  const pointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!viewBounds) return;
    // Read the native event before scheduling React state updates. React clears
    // `currentTarget` after dispatch; reading it inside a functional updater can
    // therefore throw `getBoundingClientRect` on null.
    const point = svgPoint(event);
    if (mode === 'delete-area') { setMarqueeStart(point); setMarqueeEnd(point); event.currentTarget.setPointerCapture(event.pointerId); }
  };
  const pointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (marqueeStart) setMarqueeEnd(svgPoint(event));
    if (mode === 'draw' && drawing.length && viewBounds) {
      const [x, y] = svgPoint(event);
      setDrawingCursor(snapEndpoint(viewToPoint(x, y, viewBounds)));
    }
    if (drag && viewBounds) {
      const [x, y] = svgPoint(event); const target = snapEndpoint(viewToPoint(x, y, viewBounds), drag.from);
      if (Math.hypot(target[0] - drag.from[0], target[1] - drag.from[1]) > 1e-10) dragMoved.current = true;
      setSelectedNode(target);
      setNetwork(moveNetworkNode(drag.original, drag.from, target));
    }
  };
  const pointerUp = () => {
    if (marqueeStart && marqueeEnd && viewBounds) {
      const rect = imageSvg.current?.getBoundingClientRect();
      const dx = Math.abs(marqueeStart[0] - marqueeEnd[0]) * (rect?.width ?? VIEW) / VIEW;
      const dy = Math.abs(marqueeStart[1] - marqueeEnd[1]) * (rect?.height ?? VIEW) / VIEW;
      if (Math.hypot(dx, dy) >= 3) {
        const a = viewToPoint(...marqueeStart, viewBounds); const b = viewToPoint(...marqueeEnd, viewBounds);
        persistNetwork(deleteNetworkNodesInBounds(network, [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])]), 'delete_nodes_in_area');
      }
    }
    if (drag && !marqueeStart && dragMoved.current) persistNetwork(network, 'move_node', drag.original);
    dragMoved.current = false;
    setMarqueeStart(null); setMarqueeEnd(null); setDrag(null);
  };
  const pointerCancel = () => {
    if (drag) setNetwork(drag.original);
    dragMoved.current = false;
    setDrag(null); setMarqueeStart(null); setMarqueeEnd(null); setSelectedNode(null);
  };
  const onNodePointerDown = (event: React.PointerEvent<SVGEllipseElement>, p: Position) => {
    event.stopPropagation();
    if (mode === 'select' || mode === 'move') {
      setSelectedNode(p);
      const edgeTolerance = viewBounds ? Math.min(viewBounds[2] - viewBounds[0], viewBounds[3] - viewBounds[1]) * 1e-7 : 0;
      const boundary = viewBounds && (Math.abs(p[0] - viewBounds[0]) <= edgeTolerance || Math.abs(p[0] - viewBounds[2]) <= edgeTolerance
        || Math.abs(p[1] - viewBounds[1]) <= edgeTolerance || Math.abs(p[1] - viewBounds[3]) <= edgeTolerance);
      if (boundary) { setMovementNotice('Tile-boundary nodes cannot be moved until cross-tile editing is supported.'); return; }
      setMovementNotice(''); dragMoved.current = false;
      setDrag({ from: p, pointer: event.pointerId, original: network }); event.currentTarget.setPointerCapture(event.pointerId);
    }
    if (mode === 'delete-area') return;
  };
  const deleteSelectedNode = () => { if (selectedNode) { persistNetwork(deleteNetworkNode(network, selectedNode), 'delete_node_and_incident_edges'); setSelectedNode(null); } };
  const onDrawClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (mode === 'inspect' && ready && viewBounds && currentActiveTile.current?.tileId) {
      event.preventDefault(); event.stopPropagation();
      try {
        const location = pointToWgs84(viewToPoint(...svgPoint(event), viewBounds), tileCrs);
        const active = currentActiveTile.current;
        const next: InspectionRequest = {
          schema: INSPECTION_REQUEST_SCHEMA, editorId: active.editorId,
          sourceFingerprint: active.sourceFingerprint, selectionEpoch: active.selectionEpoch,
          selectionRevision: active.selectionRevision, requestRevision: ++inspectionRevision.current,
          tileId: active.tileId, location, crs: 'EPSG:4326',
        };
        currentInspection.current = next;
        setRequestedPoint(location);
        setInspectionStatus(null);
        setCamera(null);
        accumulatedHeading.current = null;
        setDisplayHeading(null);
        cameraRevisions.current.clear();
        // Carry the current tile with each inspection. Interaction delivery is
        // event based, so a viewer attached after restoration may have missed
        // the earlier active-tile announcement.
        callbackRef.current?.({ [ACTIVE_TILE_CHANNEL]: active, [INSPECTION_REQUEST_CHANNEL]: next,
          [PANORAMA_REQUEST_CHANNEL]: panoramaRequestForInspection(next) }, nodeId);
      } catch (error) {
        setStatus({ code: 'error', content: error instanceof Error ? error.message : String(error) });
      }
      return;
    }
    if (mode !== 'draw' || !viewBounds) return;
    const screen = svgPoint(event);
    const click = { point: snapEndpoint(viewToPoint(...screen, viewBounds)), screen };
    const commit = (clicks: Array<{ point: Position; screen: [number, number] }>) => {
      for (const { point } of clicks) {
        const previous = drawingRef.current.at(-1);
        if (previous && coordinateKey(previous) === coordinateKey(point)) continue;
        if (previous) {
          const before = currentDrawing.current.network;
          const next = connectNetworkNodes(before, previous, point);
          if (next !== before) {
            currentDrawing.current.network = next;
            currentDrawing.current.persistNetwork(next, 'draw_edge', before);
          }
        }
        drawingRef.current = [...drawingRef.current, point];
        setDrawing(drawingRef.current);
        setDrawingCursor(null);
      }
    };
    const arm = (clicks: Array<{ point: Position; screen: [number, number] }>) => {
      const timer = setTimeout(() => { pendingDraw.current = null; commit(clicks); }, 220);
      pendingDraw.current = { clicks, timer };
    };
    const pending = pendingDraw.current;
    if (pending) {
      clearTimeout(pending.timer);
      const last = pending.clicks.at(-1)!;
      if (Math.hypot(last.screen[0] - screen[0], last.screen[1] - screen[1]) < 8) {
        arm([...pending.clicks, click]);
        return;
      }
      pendingDraw.current = null;
      commit(pending.clicks);
    }
    arm([click]);
  };
  const endDrawChain = (event: React.MouseEvent<SVGSVGElement>) => {
    if (mode !== 'draw') return;
    event.preventDefault();
    if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
    pendingDraw.current = null;
    drawingRef.current = [];
    setDrawing([]);
    setDrawingCursor(null);
  };
  const splitAt = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!viewBounds || mode !== 'select' || event.button !== 2) return;
    event.preventDefault(); const rect = event.currentTarget.getBoundingClientRect();
    const p = viewToPoint((event.clientX - rect.left) / rect.width * VIEW, (event.clientY - rect.top) / rect.height * VIEW, viewBounds);
    const nearest = closestLineSegment(network, p);
    const tolerance = Math.max(viewBounds[2] - viewBounds[0], viewBounds[3] - viewBounds[1]) * 0.02;
    if (nearest && nearest.distance <= tolerance) persistNetwork(splitNetworkEdge(network, nearest.featureIndex, nearest.segmentIndex, nearest.point), 'split_edge');
  };
  const saveNetwork = () => {
    if (!ready || !viewBounds || !tileId) return;
    if (issues.length) { setStatus({ code: 'error', content: issues.join(' ') }); return; }
    if (!tileFeature) return;
    const correctedNetwork = clipNetworkToBounds(network, viewBounds);
    const revision = (savedTile(configRef.current, tileId)?.revision ?? 0) + 1;
    const provenance = buildEditProvenance({ tileId, operations, before: sourceNetwork, after: correctedNetwork, editRevision: revision, validationWarnings: topologyWarnings.map(warning => warning.message) });
    const commit = makeNetworkEditEnvelope({ tileId, editRevision: revision, operationTypes: [...operations], tileFeature, before: sourceNetwork, after: correctedNetwork, provenance });
    const saved = {
      ...savedTile(configRef.current, tileId), network,
      originalNetwork: sourceNetwork,
      past, future, futureOperations, operations,
      revision,
      committedNetwork: correctedNetwork,
      provenance, committedEdit: commit,
    };
    const nextConfig = { ...configRef.current, byTile: { ...configRef.current.byTile, [tileStorageKey(configRef.current, tileId)]: saved } };
    persistConfig(nextConfig);
    if (configRef.current.mode !== 'input-overview') interactionsCallback?.({ [SIDEWALK_NETWORK_EDIT_CHANNEL]: commit }, nodeId);
    const output = { ...correctedNetwork, metadata: { sidewalkTileId: tileId, editRevision: revision, schema: SIDEWALK_EDIT_SCHEMA, operationCount: operations.length, topologyWarnings: topologyWarnings.map(warning => warning.code), provenance } };
    const latestOutput = { data: output, dataType: 'geodataframe' };
    if (onCommitted) onCommitted(nextConfig, latestOutput);
    else emit(latestOutput);
    setStatus({ code: 'success', content: `Applied network revision ${revision} for tile ${tileId} and sent it downstream.${topologyWarnings.length ? ` Review ${topologyWarnings.length} topology warning(s).` : ''}` });
  };
  const selectedResource = (value: unknown, fallback: string) => tileFeature
    ? resolveSelectedResourceTemplate(String(value ?? fallback), selection!) : fallback;
  const imageSource = selectedResource(tileFeature?.properties?.image_url, config.imageUrlTemplate);
  const networkSource = originalNetwork
    ? (config.overview?.networkUrl || 'Connected upstream network')
    : selectedResource(tileFeature?.properties?.network_url, config.networkUrlTemplate);
  const copySource = (label: string, value: string) => {
    if (!navigator.clipboard?.writeText) return;
    void navigator.clipboard.writeText(value).then(() => setCopyStatus(`${label} copied`))
      .catch(() => setCopyStatus('Copy unavailable in this browser'));
  };
  const activateMode = (next: 'select' | 'draw' | 'move' | 'delete-area' | 'inspect') => {
    setMode(current => current === next ? 'select' : next);
    if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
    pendingDraw.current = null; drawingRef.current = [];
    setDrawing([]); setDrawingCursor(null); setSelectedNode(null); setDrag(null);
    setMarqueeStart(null); setMarqueeEnd(null); dragMoved.current = false;
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!ready) return;
      const target = event.target;
      if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (event.key === 'Escape') {
        if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
        pendingDraw.current = null; drawingRef.current = [];
        if (drag) setNetwork(drag.original);
        setMode('select'); setDrawing([]); setDrawingCursor(null); setMarqueeStart(null); setMarqueeEnd(null); setDrag(null); setSelectedNode(null); dragMoved.current = false;
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedNode && mode === 'select') {
        event.preventDefault(); deleteSelectedNode(); return;
      }
      const key = event.key.toLowerCase();
      if (key === 'l') { activateMode('draw'); return; }
      if (key === 'm') { activateMode('move'); return; }
      if (key === 'd') { activateMode('delete-area'); return; }
      if (key === 'i') { activateMode('inspect'); return; }
      if (!(event.metaKey || event.ctrlKey)) return;
      if (key === 'z') { event.preventDefault(); if (event.shiftKey) redo(); else undo(); }
      else if (key === 'y') { event.preventDefault(); redo(); }
  };

  const cameraPoint = camera?.location && viewBounds && currentActiveTile.current?.geometry
    ? pointToView(pointFromWgs84(camera.location, tileCrs), viewBounds) : null;
  const cameraInside = !!cameraPoint && !!currentActiveTile.current?.geometry
    && pointInPolygon(camera!.location!, currentActiveTile.current.geometry);
  const outside = camera?.location && currentActiveTile.current?.geometry && !cameraInside
    ? cameraBoundary(camera.location, currentActiveTile.current.geometry) : null;
  const cuePoint = outside && viewBounds && camera?.location ? (() => {
    const nearest = pointToView(pointFromWgs84(outside.nearest, tileCrs), viewBounds);
    const raw = cameraPoint ?? nearest;
    const dx = raw[0] - nearest[0], dy = raw[1] - nearest[1];
    const scale = 18 / (Math.hypot(dx, dy) || 1);
    return [nearest[0] + dx * scale, nearest[1] + dy * scale] as [number, number];
  })() : null;
  const markerPoint = cameraInside ? cameraPoint : null;
  const pendingPoint = requestedPoint && !camera && viewBounds && currentActiveTile.current?.geometry
    && pointInPolygon(requestedPoint, currentActiveTile.current.geometry)
    ? pointToView(pointFromWgs84(requestedPoint, tileCrs), viewBounds) : null;
  const pendingMarkerPoint = pendingPoint ? [
    Math.max(STEWARDS_CAMERA_SIZE / 2, Math.min(VIEW - STEWARDS_CAMERA_SIZE / 2, pendingPoint[0])),
    Math.max(STEWARDS_CAMERA_SIZE * markerAspect / 2,
      Math.min(VIEW - STEWARDS_CAMERA_SIZE * markerAspect / 2, pendingPoint[1])),
  ] as [number, number] : null;
  const outsideTagPoint = cuePoint ? [
    Math.max(CAMERA_CUE_MARGIN, Math.min(VIEW - CAMERA_CUE_MARGIN, cuePoint[0])),
    Math.max(CAMERA_CUE_MARGIN * markerAspect, Math.min(VIEW - CAMERA_CUE_MARGIN * markerAspect, cuePoint[1])),
  ] as [number, number] : null;
  const outsideTagX = outsideTagPoint ? Math.max(8, Math.min(VIEW - OUTSIDE_CAMERA_TAG_WIDTH - 8,
    outsideTagPoint[0] + (outsideTagPoint[0] > VIEW / 2 ? -OUTSIDE_CAMERA_TAG_WIDTH - 26 : 26))) - outsideTagPoint[0] : 0;
  const outsideTagY = outsideTagPoint ? Math.max(8, Math.min(VIEW - OUTSIDE_CAMERA_TAG_HEIGHT * markerAspect - 8,
    outsideTagPoint[1] + (outsideTagPoint[1] > VIEW / 2 ? -OUTSIDE_CAMERA_TAG_HEIGHT - 18 : 18) * markerAspect)) - outsideTagPoint[1] : 0;
  const cameraTileId = camera?.location && neighborIndex ? tileAtPoint(neighborIndex, camera.location) : null;
  const openCameraTile = () => {
    if (!ready || !camera?.location || !cameraTileId || cameraTileId === tileId || !onNavigate) return;
    const inspection = currentInspection.current;
    if (!inspection) return;
    pendingCameraAdoption.current = { tileId: cameraTileId, camera,
      requestId: panoramaRequestForInspection(inspection).requestId,
      revision: inspection.requestRevision, cameraRevision: camera.displayRevision };
    setNavigationTarget(cameraTileId);
    onNavigate(cameraTileId);
  };
  const navigate = (direction: TileDirection) => {
    const destination = neighborIndex?.neighbors.get(tileId)?.[direction];
    if (!ready || navigationTarget || !destination || !onNavigate) return;
    setNavigationTarget(destination);
    onNavigate(destination);
  };
  const disabledButtonStyle: React.CSSProperties = {
    background: 'var(--curio-surface-muted)', border: '1px solid var(--curio-border)',
    color: 'var(--curio-text-secondary)', cursor: 'default',
  };
  const toolbarButtonStyle: React.CSSProperties = { ...ui.button, borderRadius: 'var(--curio-radius-sm)' };
  const toolbarSelectedStyle: React.CSSProperties = { ...toolbarButtonStyle,
    background: 'var(--curio-accent-sky-bg)', border: '1px solid var(--curio-accent-sky-fg)',
    color: 'var(--curio-accent-sky-fg)' };
  const deleteButtonStyle: React.CSSProperties = mode === 'delete-area'
    ? { ...toolbarSelectedStyle, background: 'var(--curio-danger-text)', borderColor: 'var(--curio-danger-text)', color: '#fff' }
    : { ...toolbarButtonStyle, background: 'var(--curio-danger-bg)', borderColor: 'var(--curio-danger-border)', color: 'var(--curio-danger-text)' };

  return (
    <div className="nodrag nopan nowheel" data-curio-sidewalk-editor={nodeId}
      role="region" aria-label={`Sidewalk editor ${nodeId}`} tabIndex={0} onKeyDown={onKeyDown}
      onPointerDownCapture={event => {
        if (event.target instanceof Element && !event.target.closest('button, input, textarea, select, [contenteditable="true"], [data-sidewalk-sources-overlay]')) event.currentTarget.focus();
      }}
      onBlurCapture={event => {
        if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) {
          if (drag) setNetwork(drag.original);
          if (pendingDraw.current) clearTimeout(pendingDraw.current.timer);
          pendingDraw.current = null; drawingRef.current = [];
          setDrawing([]); setDrawingCursor(null); setSelectedNode(null); setDrag(null);
          setMarqueeStart(null); setMarqueeEnd(null); dragMoved.current = false;
        }
      }} style={{ ...ui.body, overflowY: 'auto' }}>
      <div style={{ ...ui.row, justifyContent: 'space-between', gap: 6 }}>
        <span style={{ minWidth: 0, flex: '1 1 220px' }}><span aria-hidden="true" style={{ display: 'inline-block', width: 9, height: 9,
          borderRadius: '50%', marginRight: 8, background: error ? 'var(--curio-danger-text)' : loading ? 'var(--curio-warning-text)' : ready ? 'var(--curio-success-text)' : 'var(--curio-text-muted)' }} />
          <strong>{tileId ? `Tile ${tileId}` : 'Waiting for tile selection'}</strong>
          {' · '}{loading ? 'Loading resources' : error ? 'Resource loading failed' : ready ? imageUrl
            ? network.features.length ? 'Imagery and network loaded' : 'Imagery and empty network loaded'
            : 'Network loaded · imagery unavailable' : 'Waiting for resources'}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flex: '0 1 auto', flexWrap: 'wrap' }}>
          <span role="status" style={ui.status}>{operations.length ? `${operations.length} draft changes` : 'No draft changes'}</span>
          <button type="button" onClick={saveNetwork} disabled={!ready || issues.length > 0}
            style={{ ...ui.primaryButton, borderRadius: 'var(--curio-radius-sm)', ...(!ready || issues.length > 0 ? disabledButtonStyle : {}) }}>Save network</button>
        </div>
      </div>
      <style>{`[data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar { container-type: inline-size; }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar-inner { display: flex; align-items: center; gap: 4px; }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar button { display: inline-flex; align-items: center; justify-content: center; gap: 4px; height: 32px; min-height: 32px; box-sizing: border-box; white-space: nowrap; border-radius: var(--curio-radius-sm); flex: none; }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar button svg { width: 16px; height: 16px; flex: none; }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar button:focus-visible { outline: 2px solid var(--curio-top-bar-bg); outline-offset: 2px; }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar button:not(:disabled):hover { filter: brightness(0.94); }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar .sidewalk-mode-command { flex: 1 1 0; min-width: 0; }
        [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar .sidewalk-icon-command { width: 32px; padding: 0; }
        @container (max-width: 500px) { [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar-inner { display: grid; grid-template-columns: max-content max-content max-content; justify-content: start; row-gap: 4px; }
          [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar .sidewalk-edit-command-group { grid-column: 2 / 4; justify-self: end; } }
        @container (max-width: 350px) { [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar-inner { grid-template-columns: max-content max-content; }
          [data-curio-sidewalk-editor="${nodeId}"] .sidewalk-edit-toolbar .sidewalk-edit-command-group { grid-column: auto; justify-self: start; } }`}</style>
      <div role="toolbar" aria-label="Sidewalk network editing tools" className="sidewalk-edit-toolbar" style={{ ...ui.panel, padding: 4 }} onPointerDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
        <div className="sidewalk-edit-toolbar-inner">
          <button type="button" className="sidewalk-mode-command" aria-label={mode === 'inspect' ? 'Exit Street View inspection' : 'Inspect Street View'} title="Inspect Street View at a point (I)" aria-pressed={mode === 'inspect'} disabled={!ready} onClick={() => activateMode('inspect')} style={{ ...toolbarButtonStyle, ...(mode === 'inspect' ? toolbarSelectedStyle : {}) }}><EditToolIcon name="inspect" /> Inspect Street View</button>
          <button type="button" className="sidewalk-mode-command" aria-label={mode === 'draw' ? 'Cancel edge drawing' : 'Draw edges'} title="Draw edges (L)" aria-pressed={mode === 'draw'} disabled={!ready} onClick={() => activateMode('draw')} style={{ ...toolbarButtonStyle, ...(mode === 'draw' ? toolbarSelectedStyle : {}) }}><EditToolIcon name="draw" /> Draw edges</button>
          <button type="button" className="sidewalk-mode-command" aria-label="Move nodes" title="Drag a node to reposition it (M)" aria-pressed={mode === 'move'} disabled={!ready} onClick={() => activateMode('move')} style={{ ...toolbarButtonStyle, ...(mode === 'move' ? toolbarSelectedStyle : {}) }}><EditToolIcon name="move" /> Move nodes</button>
          <div role="group" aria-label="Delete and history" className="sidewalk-edit-command-group" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <button type="button" className="sidewalk-icon-command" aria-label="Delete" title="Delete nodes in an area (D)" aria-pressed={mode === 'delete-area'} disabled={!ready} onClick={() => activateMode('delete-area')} style={deleteButtonStyle}><EditToolIcon name="delete" /></button>
            <button type="button" className="sidewalk-icon-command" aria-label="Undo" title="Undo (Ctrl/Cmd+Z)" disabled={!ready || !past.length} onClick={undo} style={{ ...toolbarButtonStyle, ...(!ready || !past.length ? disabledButtonStyle : {}) }}><EditToolIcon name="undo" /></button>
            <button type="button" className="sidewalk-icon-command" aria-label="Redo" title="Redo (Ctrl/Cmd+Y or Shift+Z)" disabled={!ready || !future.length} onClick={redo} style={{ ...toolbarButtonStyle, ...(!ready || !future.length ? disabledButtonStyle : {}) }}><EditToolIcon name="redo" /></button>
          </div>
        </div>
      </div>
      <div style={ui.helper}>{mode === 'inspect' ? 'Click a location to open Street View.' : mode === 'draw' ? 'Click nodes or the image to draw connected edges; double-click to finish.' : mode === 'move' ? 'Drag a node to reposition it.' : mode === 'delete-area' ? 'Drag a rectangle to delete nodes and incident edges.' : 'Choose a tool to edit the network, or select a node.'}</div>
      <div style={{ flex: 'none', boxSizing: 'border-box', width: '100%', minHeight: 240, aspectRatio: imageAspect, position: 'relative', margin: '4px 0 2px', overflow: 'visible', background: 'var(--curio-surface-muted)', border: '1px solid var(--curio-border)', borderRadius: 'var(--curio-radius-md)' }}>
        {imageUrl && <img key={imageGeneration} src={imageUrl}
          onLoad={event => { if (imageGeneration === requestGeneration.current) {
            const { naturalWidth, naturalHeight } = event.currentTarget;
            if (naturalWidth > 0 && naturalHeight > 0) setImageAspect(naturalWidth / naturalHeight);
            setImageReady(true);
          } }}
          onError={() => { if (imageGeneration === requestGeneration.current) { setImageReady(false); setError('Tile image could not be loaded. Select another tile or check the image path.'); } }} alt={`Satellite image for tile ${tileId}`} draggable={false} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill', pointerEvents: 'none', borderRadius: 'var(--curio-radius-md)' }} />}
        <button ref={sourcesButton} type="button" aria-label="Data sources" title="Data sources"
          aria-expanded={sourcesOpen} aria-controls={`sidewalk-sources-${nodeId}`}
          onPointerDown={event => event.stopPropagation()}
          onClick={event => { event.stopPropagation(); setCopyStatus(''); setSourcesOpen(value => !value); }}
          style={{ position: 'absolute', zIndex: 8, top: 8, right: 8, width: 40, height: 40,
            padding: 0, border: 'none', background: 'transparent',
            color: '#000000', fontSize: 25, cursor: 'pointer',
            display: 'grid', placeItems: 'center' }}><CurioUtilityIcon name="circle-info" /></button>
        {sourcesOpen && <div ref={sourcesPanel} id={`sidewalk-sources-${nodeId}`}
          data-sidewalk-sources-overlay="true" role="dialog" aria-label="Data sources"
          onPointerDown={event => event.stopPropagation()} onPointerMove={event => event.stopPropagation()}
          onPointerUp={event => event.stopPropagation()} onClick={event => event.stopPropagation()}
          onDoubleClick={event => event.stopPropagation()} onContextMenu={event => event.stopPropagation()}
          onKeyDown={event => event.stopPropagation()}
          style={{ ...ui.panel, position: 'absolute', zIndex: 7, top: 48, right: 8,
            boxSizing: 'border-box', width: 'min(330px, calc(100% - 16px))',
            maxHeight: 'min(310px, calc(100% - 56px))', overflowY: 'auto',
            padding: '6px 10px 10px',
            background: 'var(--curio-card-bg)', boxShadow: '0 4px 16px rgba(15,23,42,0.2)' }}>
          <div style={{ ...ui.row, justifyContent: 'space-between' }}>
            <strong>Data sources</strong>
            <button type="button" aria-label="Close data sources" title="Close data sources"
              onClick={() => { setSourcesOpen(false); setCopyStatus(''); sourcesButton.current?.focus(); }}
              style={{ border: 'none', background: 'none', color: 'var(--curio-text-primary)',
                padding: 0, width: 28, height: 28, fontSize: 12, lineHeight: 1,
                display: 'grid', placeItems: 'center', cursor: 'pointer' }}><CurioUtilityIcon name="close" /></button>
          </div>
          {([['Image', imageSource], ['Network', networkSource]] as const).map(([label, value]) =>
            <div key={label} style={{ marginTop: 7 }}>
              <strong>{label}</strong>
              <div style={{ ...ui.panel, position: 'relative', marginTop: 3, paddingRight: 38,
                overflowWrap: 'anywhere', userSelect: 'text', fontSize: 'var(--curio-font-size-xs)',
                color: 'var(--curio-text-muted)', minHeight: 26 }}>
                {value || 'Unavailable'}
                <button type="button" aria-label={`Copy ${label.toLowerCase()} source`}
                  title={`Copy ${label.toLowerCase()} source`}
                  disabled={!value || !navigator.clipboard?.writeText} onClick={() => copySource(label, value)}
                  style={{ position: 'absolute', top: 3, right: 3, width: 26, height: 26,
                    padding: 0, display: 'grid', placeItems: 'center', cursor: 'pointer',
                    border: '1px solid var(--curio-border)', borderRadius: 'var(--curio-radius-sm)',
                    background: 'var(--curio-card-bg)', color: 'var(--curio-text-secondary)',
                    fontSize: 'var(--curio-font-size-sm)', lineHeight: 1,
                    ...(!value || !navigator.clipboard?.writeText ? { cursor: 'default', opacity: 0.5 } : {}) }}>
                  <CurioUtilityIcon name="copy" />
                </button>
              </div>
            </div>)}
          {copyStatus && <div role="status" style={ui.status}>{copyStatus}</div>}
        </div>}
        {TILE_DIRECTIONS.map(direction => {
          const destination = neighborIndex?.neighbors.get(tileId)?.[direction];
          const disabled = !destination || !ready || !!navigationTarget || !onNavigate;
          const placement: React.CSSProperties = direction === 'north' ? { top: 8, left: '50%', transform: 'translateX(-50%)' }
            : direction === 'south' ? { bottom: 8, left: '50%', transform: 'translateX(-50%)' }
              : direction === 'east' ? { right: 8, top: '50%', transform: 'translateY(-50%)' }
                : { left: 8, top: '50%', transform: 'translateY(-50%)' };
          return <button key={direction} type="button" aria-label={`Navigate ${direction}`} disabled={disabled}
            title={destination ? `Go ${direction} to tile ${destination}` : `No adjacent tile to the ${direction}`}
            onPointerDown={event => event.stopPropagation()} onClick={event => { event.stopPropagation(); navigate(direction); }}
            style={{ ...placement, position: 'absolute', zIndex: 5, width: 32, height: 32, padding: 0,
              border: '1px solid var(--curio-border-strong)', borderRadius: 'var(--curio-radius-md)',
              background: 'var(--curio-card-bg)', color: 'var(--curio-text-primary)',
              display: 'grid', placeItems: 'center', cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.36 : 0.82,
              boxShadow: '0 1px 5px rgba(15,23,42,0.18)' }}>
            <TileNavigationChevron direction={direction} />
          </button>;
        })}
        {(loading || (!!tileId && !imageReady && !error)) && <div role="status" style={{ ...ui.panel, position: 'absolute', zIndex: 2, margin: 8 }}>Loading tile…</div>}
        {error && <div role="alert" style={{ ...ui.error, position: 'absolute', zIndex: 2, margin: 8 }}>{error}</div>}
        {ready && !imageUrl && <div role="status" style={{ ...ui.status, position: 'absolute', zIndex: 2, right: 8, bottom: 8 }}>
          Imagery unavailable for this tile. Network editing remains available.
        </div>}
        {!tileFeature && !loading && <div style={{ ...ui.status, padding: 12 }}>Connect an upstream Autark tile selection to review it.</div>}
        {ready && viewBounds && <svg ref={imageSvg} aria-label="Sidewalk tile image and network" viewBox={`0 0 ${VIEW} ${VIEW}`} preserveAspectRatio="none" overflow="hidden" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', overflow: 'hidden', borderRadius: 'var(--curio-radius-md)', touchAction: 'none', cursor: mode === 'draw' || mode === 'delete-area' || mode === 'inspect' ? 'crosshair' : 'default' }} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerCancel} onClick={onDrawClick} onDoubleClick={endDrawChain} onContextMenu={splitAt}>
          {network.features.map((feature, i) => <path key={`${feature.id ?? i}`} d={linePath(feature, viewBounds)} fill="none" stroke={NETWORK_STROKE} strokeWidth={NETWORK_STROKE_WIDTH} vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />)}
          {endpoints.map((p, i) => { const [cx, cy] = pointToView(p, viewBounds); const selected = selectedNode && coordinateKey(selectedNode) === coordinateKey(p); return <ellipse key={i} data-testid="sidewalk-network-node" cx={cx} cy={cy} rx={NETWORK_NODE_RADIUS} ry={NETWORK_NODE_RADIUS * markerAspect} fill={selected ? '#ff0000' : NETWORK_STROKE} stroke="#fff" strokeWidth={2} onPointerDown={e => onNodePointerDown(e, p)} />; })}
          {drawingAnchor && !drawingAnchorIsNetworkNode && <ellipse cx={pointToView(drawingAnchor, viewBounds)[0]} cy={pointToView(drawingAnchor, viewBounds)[1]} rx={NETWORK_NODE_RADIUS} ry={NETWORK_NODE_RADIUS * markerAspect} fill={NETWORK_STROKE} stroke="#fff" strokeWidth={2} />}
          {drawingAnchor && drawingCursor && <line x1={pointToView(drawingAnchor, viewBounds)[0]} y1={pointToView(drawingAnchor, viewBounds)[1]} x2={pointToView(drawingCursor, viewBounds)[0]} y2={pointToView(drawingCursor, viewBounds)[1]} stroke={NETWORK_STROKE} strokeWidth={2} strokeDasharray="3 3" opacity={0.85} vectorEffect="non-scaling-stroke" />}
          {pendingMarkerPoint && <g data-testid="street-view-pending-marker" role="img"
            aria-label="Requested location — Street View not loaded" pointerEvents="none"
            transform={`translate(${pendingMarkerPoint[0]} ${pendingMarkerPoint[1]})`}>
            <title>Requested location — Street View not loaded</title>
            <svg x={-STEWARDS_CAMERA_SIZE / 2} y={-STEWARDS_CAMERA_SIZE * markerAspect / 2}
              width={STEWARDS_CAMERA_SIZE} height={STEWARDS_CAMERA_SIZE * markerAspect}
              viewBox="0 0 36 36" preserveAspectRatio="none" overflow="hidden">
              <path d="M 4.48 14.38 A 14 14 0 0 1 31.52 14.38"
                fill="none" stroke="var(--curio-text-secondary)" strokeWidth="7" strokeLinecap="round" opacity="0.82" />
              <circle cx="18" cy="18" r="6" fill="var(--curio-text-secondary)" />
              <circle cx="18" cy="18" r="3.5" fill="var(--curio-text-muted)" opacity="0.5" />
            </svg>
          </g>}
          {markerPoint && <g data-testid="street-view-camera-marker"
            aria-label="Street View camera at its actual tile location"
            pointerEvents="none" transform={`translate(${markerPoint[0]} ${markerPoint[1]})`}>
            <svg x={-STEWARDS_CAMERA_SIZE / 2} y={-STEWARDS_CAMERA_SIZE * markerAspect / 2}
              width={STEWARDS_CAMERA_SIZE} height={STEWARDS_CAMERA_SIZE * markerAspect} viewBox="0 0 36 36" preserveAspectRatio="none"
              data-testid="stewards-camera-symbol" overflow="visible"
              style={{ filter: 'drop-shadow(0 2px 6px rgba(0,0,0,0.3))' }}>
              <g data-testid="stewards-camera-heading"
                style={{ transform: `rotate(${displayHeading ?? 0}deg)`, transformBox: 'view-box',
                  transformOrigin: '50% 50%', transition: 'transform 0.1s ease' }}>
                <path d="M 4.48 14.38 A 14 14 0 0 1 31.52 14.38"
                  fill="none" stroke="#ef4444" strokeWidth="7" strokeLinecap="round" opacity="0.82" />
                <circle cx="18" cy="18" r="6" fill="#ef4444" />
                <circle cx="18" cy="18" r="3.5" fill="#dc2626" opacity="0.5" />
              </g>
            </svg>
          </g>}
          {outside && outsideTagPoint && <g data-testid="street-view-outside-cue" pointerEvents="none"
            transform={`translate(${outsideTagPoint[0]} ${outsideTagPoint[1]})`}>
            <svg data-testid="street-view-outside-tag" role="status"
              x={outsideTagX} y={outsideTagY}
              width={OUTSIDE_CAMERA_TAG_WIDTH} height={OUTSIDE_CAMERA_TAG_HEIGHT * markerAspect}
              viewBox={`0 0 ${OUTSIDE_CAMERA_TAG_WIDTH} ${OUTSIDE_CAMERA_TAG_HEIGHT}`}
              preserveAspectRatio="none" overflow="visible">
              <rect x="1" y="1" width={OUTSIDE_CAMERA_TAG_WIDTH - 2} height={OUTSIDE_CAMERA_TAG_HEIGHT - 2}
                rx="10" fill="#fff" stroke="#ef4444" strokeWidth="2" />
              <svg x="15" y="10" width="32" height="32" viewBox="0 0 512 512"
                data-testid="street-view-outside-warning-icon" aria-hidden="true">
                <path fill="#ef4444" d="M256 0c14.7 0 28.2 8.1 35.2 21l216 400c6.7 12.4 6.4 27.4-.8 39.5S486.1 480 472 480L40 480c-14.1 0-27.2-7.4-34.4-19.5s-7.5-27.1-.8-39.5l216-400c7-12.9 20.5-21 35.2-21zm0 352a32 32 0 1 0 0 64 32 32 0 1 0 0-64zm0-192c-18.2 0-32.7 15.5-31.4 33.7l7.4 104c.9 12.5 11.4 22.3 23.9 22.3 12.6 0 23-9.7 23.9-22.3l7.4-104c1.3-18.2-13.1-33.7-31.4-33.7z" />
              </svg>
              <text x="55" y="34" fill="#ef4444" fontSize="25" fontWeight="600"
                fontFamily="var(--curio-font-family)">Camera outside the active tile</text>
            </svg>
          </g>}
          {marqueeStart && marqueeEnd && <rect x={Math.min(marqueeStart[0], marqueeEnd[0])} y={Math.min(marqueeStart[1], marqueeEnd[1])} width={Math.abs(marqueeEnd[0] - marqueeStart[0])} height={Math.abs(marqueeEnd[1] - marqueeStart[1])} fill="#e0000022" stroke="#e00000" strokeDasharray="6 4" />}
        </svg>}
      </div>
      <div style={{ ...ui.panel, ...ui.row, justifyContent: 'space-between', gap: 8 }}>
        <span>{ready ? `${network.features.length} lines` : 'No network loaded'}</span>
        <span>{issues.length ? `${issues.length} blocking validation issue(s)`
          : ready ? network.features.length ? 'Geometry valid' : 'Empty network · geometry valid'
            : 'Validation unavailable'}</span>
      </div>
      {navigationTarget && <div role="status" style={ui.status}>Loading tile {navigationTarget}…</div>}
      {movementNotice && <div role="status" style={ui.warning}>{movementNotice}</div>}
      {outside && <div role="status" style={{ ...S.card, ...S.row, justifyContent: 'space-between' }}>
        <span>Camera outside current tile · {Math.round(outside.metres)} m from boundary</span>
        <button type="button" onClick={openCameraTile} disabled={!cameraTileId || cameraTileId === tileId || !!navigationTarget || !currentInspection.current}
          style={{ ...S.btn, ...S.btnSecondary, width: 'auto' }}>
          {cameraTileId && cameraTileId !== tileId && currentInspection.current ? `Open camera tile ${cameraTileId}` : 'Camera tile unavailable'}
        </button>
      </div>}
      {requestedPoint && <div role="status" style={ui.status}>Requested Street View point: lon {requestedPoint[0].toFixed(6)}°, lat {requestedPoint[1].toFixed(6)}°</div>}
      {requestedPoint && !camera && inspectionStatus?.state === 'missing-key' && <div role="status" style={ui.panel}>
        Street View requires an API key. Configure it in the connected Street View Panorama node.
      </div>}
      {requestedPoint && !camera && inspectionStatus?.state === 'invalid-key' && <div role="alert" style={ui.warning}>
        Street View needs a valid Maps JavaScript API key in the connected Panorama node.
      </div>}
      {requestedPoint && !camera && inspectionStatus?.state === 'loading' && <div role="status" style={ui.panel}>Loading Street View…</div>}
      {requestedPoint && !camera && (inspectionStatus?.state === 'error' || inspectionStatus?.state === 'unavailable') && <div role="alert" style={ui.warning}>
        {inspectionStatus.message || (inspectionStatus.state === 'unavailable' ? 'No nearby Street View panorama is available.' : 'Street View could not load. Check the browser key and connection, then Retry in Panorama.')}
      </div>}
      {issues.length > 0 && <div role="alert" style={ui.error}>{issues.slice(0, 3).join(' ')}</div>}
      {topologyWarnings.length > 0 && <details aria-label="Sidewalk topology warnings"
        onToggle={event => setWarningsOpen(event.currentTarget.open)}
        style={{ ...ui.warning, maxHeight: warningsOpen ? 160 : 48 }}>
        <summary>{topologyWarnings.length} topology warning(s)</summary>
        {topologyWarnings.map(warning => <div key={warning.code} style={{ marginTop: 5 }}>
          {warning.message} Affected features: {warning.featureIndexes.slice(0, 8).map(index =>
            String(network.features[index]?.id ?? index + 1)).join(', ')}
          {warning.featureIndexes.length > 8 ? ` and ${warning.featureIndexes.length - 8} more` : ''}.
        </div>)}
      </details>}
      {selectedNode && <div style={ui.helper}>Node selected. Drag it onto another node to join the networks. Press Delete or Backspace to remove the node and its connected lines.</div>}
    </div>
  );
}
