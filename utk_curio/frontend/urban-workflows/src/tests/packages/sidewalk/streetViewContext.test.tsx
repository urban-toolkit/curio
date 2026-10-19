import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
const { useSidewalkTileEditBehavior } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/sidewalkTileEditBehavior');
const { useStreetViewPanoramaBehavior } = require('../../../../../../../packages/curio.streetvision@1/sources/streetViewPanoramaBehavior');
const { sourceFingerprint } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/streetViewContract');
const { DEFAULT_IMAGE_TEMPLATE, DEFAULT_NETWORK_TEMPLATE } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/SidewalkTileEditor');

const tile = (id: string, west: number) => ({ type: 'Feature', properties: { tile_id: id,
  image_url: `image-${id}.png`, network_url: `network-${id}.geojson` },
  geometry: { type: 'Polygon', coordinates: [[[west, 0], [west + 1, 0], [west + 1, 1], [west, 1], [west, 0]]] } });
const grid = { type: 'FeatureCollection', features: [tile('A', 0), tile('B', 1)] };
const mapEvent = (index: number) => ({ details: { autk_selection: { data: index === 0 ? [0] : [0, 1], priority: 1,
  selectionOrigin: { version: 1, kind: 'map-pick', activeIndex: index }, featureId: index ? 'B' : 'A' } }, priority: 1 });

function EditorHost({ interactions, send, persist, initialCode = '', input = grid }: { interactions: unknown; send: (event: unknown) => void; persist: jest.Mock; initialCode?: string; input?: unknown }) {
  const [code, setCode] = React.useState(initialCode);
  return <>{useSidewalkTileEditBehavior({ nodeId: 'editor', input, interactions,
    outputCallback: jest.fn(), interactionsCallback: (event: unknown) => send(event) },
  { code, setCode: (next: string) => { persist(next); setCode(next); }, setOutput: jest.fn() }).contentComponent}</>;
}
function PanoramaHost({ interactions, send }: { interactions: unknown; send: (event: unknown) => void }) {
  return <>{useStreetViewPanoramaBehavior({ nodeId: 'panorama', input: null, interactions,
    outputCallback: jest.fn(), interactionsCallback: (event: unknown) => send(event) },
  { code: '', setCode: jest.fn(), setOutput: jest.fn() }).contentComponent}</>;
}
function PanoramaHarness({ persist, onCamera }: { persist: jest.Mock; onCamera?: (event: any) => void }) {
  const [editorInteractions, setEditorInteractions] = React.useState<unknown[]>([mapEvent(0)]);
  const [viewerInteractions, setViewerInteractions] = React.useState<unknown[]>([]);
  return <>
    <EditorHost interactions={editorInteractions} persist={persist} send={event =>
      setViewerInteractions([{ details: event, priority: 1 }])} />
    <PanoramaHost interactions={viewerInteractions} send={event => {
      onCamera?.(event); setEditorInteractions([{ details: event, priority: 1 }]);
    }} />
  </>;
}

test('missing key keeps the latest requested point gray and shows an inline notice', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  try {
    const events: any[] = [];
    const view = render(<PanoramaHarness persist={jest.fn()} onCamera={event => events.push(event)} />);
    fireEvent.load(await screen.findByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true,
      value: () => ({ left: 0, top: 0, width: 1000, height: 1000 }) });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' }));
    fireEvent.click(svg, { clientX: 450, clientY: 550 });
    await screen.findByText('Street View requires an API key. Configure it in the connected Street View Panorama node.');
    expect(screen.getByText(/API key required to load Street View/)).toBeInTheDocument();
    expect(view.container.querySelector('[data-testid="street-view-pending-marker"]')?.getAttribute('transform')).toBe('translate(450 550)');
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();
    fireEvent.click(svg, { clientX: 650, clientY: 350 });
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-pending-marker"]')?.getAttribute('transform')).toBe('translate(650 350)'));
    expect(events.filter(event => event['curio.panorama.status']?.state === 'missing-key')).toHaveLength(2);
    fireEvent.click(svg, { clientX: 1, clientY: 999 });
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-pending-marker"]')?.getAttribute('transform')).not.toBe('translate(650 350)'));
    const coordinates = view.container.querySelector('[data-testid="street-view-pending-marker"]')!.getAttribute('transform')!.match(/[\d.]+/g)!.map(Number);
    expect(coordinates[0]).toBeGreaterThan(1); expect(coordinates[1]).toBeLessThan(999);
    expect(screen.queryByText('Camera outside the active tile')).not.toBeInTheDocument();

    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();
  } finally { global.fetch = previousFetch; }
});

