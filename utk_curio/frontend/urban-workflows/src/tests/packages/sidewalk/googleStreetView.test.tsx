import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

const { GoogleStreetView, bearingToward, loadGoogleStreetView } = require('../../../../../../../packages/curio.sidewalk-stewards@1/sources/googleStreetView');

const latLng = (lng: number, lat: number) => ({ lng: () => lng, lat: () => lat });
const deferred = () => {
  let resolve!: (result: unknown) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

function sdk() {
  const lookups: ReturnType<typeof deferred>[] = [];
  const requests: unknown[] = [];
  const panoramas: any[] = [];
  const resizeEvents: string[] = [];
  class Service {
    getPanorama(request: unknown) {
      requests.push(request);
      const lookup = deferred();
      lookups.push(lookup);
      return lookup.promise;
    }
  }
  class Panorama {
    listeners = new Map<string, Set<() => void>>();
    removed = 0;
    visible = true;
    position: ReturnType<typeof latLng>;
    heading: number;
    panoId: string;
    options: any;
    constructor(_element: HTMLElement, options: any) {
      this.options = options;
      this.position = latLng(options.position.lng, options.position.lat);
      this.heading = options.pov.heading;
      this.panoId = options.pano;
      panoramas.push(this);
    }
    addListener(name: string, callback: () => void) {
      const callbacks = this.listeners.get(name) ?? new Set();
      callbacks.add(callback);
      this.listeners.set(name, callbacks);
      return { remove: () => { callbacks.delete(callback); this.removed += 1; } };
    }
    emit(name: string) { this.listeners.get(name)?.forEach(callback => callback()); }
    getPosition() { return this.position; }
    getPov() { return { heading: this.heading, pitch: 0 }; }
    getPano() { return this.panoId; }
    setVisible(value: boolean) { this.visible = value; }
  }
  (window as any).google = { maps: { StreetViewService: Service, StreetViewPanorama: Panorama,
    StreetViewPreference: { NEAREST: 'NEAREST' }, event: { trigger: (_pano: unknown, name: string) => resizeEvents.push(name) } } };
  return { lookups, requests, panoramas, resizeEvents };
}

afterEach(() => { delete (window as any).google; });

test('looks up the clicked point and follows real panorama rotation and navigation', async () => {
  const mock = sdk();
  const onCamera = jest.fn();
  const view = render(<GoogleStreetView browserKey="browser-test-key" request={[-34.9, -8.1]} radiusMetres={60} onCamera={onCamera} />);
  await waitFor(() => expect(mock.lookups).toHaveLength(1));
  view.rerender(<GoogleStreetView browserKey="browser-test-key" request={[-34.9, -8.1]} radiusMetres={60} onCamera={onCamera} />);
  expect(mock.lookups).toHaveLength(1);
  expect(mock.requests[0]).toEqual({ location: { lat: -8.1, lng: -34.9 }, radius: 60, preference: 'NEAREST' });
  await act(async () => mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.8999, -8.1), pano: 'pano-a' } } }));
  const panorama = mock.panoramas[0];
  expect(panorama.options.pov.heading).toBeCloseTo(270, 0);
  expect(onCamera).toHaveBeenLastCalledWith({ location: [-34.8999, -8.1], headingDegrees: expect.closeTo(270, 0), pitchDegrees: 0, panoId: 'pano-a' }, '-34.9,-8.1');
  expect(screen.getByLabelText('Interactive Google Street View panorama')).toBeVisible();
  act(() => { panorama.heading = 225; panorama.emit('pov_changed'); });
  expect(onCamera).toHaveBeenLastCalledWith({ location: [-34.8999, -8.1], headingDegrees: 225, pitchDegrees: 0, panoId: 'pano-a' }, '-34.9,-8.1');
  act(() => { panorama.position = latLng(-34.91, -8.11); panorama.panoId = 'pano-b'; panorama.emit('position_changed'); panorama.emit('pano_changed'); });
  expect(onCamera).toHaveBeenLastCalledWith({ location: [-34.91, -8.11], headingDegrees: 225, pitchDegrees: 0, panoId: 'pano-b' }, '-34.9,-8.1');
});

