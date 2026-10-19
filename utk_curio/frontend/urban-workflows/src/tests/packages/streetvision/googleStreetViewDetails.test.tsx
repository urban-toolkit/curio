import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
const { GoogleStreetView } = require('../../../../../../../packages/curio.streetvision@1/sources/googleStreetView');

test('location descriptions track the displayed panorama without extra lookup requests', async () => {
  const previousGoogle = (window as any).google;
  const onCamera = jest.fn();
  const lookup = jest.fn(async () => ({ data: { location: {
    latLng: { lng: () => -34.9, lat: () => -8.1 }, pano: 'pano-a',
    description: 'Avenida Boa Viagem', shortDescription: 'Boa Viagem',
  } } }));
  const panoramas: any[] = [];
  class Panorama {
    listeners = new Map<string, Set<() => void>>();
    position = { lng: () => -34.9, lat: () => -8.1 };
    heading = 0;
    pano = 'pano-a';
    location: any = null;
    constructor(_element: HTMLElement, _options: unknown) { panoramas.push(this); }
    addListener(name: string, listener: () => void) {
      const listeners = this.listeners.get(name) ?? new Set(); listeners.add(listener); this.listeners.set(name, listeners);
      return { remove: () => listeners.delete(listener) };
    }
    emit(name: string) { this.listeners.get(name)?.forEach(listener => listener()); }
    getPosition() { return this.position; }
    getPov() { return { heading: this.heading, pitch: 0 }; }
    getPano() { return this.pano; }
    getLocation() { return this.location; }
    setVisible(_visible: boolean) {}
  }
  (window as any).google = { maps: { StreetViewService: class { getPanorama = lookup; }, StreetViewPanorama: Panorama } };
  try {
    const props = { browserKey: 'fixture-key', request: [-34.9, -8.1] as [number, number],
      requestKey: 'request-a:1', radiusMetres: 60, onCamera };
    const view = render(<GoogleStreetView {...props} />);
    await waitFor(() => expect(onCamera).toHaveBeenCalled());
    expect(onCamera.mock.lastCall[0].description).toBe('Avenida Boa Viagem');
    expect(lookup).toHaveBeenCalledTimes(1);

    act(() => { panoramas[0].heading = 95; panoramas[0].emit('pov_changed'); });
    expect(onCamera.mock.lastCall[0]).toMatchObject({ panoId: 'pano-a', description: 'Avenida Boa Viagem', headingDegrees: 95 });
    expect(lookup).toHaveBeenCalledTimes(1);

    act(() => { panoramas[0].pano = 'pano-b'; panoramas[0].position = { lng: () => -34.8, lat: () => -8.2 };
      panoramas[0].location = { pano: 'pano-b', latLng: panoramas[0].position, description: 'Rua Nova' };
      panoramas[0].emit('pano_changed'); });
    expect(onCamera.mock.lastCall[0]).toMatchObject({ panoId: 'pano-b', location: [-34.8, -8.2], description: 'Rua Nova' });
    expect(lookup).toHaveBeenCalledTimes(1);

    act(() => { panoramas[0].pano = 'pano-c'; panoramas[0].position = { lng: () => -34.7, lat: () => -8.3 };
      panoramas[0].location = null; panoramas[0].emit('position_changed'); });
    expect(onCamera.mock.lastCall[0].description).toBeUndefined();
    view.rerender(<GoogleStreetView {...props} radiusMetres={120} initialHeadingDegrees={180} />);
    expect(lookup).toHaveBeenCalledTimes(1);
    view.unmount();
  } finally { (window as any).google = previousGoogle; }
});