test('a viewer request initially answered with no tile is answered again after the editor restores its selection', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const persisted = JSON.stringify({ schema: 'curio.sidewalk-tile-edit/v1',
    imageUrlTemplate: DEFAULT_IMAGE_TEMPLATE, networkUrlTemplate: DEFAULT_NETWORK_TEMPLATE, byTile: {},
    activeSelection: { tileId: 'A', sourceFingerprint: sourceFingerprint(undefined, DEFAULT_IMAGE_TEMPLATE, DEFAULT_NETWORK_TEMPLATE, grid) } });
  const request = [{ details: { 'sidewalk.active-tile-request': {
    schema: 'io.github.lzml0.sidewalk-stewards/active-tile-request/v1', viewerId: 'viewer',
    viewerEpoch: 'reopen', requestRevision: 1,
  } }, priority: 1 }];
  const sent: any[] = [];
  try {
    const view = render(<EditorHost input={null} interactions={request} persist={jest.fn()} initialCode={persisted} send={event => sent.push(event)} />);
    await waitFor(() => expect(sent.some(event => event['sidewalk.active-tile']?.tileId === null)).toBe(true));
    view.rerender(<EditorHost input={grid} interactions={request} persist={jest.fn()} initialCode={persisted} send={event => sent.push(event)} />);
    await screen.findByAltText('Satellite image for tile A');
    await waitFor(() => expect(sent.some(event => event['sidewalk.active-tile']?.tileId === 'A')).toBe(true));
  } finally { global.fetch = previousFetch; }
});

test('reopened workflow rehydrates the persisted active tile without a transient map event', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const persisted = JSON.stringify({ schema: 'curio.sidewalk-tile-edit/v1',
    imageUrlTemplate: DEFAULT_IMAGE_TEMPLATE, networkUrlTemplate: DEFAULT_NETWORK_TEMPLATE, byTile: {},
    activeSelection: { tileId: 'B', sourceFingerprint: sourceFingerprint(undefined, DEFAULT_IMAGE_TEMPLATE, DEFAULT_NETWORK_TEMPLATE, grid) } });
  try {
    render(<EditorHost interactions={[]} send={jest.fn()} persist={jest.fn()} initialCode={persisted} />);
    await screen.findByAltText('Satellite image for tile B');
  } finally { global.fetch = previousFetch; }
});

test('editor emits a generic point request and accepts correlated generic camera navigation', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const sent: any[] = [];
  const persist = jest.fn();
  try {
    const view = render(<EditorHost interactions={[mapEvent(0)]} persist={persist} send={event => sent.push(event)} />);
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true,
      value: () => ({ left: 0, top: 0, width: 1000, height: 1000 }) });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' }));
    fireEvent.click(svg, { clientX: 450, clientY: 550 });
    const generic = sent.find(event => event['curio.panorama.request'])?.['curio.panorama.request'];
    expect(generic).toMatchObject({ schema: 'curio.streetvision/panorama-request/v1',
      location: [expect.closeTo(0.45), expect.closeTo(0.45)], crs: 'EPSG:4326' });
    const camera = { schema: 'curio.streetvision/panorama-camera/v1', requestId: generic.requestId,
      revision: generic.revision, viewerId: 'generic-viewer', cameraRevision: 1,
      requestedLocation: generic.location, actualLocation: [1.1, 0.5], panoId: 'outside',
      headingDegrees: 135, headingReference: 'clockwise-from-true-north' };
    const savedBefore = persist.mock.calls.length;
    view.rerender(<EditorHost interactions={[{ details: { 'curio.panorama.camera': camera }, priority: 1 }]}
      persist={persist} send={event => sent.push(event)} />);
    await screen.findByText(/Camera outside current tile/);
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toHaveTextContent('Camera outside the active tile');
    expect(persist.mock.calls.length).toBe(savedBefore);
  } finally { global.fetch = previousFetch; }
});

