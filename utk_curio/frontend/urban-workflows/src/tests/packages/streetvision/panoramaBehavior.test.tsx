import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
const {
  PANORAMA_REQUEST_CHANNEL, PANORAMA_REQUEST_SCHEMA, PANORAMA_CAMERA_CHANNEL,
  latestPanoramaRequest, latestPanoramaCamera,
} = require('../../../../../../../packages/curio.streetvision@1/sources/panoramaContract');
const { browserKeyInputIssue, pointFromInput, useStreetViewPanoramaBehavior } = require('../../../../../../../packages/curio.streetvision@1/sources/streetViewPanoramaBehavior');
const { PANORAMA_STATUS_CHANNEL } = require('../../../../../../../packages/curio.streetvision@1/sources/panoramaContract');

const cameras: Array<(camera: any) => void> = [];
const viewerProps: any[] = [];
jest.mock('../../../../../../../packages/curio.streetvision@1/sources/googleStreetView', () => ({
  GoogleStreetView: ({ onCamera, request, requestKey, reuseCurrent, onStatus, retryRevision,
    radiusMetres, initialHeadingDegrees }: any) => {
    cameras.push(onCamera);
    viewerProps.push({ requestKey, reuseCurrent, onStatus, retryRevision, radiusMetres, initialHeadingDegrees });
    return <div data-testid="mock-panorama">{request.join(',')}</div>;
  },
}));

const request = (requestId: string, revision: number, location: [number, number]) => ({
  schema: PANORAMA_REQUEST_SCHEMA, requestId, revision, location, crs: 'EPSG:4326', radiusMetres: 60,
});
const interaction = (value: any) => [{ details: { [PANORAMA_REQUEST_CHANNEL]: value }, priority: 1 }];

function Host({ interactions, sent, input = null }: { interactions: unknown; sent: jest.Mock; input?: unknown }) {
  return <>{useStreetViewPanoramaBehavior({ nodeId: 'panorama', interactions, input,
    interactionsCallback: (event: unknown) => sent(event), outputCallback: jest.fn() } as any,
  { code: '', setCode: jest.fn(), setOutput: jest.fn() } as any).contentComponent}</>;
}

beforeEach(() => { cameras.length = 0; viewerProps.length = 0; });

test('a workflow URL entered as the browser key is rejected locally before creating a viewer', async () => {
  expect(browserKeyInputIssue('http://localhost:8626/dataflow/example')).toMatch(/not a workflow URL/);
  const view = render(<Host interactions={interaction(request('pick-A', 1, [-34.9, -8.1]))} sent={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), {
    target: { value: 'http://localhost:8626/dataflow/example' },
  });
  expect(screen.getByRole('alert')).toHaveTextContent('not a workflow URL');
  expect(viewerProps).toHaveLength(0);
  expect(screen.getByRole('button', { name: 'Return to requested location' })).toBeDisabled();
  view.unmount();
});

test('Cancel discards a draft browser key without changing the configured viewer', async () => {
  render(<Host interactions={interaction(request('pick-A', 1, [-34.9, -8.1]))} sent={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  expect(screen.queryByTestId('mock-panorama')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByText('Google Maps key not configured')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  expect(screen.getByLabelText('Maps JavaScript browser key')).toHaveValue('');
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByTestId('mock-panorama');
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'replacement-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByText('Google Maps key configured')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  expect(screen.getByLabelText('Maps JavaScript browser key')).toHaveValue('test-browser-key');
});

test('the latest pending request loads after key configuration and confirms only on a camera event', async () => {
  const sent = jest.fn();
  const view = render(<Host interactions={interaction(request('pick-A', 1, [-34.9, -8.1]))} sent={sent} />);
  view.rerender(<Host interactions={interaction(request('pick-B', 2, [-34.8, -8.2]))} sent={sent} />);
  const statuses = () => sent.mock.calls.map(([event]) => event[PANORAMA_STATUS_CHANNEL]).filter(Boolean);
  expect(statuses().at(-1)).toMatchObject({ requestId: 'pick-B', state: 'missing-key' });
  expect(viewerProps).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByText('-34.8,-8.2');
  expect(statuses().at(-1)).toMatchObject({ requestId: 'pick-B', state: 'loading' });
  expect(statuses().some((status: any) => status.requestId === 'pick-A' && status.state === 'loading')).toBe(false);
  act(() => viewerProps.at(-1).onStatus('ready'));
  expect(statuses().at(-1).state).toBe('loading');
  act(() => cameras.at(-1)!({ location: [-34.801, -8.201], headingDegrees: 90, panoId: 'confirmed' }));
  expect(statuses().at(-1)).toMatchObject({ requestId: 'pick-B', state: 'confirmed' });
  const count = statuses().length;
  view.rerender(<Host interactions={interaction(request('pick-B', 2, [-34.8, -8.2]))} sent={sent} />);
  expect(statuses()).toHaveLength(count);
});

test('generic requests are versioned and WGS84 points keep longitude-first order', () => {
  expect(pointFromInput({ dataType: 'geodataframe', data: { type: 'FeatureCollection', features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-34.9, -8.1] } },
  ] } })).toEqual([-34.9, -8.1]);
  expect(pointFromInput({ type: 'Point', coordinates: [200, -8] })).toBeNull();
  expect(pointFromInput({ type: 'FeatureCollection', features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-34.9, -8.1] } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-34.8, -8.2] } },
  ] })).toBeNull();
  expect(latestPanoramaRequest(interaction(request('pick-1', 1, [-34.9, -8.1])))).toEqual(request('pick-1', 1, [-34.9, -8.1]));
  expect(latestPanoramaRequest(interaction({ ...request('pick-1', 1, [-34.9, -8.1]), crs: 'EPSG:3857' }))).toBeNull();
});