test('a newer click supersedes an unresolved lookup and unmount removes all listeners', async () => {
  const mock = sdk();
  const onCamera = jest.fn();
  const view = render(<GoogleStreetView browserKey="browser-test-key" request={[-34.9, -8.1]} radiusMetres={60} onCamera={onCamera} />);
  await waitFor(() => expect(mock.lookups).toHaveLength(1));
  view.rerender(<GoogleStreetView browserKey="browser-test-key" request={[-34.91, -8.11]} radiusMetres={60} onCamera={onCamera} />);
  await waitFor(() => expect(mock.lookups).toHaveLength(2));
  await act(async () => mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.9, -8.1), pano: 'stale' } } }));
  expect(mock.panoramas).toHaveLength(0);
  await act(async () => mock.lookups[1].resolve({ data: { location: { latLng: latLng(-34.91, -8.11), pano: 'new' } } }));
  expect(mock.panoramas).toHaveLength(1);
  expect(onCamera).toHaveBeenLastCalledWith({ location: [-34.91, -8.11], headingDegrees: 0, pitchDegrees: 0, panoId: 'new' }, '-34.91,-8.11');
  const panorama = mock.panoramas[0];
  view.unmount();
  expect(panorama.removed).toBe(3);
  expect(panorama.visible).toBe(false);
  const calls = onCamera.mock.calls.length;
  act(() => { panorama.heading = 30; panorama.emit('pov_changed'); });
  expect(onCamera).toHaveBeenCalledTimes(calls);
});

test('unavailable or too-distant results do not create a misleading camera', async () => {
  const mock = sdk();
  const onCamera = jest.fn();
  const view = render(<GoogleStreetView browserKey="browser-test-key" request={[-34.9, -8.1]} radiusMetres={60} onCamera={onCamera} />);
  await waitFor(() => expect(mock.lookups).toHaveLength(1));
  await act(async () => mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.91, -8.11), pano: 'far' } } }));
  expect(screen.getByText(/No live Street View panorama is available/)).toBeInTheDocument();
  expect(mock.panoramas).toHaveLength(0);
  expect(onCamera).not.toHaveBeenCalled();
  view.rerender(<GoogleStreetView browserKey="browser-test-key" request={[-34.91, -8.11]} radiusMetres={60} onCamera={onCamera} />);
  await waitFor(() => expect(mock.lookups).toHaveLength(2));
  await act(async () => mock.lookups[1].reject(new Error('ZERO_RESULTS')));
  expect(screen.getByText(/No live Street View panorama is available/)).toBeInTheDocument();
});

test('resizing notifies the viewer and disconnects its observer on unmount', async () => {
  const previous = global.ResizeObserver;
  const observers: any[] = [];
  (global as any).ResizeObserver = class {
    callback: () => void;
    disconnect = jest.fn();
    observe = jest.fn();
    constructor(callback: () => void) { this.callback = callback; observers.push(this); }
  };
  try {
    const mock = sdk();
    const view = render(<GoogleStreetView browserKey="browser-test-key" request={[-34.9, -8.1]} radiusMetres={60} onCamera={jest.fn()} />);
    await waitFor(() => expect(mock.lookups).toHaveLength(1));
    await act(async () => mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.9, -8.1), pano: 'pano' } } }));
    expect(observers[0].observe).toHaveBeenCalled();
    act(() => observers[0].callback());
    expect(mock.resizeEvents).toEqual(['resize']);
    view.unmount();
    expect(observers[0].disconnect).toHaveBeenCalled();
  } finally { (global as any).ResizeObserver = previous; }
});

test('initial direction calculation is geographic and normalized', () => {
  expect(bearingToward([0, 0], [1, 0])).toBeCloseTo(90);
  expect(bearingToward([0, 0], [0, -1])).toBeCloseTo(180);
  expect(bearingToward([0, 0], [-1, 0])).toBeCloseTo(270);
});

test('two viewer instances keep independent cameras and cleanup', async () => {
  const mock = sdk();
  const firstCamera = jest.fn();
  const secondCamera = jest.fn();
  const first = render(<GoogleStreetView browserKey="browser-test-key" request={[-34.9, -8.1]} radiusMetres={60} onCamera={firstCamera} />);
  const second = render(<GoogleStreetView browserKey="browser-test-key" request={[-34.91, -8.11]} radiusMetres={60} onCamera={secondCamera} />);
  await waitFor(() => expect(mock.lookups).toHaveLength(2));
  await act(async () => {
    mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.9, -8.1), pano: 'first' } } });
    mock.lookups[1].resolve({ data: { location: { latLng: latLng(-34.91, -8.11), pano: 'second' } } });
  });
  expect(mock.panoramas).toHaveLength(2);
  act(() => { mock.panoramas[1].heading = 95; mock.panoramas[1].emit('pov_changed'); });
  expect(secondCamera).toHaveBeenLastCalledWith(expect.objectContaining({ panoId: 'second', headingDegrees: 95 }), '-34.91,-8.11');
  expect(firstCamera).toHaveBeenCalledTimes(1);
  first.unmount();
  expect(mock.panoramas[0].visible).toBe(false);
  expect(mock.panoramas[1].visible).toBe(true);
  second.unmount();
  expect(mock.panoramas[1].visible).toBe(false);
});