test('generic camera rotation, changed panorama IDs, navigation, and a newer inspection preserve the editor draft', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const sent: any[] = [];
  const persist = jest.fn();
  const marker = (view: ReturnType<typeof render>) => view.container.querySelector('[data-testid="street-view-camera-marker"]');
  const heading = (view: ReturnType<typeof render>) => (view.container.querySelector('[data-testid="stewards-camera-heading"]') as SVGGElement | null)?.style.transform;
  try {
    const editor = (interactions: unknown) => <div className="react-flow__viewport">
      <EditorHost interactions={interactions} persist={persist} send={event => sent.push(event)} />
    </div>;
    const view = render(editor([mapEvent(0)]));
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    let renderedWidth = 1000;
    let renderedHeight = 1000;
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true,
      value: () => ({ left: 0, top: 0, width: renderedWidth, height: renderedHeight }) });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' }));
    fireEvent.click(svg, { clientX: 450, clientY: 550 });
    const first = sent.find(event => event['curio.panorama.request'])['curio.panorama.request'];
    const camera = (request: any, cameraRevision: number, actualLocation: number[], headingDegrees: number, panoId: string) => ({
      schema: 'curio.streetvision/panorama-camera/v1', requestId: request.requestId,
      revision: request.revision, viewerId: 'generic-viewer', cameraRevision,
      requestedLocation: request.location, actualLocation, panoId, headingDegrees,
      headingReference: 'clockwise-from-true-north',
    });
    const deliver = (payload: any) => view.rerender(editor([{ details: { 'curio.panorama.camera': payload }, priority: 1 }]));
    const savedBefore = persist.mock.calls.length;
    deliver(camera(first, 1, [0.45, 0.45], 350, 'pano-a'));
    await waitFor(() => expect(heading(view)).toBe('rotate(350deg)'));
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeNull();
    const symbol = view.container.querySelector('[data-testid="stewards-camera-symbol"]')!;
    expect(symbol.getAttribute('viewBox')).toBe('0 0 36 36');
    expect(symbol.getAttribute('preserveAspectRatio')).toBe('none');
    expect(Number(symbol.getAttribute('width'))).toBeCloseTo(40);
    expect(Number(symbol.getAttribute('height'))).toBeCloseTo(40);
    expect(symbol.querySelector('path')?.getAttribute('d')).toBe('M 4.48 14.38 A 14 14 0 0 1 31.52 14.38');
    expect(symbol.querySelector('path')?.getAttribute('opacity')).toBe('0.82');
    expect(Array.from(symbol.querySelectorAll('circle')).map(circle => circle.getAttribute('r'))).toEqual(['6', '3.5']);
    const viewport = view.container.querySelector('.react-flow__viewport') as HTMLElement;
    act(() => {
      renderedWidth = 500;
      renderedHeight = 400;
      viewport.style.transform = 'scale(0.5)';
      window.dispatchEvent(new Event('resize'));
    });
    await waitFor(() => {
      expect(Number(symbol.getAttribute('width'))).toBeCloseTo(40);
      expect(Number(symbol.getAttribute('height'))).toBeCloseTo(40 * 1.25);
    });
    act(() => {
      renderedWidth = 1000;
      renderedHeight = 1000;
      viewport.style.transform = 'scale(1)';
    });
    await waitFor(() => expect(Number(symbol.getAttribute('width'))).toBeCloseTo(40));
    expect(marker(view)?.getAttribute('transform')).toBe('translate(450 550)');
    deliver(camera(first, 2, [0.45, 0.45], 10, 'pano-b'));
    await waitFor(() => expect(heading(view)).toBe('rotate(370deg)'));
    expect(marker(view)?.getAttribute('transform')).toBe('translate(450 550)');
    deliver(camera(first, 3, [0.55, 0.55], 25, 'pano-c'));
    await waitFor(() => expect(marker(view)?.getAttribute('transform')).toBe('translate(550 450)'));
    expect(heading(view)).toBe('rotate(385deg)');
    deliver(camera(first, 4, [1.1, 0.5], 30, 'pano-outside'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-outside-tag"]'))
      .toHaveTextContent('Camera outside the active tile'));
    expect(view.container.querySelector('[data-testid="street-view-outside-warning-icon"] path'))
      .toHaveAttribute('fill', '#ef4444');
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"] text'))
      .toHaveAttribute('fill', '#ef4444');
    expect(marker(view)).toBeNull();
    const expectOutsideCueWithinImage = () => {
      const position = view.container.querySelector('[data-testid="street-view-outside-cue"]')
        ?.getAttribute('transform')?.match(/translate\(([-\d.]+) ([-\d.]+)\)/);
      const tag = view.container.querySelector('[data-testid="street-view-outside-tag"]');
      expect(position).toBeTruthy();
      expect(tag).toBeTruthy();
      const x = Number(position![1]), y = Number(position![2]);
      const tagX = x + Number(tag!.getAttribute('x'));
      const tagY = y + Number(tag!.getAttribute('y'));
      expect(tagX).toBeGreaterThanOrEqual(0);
      expect(tagX + Number(tag!.getAttribute('width'))).toBeLessThanOrEqual(1000);
      expect(tagY).toBeGreaterThanOrEqual(0);
      expect(tagY + Number(tag!.getAttribute('height'))).toBeLessThanOrEqual(1000);
    };
    expectOutsideCueWithinImage();
    for (const [revision, location] of [[5, [0.5, -0.1]], [6, [0.5, 1.1]], [7, [-0.1, 0.5]]] as const) {
      deliver(camera(first, revision, [...location], 30, `pano-outside-${revision}`));
      expect(marker(view)).toBeNull();
      expectOutsideCueWithinImage();
    }
    deliver(camera(first, 8, [0.55, 0.55], 35, 'pano-inside'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeNull());
    expect(view.container.querySelector('[data-testid="street-view-request-marker"]')).toBeNull();
    expect(screen.getByText(/Requested Street View point: lon 0\.450000°, lat 0\.450000°/)).toBeInTheDocument();
    deliver(camera(first, 9, [1.1, 0.5], 40, 'pano-outside-again'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeTruthy());
    fireEvent.click(svg, { clientX: 650, clientY: 350 });
    const second = sent.filter(event => event['curio.panorama.request']).at(-1)['curio.panorama.request'];
    expect(second.requestId).not.toBe(first.requestId);
    expect(marker(view)).toBeNull();
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeNull();
    deliver(camera(first, 99, [0.7, 0.7], 90, 'stale'));
    expect(marker(view)).toBeNull();
    deliver(camera(second, 1, [0.65, 0.65], 75, 'new'));
    await waitFor(() => expect(marker(view)).toBeTruthy());
    expect(heading(view)).toBe('rotate(75deg)');
    expect(screen.getByText("Tile A")).toBeInTheDocument();
    expect(persist.mock.calls.length).toBe(savedBefore);
  } finally { global.fetch = previousFetch; }
});