test('a newer interaction supersedes an older camera and publishes live position and direction', async () => {
  const sent = jest.fn();
  const view = render(<Host interactions={interaction(request('pick-A', 1, [-34.9, -8.1]))} sent={sent} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByText('-34.9,-8.1');
  const staleCamera = cameras.at(-1)!;
  view.rerender(<Host interactions={interaction(request('pick-B', 2, [-34.91, -8.11]))} sent={sent} />);
  await screen.findByText('-34.91,-8.11');
  const beforeStale = sent.mock.calls.length;
  act(() => staleCamera({ location: [-34.9, -8.1], headingDegrees: 10, panoId: 'old' }));
  expect(sent).toHaveBeenCalledTimes(beforeStale);
  act(() => cameras.at(-1)!({ location: [-34.911, -8.112], headingDegrees: 225,
    pitchDegrees: -5, zoom: 2, panoId: 'new' }));
  await waitFor(() => expect(sent.mock.calls.some(([event]) => event[PANORAMA_CAMERA_CHANNEL])).toBe(true));
  const cameraEvent = sent.mock.calls.find(([event]) => event[PANORAMA_CAMERA_CHANNEL])![0];
  const camera = cameraEvent[PANORAMA_CAMERA_CHANNEL];
  expect(camera).toMatchObject({ requestId: 'pick-B', revision: 2,
    requestedLocation: [-34.91, -8.11], actualLocation: [-34.911, -8.112], panoId: 'new',
    headingDegrees: 225, headingReference: 'clockwise-from-true-north', pitchDegrees: -5, zoom: 2 });
  expect(latestPanoramaCamera([{ details: cameraEvent, priority: 1 }])).toEqual(camera);
});

test('an adopted connected target retains the viewer and Return remains an explicit action', async () => {
  const sent = jest.fn();
  const view = render(<Host interactions={interaction(request('original', 1, [-34.9, -8.1]))} sent={sent} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByText('-34.9,-8.1');
  act(() => viewerProps.at(-1).onStatus('ready'));
  act(() => cameras.at(-1)!({ location: [-34.91, -8.11], headingDegrees: 127, panoId: 'live-camera' }));
  const adopted = { ...request('adopted', 2, [-34.91, -8.11]),
    reuseCurrent: { viewerId: 'panorama', panoId: 'live-camera' } };
  view.rerender(<Host interactions={interaction(adopted)} sent={sent} />);
  await screen.findByText('-34.91,-8.11');
  expect(viewerProps.at(-1)).toMatchObject({ requestKey: 'adopted:2', reuseCurrent: true });
  act(() => viewerProps.at(-1).onStatus('ready'));
  const beforeReturn = viewerProps.at(-1).retryRevision;
  fireEvent.click(screen.getByRole('button', { name: 'Return to requested location' }));
  expect(viewerProps.at(-1).retryRevision).toBe(beforeReturn + 1);
});

test('ordinary input opens automatically while manual coordinates require submission', async () => {
  const sent = jest.fn();
  const view = render(<Host interactions={[]} sent={sent} input={{ dataType: 'json', data: { type: 'Point', coordinates: [-34.9, -8.1] } }} />);
  await screen.findByText(/lon -34.900000/);
  expect(screen.getByText(/API key required to load Street View/)).toBeInTheDocument();
  fireEvent.click(screen.getByText('Enter coordinates'));
  fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '-34.8' } });
  fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '-8.2' } });
  expect(screen.getByText(/lon -34.900000/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'View location' }));
  expect(screen.getByText(/lon -34.800000/)).toBeInTheDocument();
  view.rerender(<Host interactions={[]} sent={sent} input={{ dataType: 'json', data: { type: 'Point', coordinates: [-34.9, -8.1] } }} />);
  expect(screen.getByText(/lon -34.800000/)).toBeInTheDocument();
});

test('an ordinary point artifact resolves without selecting a row from a multi-point result', async () => {
  const previousFetch = global.fetch;
  const fetchMock = jest.fn().mockResolvedValue({ ok: true, json: async () => ({
    dataType: 'geodataframe', data: { type: 'FeatureCollection', features: [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [-34.9, -8.1] } },
    ] },
  }) });
  global.fetch = fetchMock as any;
  try {
    const view = render(<Host interactions={[]} sent={jest.fn()} input="point-artifact" />);
    await waitFor(() => expect(screen.getByText(/lon -34.900000/)).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/get?fileName=point-artifact'), expect.any(Object));
    view.rerender(<Host interactions={[]} sent={jest.fn()} input={{ type: 'FeatureCollection', features: [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [-34.9, -8.1] } },
      { type: 'Feature', geometry: { type: 'Point', coordinates: [-34.8, -8.2] } },
    ] }} />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('WGS84 point'));
    expect(screen.getByRole('alert')).toHaveTextContent('WGS84 point');
  } finally { global.fetch = previousFetch; }
});