test('concurrent viewers share one SDK script load', async () => {
  const first = loadGoogleStreetView('browser-test-key');
  const second = loadGoogleStreetView('browser-test-key');
  expect(first).toBe(second);
  const scripts = [...document.head.querySelectorAll('script[src*="maps.googleapis.com/maps/api/js"]')];
  expect(scripts).toHaveLength(1);
  const maps = { StreetViewPanorama: class {}, StreetViewService: class {} };
  (window as any).google = { maps };
  (scripts[0] as HTMLScriptElement).onload?.(new Event('load'));
  await expect(first).resolves.toBe(maps);
  await expect(second).resolves.toBe(maps);
  scripts[0].remove();
});


test('previous native camera cannot confirm a pending or failed target', async () => {
  const mock = sdk(); const onCamera = jest.fn(); const onStatus = jest.fn();
  const props = { browserKey: 'browser-test-key', radiusMetres: 60, onCamera, onStatus };
  const view = render(<GoogleStreetView {...props} request={[-34.9, -8.1]} requestKey="a:1" />);
  await waitFor(() => expect(mock.lookups).toHaveLength(1));
  await act(async () => mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.9, -8.1), pano: 'a' } } }));
  const panorama = mock.panoramas[0];
  panorama.setPosition = jest.fn(); panorama.setPov = jest.fn(); panorama.setPano = jest.fn();
  onCamera.mockClear();
  view.rerender(<GoogleStreetView {...props} request={[-34.91, -8.11]} requestKey="b:2" />);
  await waitFor(() => expect(mock.lookups).toHaveLength(2));
  expect(screen.getByText(/Showing the previous location until this request is confirmed/)).toBeVisible();
  act(() => panorama.emit('pov_changed'));
  expect(onCamera).not.toHaveBeenCalled();
  await act(async () => mock.lookups[1].resolve({ data: { location: { latLng: latLng(-34.91, -8.11), pano: 'b' } } }));
  expect(onCamera).not.toHaveBeenCalled();
  expect(onStatus).toHaveBeenLastCalledWith('loading', undefined);
  act(() => { panorama.panoId = 'b'; panorama.emit('pano_changed'); });
  expect(onCamera).not.toHaveBeenCalled();
  act(() => { panorama.position = latLng(-34.91, -8.11); panorama.heading = 145; panorama.emit('position_changed'); });
  expect(onCamera).toHaveBeenLastCalledWith(expect.objectContaining({ location: [-34.91, -8.11], headingDegrees: 145, panoId: 'b' }), 'b:2');
  expect(onStatus).toHaveBeenLastCalledWith('ready', undefined);
  view.rerender(<GoogleStreetView {...props} request={[-34.92, -8.12]} requestKey="c:3" />);
  await waitFor(() => expect(mock.lookups).toHaveLength(3)); onCamera.mockClear();
  await act(async () => mock.lookups[2].reject(new Error('REQUEST_DENIED')));
  expect(screen.getByRole('alert')).toHaveTextContent('REQUEST_DENIED');
  expect(screen.getByRole('alert')).toHaveTextContent('Showing the previous location');
  act(() => panorama.emit('position_changed'));
  expect(onCamera).not.toHaveBeenCalled();
});

test('inactive inspection cancels its lookup without confirming a delayed response', async () => {
  const mock = sdk(); const onCamera = jest.fn();
  const props = { browserKey: 'browser-test-key', radiusMetres: 60, onCamera };
  const view = render(<GoogleStreetView {...props} request={[-34.9, -8.1]} active={false} />);
  expect(mock.lookups).toHaveLength(0);
  view.rerender(<GoogleStreetView {...props} request={[-34.9, -8.1]} active />);
  await waitFor(() => expect(mock.lookups).toHaveLength(1));
  view.rerender(<GoogleStreetView {...props} request={[-34.9, -8.1]} active={false} />);
  await act(async () => mock.lookups[0].resolve({ data: { location: { latLng: latLng(-34.9, -8.1), pano: 'stale' } } }));
  expect(onCamera).not.toHaveBeenCalled(); expect(mock.panoramas).toHaveLength(0);
});