test('the outside label follows the current camera across tiles and the red pointer returns on its tile', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const sent: any[] = [];
  const persist = jest.fn();
  const editor = (interactions: unknown) => <EditorHost interactions={interactions} persist={persist}
    send={event => sent.push(event)} />;
  try {
    const view = render(editor([mapEvent(0)]));
    fireEvent.load(await screen.findByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true,
      value: () => ({ left: 0, top: 0, width: 1000, height: 1000 }) });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' }));
    fireEvent.click(svg, { clientX: 450, clientY: 550 });
    const request = sent.find(event => event['curio.panorama.request'])['curio.panorama.request'];
    const camera = (revision: number, location: number[], heading: number) => ({ details: {
      'curio.panorama.camera': { schema: 'curio.streetvision/panorama-camera/v1',
        requestId: request.requestId, revision: request.revision, viewerId: 'generic-viewer',
        cameraRevision: revision, requestedLocation: request.location, actualLocation: location,
        panoId: 'live-camera', headingDegrees: heading, headingReference: 'clockwise-from-true-north' },
    }, priority: 1 });
    view.rerender(editor([camera(1, [0.45, 0.45], 90)]));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')
      ?.getAttribute('transform')).toBe('translate(450 550)'));
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeNull();

    view.rerender(editor([mapEvent(1)]));
    fireEvent.load(await screen.findByAltText('Satellite image for tile B'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-outside-tag"]'))
      .toHaveTextContent('Camera outside the active tile'));
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();

    view.rerender(editor([camera(2, [1.25, 0.5], 225)]));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')
      ?.getAttribute('transform')).toBe('translate(250 500)'));
    const displayedHeading = Number(view.container.querySelector('[data-testid="stewards-camera-heading"]')
      ?.getAttribute('style')?.match(/rotate\(([-\d.]+)deg\)/)?.[1]);
    expect(((displayedHeading % 360) + 360) % 360).toBe(225);
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeNull();

    view.rerender(editor([mapEvent(0)]));
    fireEvent.load(await screen.findByAltText('Satellite image for tile A'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-outside-tag"]'))
      .toHaveTextContent('Camera outside the active tile'));
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();

    view.rerender(editor([mapEvent(1)]));
    fireEvent.load(await screen.findByAltText('Satellite image for tile B'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')
      ?.getAttribute('transform')).toBe('translate(250 500)'));
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toBeNull();
  } finally { global.fetch = previousFetch; }
});

