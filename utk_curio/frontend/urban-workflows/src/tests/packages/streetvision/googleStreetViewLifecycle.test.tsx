import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
const { GoogleStreetView } = require('../../../../../../../packages/curio.streetvision@1/sources/googleStreetView');

test('ordinary updates keep one viewer; adoption reuses it without lookup; Return explicitly looks up', async () => {
  const original = (window as any).google;
  const lookups: any[] = [];
  const instances: any[] = [];
  class Panorama {
    position = { lng: () => -34.9, lat: () => -8.1 };
    heading = 20;
    pano = 'first';
    listeners = new Map<string, Set<() => void>>();
    constructor(_element: HTMLElement, options: any) {
      this.pano = options.pano; instances.push(this);
    }
    addListener(name: string, callback: () => void) {
      const callbacks = this.listeners.get(name) ?? new Set(); callbacks.add(callback); this.listeners.set(name, callbacks);
      return { remove: () => callbacks.delete(callback) };
    }
    getPosition() { return this.position; }
    getPov() { return { heading: this.heading, pitch: 0 }; }
    getPano() { return this.pano; }
    setPosition(next: { lat: number; lng: number }) { this.position = { lng: () => next.lng, lat: () => next.lat }; }
    setPov(next: { heading: number }) { this.heading = next.heading; }
    setPano(next: string) { this.pano = next; }
    setVisible(_visible: boolean) {}
  }
  (window as any).google = { maps: { StreetViewPanorama: Panorama,
    StreetViewService: class { getPanorama(request: any) {
      lookups.push(request);
      return Promise.resolve({ data: { location: { pano: lookups.length === 1 ? 'first' : 'returned',
        latLng: { lng: () => request.location.lng, lat: () => request.location.lat } } } });
    } } } };
  const onCamera = jest.fn();
  const onStatus = jest.fn();
  try {
    const view = render(<GoogleStreetView browserKey="test-key" request={[-34.9, -8.1]} requestKey="first:1"
      radiusMetres={60} onCamera={onCamera} onStatus={onStatus} />);
    await waitFor(() => expect(lookups).toHaveLength(1));
    await waitFor(() => expect(instances).toHaveLength(1));
    view.rerender(<GoogleStreetView browserKey="test-key" request={[-34.9, -8.1]} requestKey="first:1"
      radiusMetres={90} onCamera={onCamera} onStatus={onStatus} />);
    expect(lookups).toHaveLength(1);
    act(() => { instances[0].position = { lng: () => -34.91, lat: () => -8.11 }; instances[0].pano = 'moved'; });
    view.rerender(<GoogleStreetView browserKey="test-key" request={[-34.91, -8.11]} requestKey="adopted:2"
      radiusMetres={60} reuseCurrent expectedPanoId="moved" onCamera={onCamera} onStatus={onStatus} />);
    await waitFor(() => expect(onCamera).toHaveBeenCalledWith(expect.objectContaining({ panoId: 'moved' }), 'adopted:2'));
    expect(lookups).toHaveLength(1);
    expect(instances).toHaveLength(1);
    view.rerender(<GoogleStreetView browserKey="test-key" request={[-34.91, -8.11]} requestKey="adopted:2"
      retryRevision={1} radiusMetres={60} reuseCurrent expectedPanoId="moved" onCamera={onCamera} onStatus={onStatus} />);
    await waitFor(() => expect(lookups).toHaveLength(2));
    expect(instances).toHaveLength(1);
    view.unmount();
    expect([...instances[0].listeners.values()].every((callbacks: Set<unknown>) => callbacks.size === 0)).toBe(true);
  } finally { (window as any).google = original; }
});