test('the compact viewer uses Font Awesome controls, one live readout, and stable disclosures', async () => {
  const view = render(<Host interactions={interaction(request('pick-A', 1, [-34.9, -8.1]))} sent={jest.fn()} />);
  const root = screen.getByRole('region', { name: 'Street View Panorama' });
  for (const icon of ['gear', 'location-arrow', 'location-dot', 'reply', 'crosshairs', 'sliders', 'chevron-right', 'chevron-down']) {
    expect(root.querySelector(`[data-icon="${icon}"]`)).toBeTruthy();
  }
  const sections = Array.from(root.querySelectorAll('details'));
  expect(sections).toHaveLength(3);
  expect(sections.every(section => !section.open)).toBe(true);
  expect(screen.getByText('Heading unavailable')).toBeInTheDocument();
  expect(screen.getByText('Distance unavailable')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Location details'));
  expect(sections[0].open).toBe(true);
  expect(screen.getByText('Location description unavailable')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByTestId('mock-panorama');
  act(() => viewerProps.at(-1).onStatus('ready'));
  act(() => cameras.at(-1)!({ location: [-34.901, -8.101], headingDegrees: 358,
    panoId: 'pano-1', description: 'Avenida Boa Viagem' }));
  expect(screen.getByText('Heading 358°')).toBeInTheDocument();
  expect(screen.getByText(/m from requested point/)).toBeInTheDocument();
  expect(screen.getByText('Avenida Boa Viagem')).toBeInTheDocument();
  expect(sections[0].open).toBe(true);
  expect(root.querySelector('[data-testid="live-street-view-camera"]')).toBeNull();
  view.unmount();
});

test('advanced fields wait for explicit manual submission and preserve the connected request', async () => {
  const sent = jest.fn();
  render(<Host interactions={interaction(request('connected', 1, [-34.9, -8.1]))} sent={sent} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByTestId('mock-panorama');
  const initialViewerCalls = viewerProps.length;
  fireEvent.click(screen.getByText('Advanced options'));
  fireEvent.change(screen.getByLabelText('Search radius metres'), { target: { value: '120' } });
  fireEvent.change(screen.getByLabelText('Initial heading degrees'), { target: { value: '270' } });
  expect(screen.getByText('Maximum distance from the requested point to search for available imagery.')).toBeInTheDocument();
  expect(viewerProps.at(-1).requestKey).toBe('connected:1');
  expect(viewerProps.length).toBeGreaterThanOrEqual(initialViewerCalls);
  fireEvent.click(screen.getByText('Enter coordinates'));
  fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '-34.8' } });
  fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '-8.2' } });
  expect(viewerProps.at(-1).requestKey).toBe('connected:1');
  fireEvent.click(screen.getByRole('button', { name: 'View location' }));
  expect(viewerProps.at(-1)).toMatchObject({ radiusMetres: 120, initialHeadingDegrees: 270 });
  expect(screen.getByTestId('mock-panorama')).toHaveTextContent('-34.8,-8.2');
  expect(sent.mock.calls.every(([event]) => !event[PANORAMA_CAMERA_CHANNEL])).toBe(true);
});

test('a recoverable provider failure offers Retry for the accepted request', async () => {
  render(<Host interactions={interaction(request('pick-A', 1, [-34.9, -8.1]))} sent={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByTestId('mock-panorama');
  act(() => viewerProps.at(-1).onStatus('error'));
  expect(screen.getByRole('status')).toHaveTextContent('Panorama error');
  const previousRevision = viewerProps.at(-1).retryRevision;
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(viewerProps.at(-1)).toMatchObject({ requestKey: 'pick-A:1', retryRevision: previousRevision + 1 });
});


test('provider errors are forwarded as request-scoped diagnostics without confirmation', async () => {
  const sent = jest.fn();
  render(<Host interactions={interaction(request('failure', 3, [-34.9, -8.1]))} sent={sent} />);
  fireEvent.click(screen.getByRole('button', { name: 'Panorama settings' }));
  fireEvent.change(screen.getByLabelText('Maps JavaScript browser key'), { target: { value: 'test-browser-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add configuration' }));
  await screen.findByTestId('mock-panorama');
  act(() => viewerProps.at(-1).onStatus('error', 'Street View request failed (REQUEST_DENIED).'));
  const statuses = sent.mock.calls.map(([event]) => event[PANORAMA_STATUS_CHANNEL]).filter(Boolean);
  expect(statuses.at(-1)).toMatchObject({ requestId: 'failure', revision: 3, state: 'error', message: 'Street View request failed (REQUEST_DENIED).' });
  expect(sent.mock.calls.some(([event]) => event[PANORAMA_CAMERA_CHANNEL])).toBe(false);
});