test('native panorama events travel through the generic viewer interaction edge to the editor', async () => {
  const previousFetch = global.fetch;
  const previousGoogle = (window as any).google;
  const panoramas: any[] = [];
  let lookup = 0;
  class Panorama {
    listeners = new Map<string, Set<() => void>>();
    position: { lng: () => number; lat: () => number };
    heading: number;
    pano: string;
    constructor(_element: HTMLElement, options: any) {
      this.position = { lng: () => options.position.lng, lat: () => options.position.lat };
      this.heading = options.pov.heading;
      this.pano = options.pano;
      panoramas.push(this);
    }
    addListener(name: string, callback: () => void) {
      const callbacks = this.listeners.get(name) ?? new Set(); callbacks.add(callback); this.listeners.set(name, callbacks);
      return { remove: () => callbacks.delete(callback) };
    }
    emit(name: string) { this.listeners.get(name)?.forEach(callback => callback()); }
    getPosition() { return this.position; }
    getPov() { return { heading: this.heading, pitch: 0 }; }
    getPano() { return this.pano; }
    setVisible(_visible: boolean) {}
  }
  (window as any).google = { maps: { StreetViewPanorama: Panorama,
    StreetViewService: class { getPanorama(request: any) {
      const pano = `pano-${++lookup}`;
      return Promise.resolve({ data: { location: { latLng: {
        lng: () => request.location.lng, lat: () => request.location.lat,
      }, pano } } });
    } } } };
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const persist = jest.fn();
  const outgoing: any[] = [];
  try {
    const view = render(<PanoramaHarness persist={persist} onCamera={event => outgoing.push(event)} />);
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true,
      value: () => ({ left: 0, top: 0, width: 1000, height: 1000 }) });
    fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
    fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'browser-test-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' }));
    fireEvent.click(svg, { clientX: 450, clientY: 550 });
    await waitFor(() => expect(panoramas).toHaveLength(1));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeTruthy());
    expect(view.container.querySelector('[data-testid="street-view-pending-marker"]')).toBeNull();
    expect(screen.queryByText('Street View requires an API key. Configure it in the connected Street View Panorama node.')).toBeNull();
    const first = panoramas[0];
    const savedBefore = persist.mock.calls.length;
    act(() => { first.heading = 135; first.emit('pov_changed'); });
    await waitFor(() => expect((view.container.querySelector('[data-testid="stewards-camera-heading"]') as SVGGElement)?.style.transform).toBe('rotate(135deg)'));
    act(() => { first.position = { lng: () => 0.55, lat: () => 0.55 }; first.pano = 'moved-pano'; first.emit('pano_changed'); first.emit('position_changed'); });
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')?.getAttribute('transform')).toBe('translate(550 450)'));
    expect(outgoing.filter(event => event['curio.panorama.camera']).at(-1)['curio.panorama.camera']).toMatchObject({ panoId: 'moved-pano', actualLocation: [0.55, 0.55], headingDegrees: 135 });
    fireEvent.click(svg, { clientX: 650, clientY: 350 });
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();
    await waitFor(() => expect(panoramas).toHaveLength(2));
    const second = panoramas[1];
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeTruthy());
    const secondPosition = view.container.querySelector('[data-testid="street-view-camera-marker"]')?.getAttribute('transform');
    const emittedBeforeStale = outgoing.length;
    act(() => { first.heading = 225; first.emit('pov_changed'); });
    expect(outgoing.length).toBe(emittedBeforeStale);
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')?.getAttribute('transform')).toBe(secondPosition);
    expect(outgoing.filter(event => event['curio.panorama.camera']).at(-1)['curio.panorama.camera'].panoId).toBe(second.pano);
    expect(screen.getByText("Tile A")).toBeInTheDocument();
    expect(persist.mock.calls.length).toBe(savedBefore);
  } finally { global.fetch = previousFetch; (window as any).google = previousGoogle; }
});

test('Open camera tile adopts the running panorama without a lookup or edit', async () => {
  const previousFetch = global.fetch;
  const previousGoogle = (window as any).google;
  const panoramas: any[] = [];
  const lookup = jest.fn(async () => ({ data: { location: { latLng: {
    lng: () => 0.45, lat: () => 0.45,
  }, pano: 'live-a' } } }));
  class Panorama {
    listeners = new Map<string, Set<() => void>>();
    position = { lng: () => 0.45, lat: () => 0.45 };
    heading = 0;
    pano = 'live-a';
    constructor(_element: HTMLElement, _options: unknown) { panoramas.push(this); }
    addListener(name: string, callback: () => void) {
      const callbacks = this.listeners.get(name) ?? new Set(); callbacks.add(callback); this.listeners.set(name, callbacks);
      return { remove: () => callbacks.delete(callback) };
    }
    emit(name: string) { this.listeners.get(name)?.forEach(callback => callback()); }
    getPosition() { return this.position; }
    getPov() { return { heading: this.heading, pitch: 0 }; }
    getPano() { return this.pano; }
    setVisible(_visible: boolean) {}
  }
  (window as any).google = { maps: { StreetViewPanorama: Panorama,
    StreetViewService: class { getPanorama = lookup; } } };
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  const persist = jest.fn();
  try {
    const view = render(<PanoramaHarness persist={persist} />);
    await screen.findByAltText('Satellite image for tile A');
    fireEvent.load(screen.getByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true,
      value: () => ({ left: 0, top: 0, width: 1000, height: 1000 }) });
    fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
    fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' }));
    fireEvent.click(svg, { clientX: 450, clientY: 550 });
    await waitFor(() => expect(panoramas).toHaveLength(1));
    const before = lookup.mock.calls.length;
    const savedBefore = persist.mock.calls.length;
    act(() => { panoramas[0].position = { lng: () => 1.25, lat: () => 0.5 };
      panoramas[0].pano = 'live-b'; panoramas[0].heading = 225;
      panoramas[0].emit('position_changed'); });
    await screen.findByText(/Camera outside current tile/);
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();
    expect(view.container.querySelector('[data-testid="street-view-outside-tag"]')).toHaveTextContent('Camera outside the active tile');
    fireEvent.click(screen.getByRole('button', { name: 'Open camera tile B' }));
    await screen.findByAltText('Satellite image for tile B');
    fireEvent.load(screen.getByAltText('Satellite image for tile B'));
    await waitFor(() => expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeTruthy());
    expect(panoramas).toHaveLength(1);
    expect(lookup).toHaveBeenCalledTimes(before);
    expect(screen.getByText(/Requested Street View point: lon 1.250000/)).toBeInTheDocument();
    const displayedHeading = Number(view.container.querySelector('[data-testid="stewards-camera-heading"]')
      ?.getAttribute('style')?.match(/rotate\(([-\d.]+)deg\)/)?.[1]);
    expect(((displayedHeading % 360) + 360) % 360).toBe(225);
    expect(persist.mock.calls.length).toBeGreaterThanOrEqual(savedBefore); // active tile choice persists, no edit operation is added.
    expect(screen.getByText("Tile B")).toBeInTheDocument();
  } finally { global.fetch = previousFetch; (window as any).google = previousGoogle; }
});


test('failed inspection keeps gray marker and its specific error; stale status cannot replace it', async () => {
  const previousFetch = global.fetch;
  global.fetch = jest.fn(async () => ({ ok: true, json: async () => ({ type: 'FeatureCollection', features: [] }) })) as unknown as typeof fetch;
  try {
    let sent: any; const persist = jest.fn(); const send = (event: any) => { if (event['curio.panorama.request']) sent = event; };
    const view = render(<EditorHost interactions={[mapEvent(0)]} persist={persist} send={send} />);
    fireEvent.load(await screen.findByAltText('Satellite image for tile A'));
    const svg = screen.getByLabelText('Sidewalk tile image and network');
    Object.defineProperty(svg, 'getBoundingClientRect', { configurable: true, value: () => ({ left: 0, top: 0, width: 1000, height: 1000 }) });
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Street View' })); fireEvent.click(svg, { clientX: 300, clientY: 400 });
    const request = sent['curio.panorama.request'];
    const status = { schema: 'curio.streetvision/panorama-status/v1', requestId: request.requestId, revision: request.revision, viewerId: 'panorama', state: 'error', message: 'Street View request failed (REQUEST_DENIED).' };
    view.rerender(<EditorHost interactions={[{ details: { 'curio.panorama.status': status }, priority: 1 }]} persist={persist} send={send} />);
    expect(await screen.findByText('Street View request failed (REQUEST_DENIED).')).toBeVisible();
    expect(screen.getByLabelText('Requested location — Street View not loaded')).toBeInTheDocument();
    expect(view.container.querySelector('[data-testid="street-view-camera-marker"]')).toBeNull();
    view.rerender(<EditorHost interactions={[{ details: { 'curio.panorama.status': { ...status, requestId: 'stale', message: 'Wrong request' } }, priority: 1 }]} persist={persist} send={send} />);
    expect(screen.queryByText('Wrong request')).not.toBeInTheDocument();
    expect(screen.getByText('Street View request failed (REQUEST_DENIED).')).toBeVisible();
  } finally { global.fetch = previousFetch; }
});
