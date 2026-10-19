import React from 'react';
import fs from 'fs';
import path from 'path';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
jest.mock('../../../adapters/node', () => ({
  inputOnly: () => [], outputOnly: () => [], standardInOut: () => [], withBidirectional: (value: unknown) => value,
  useCodeNodeBehavior: () => ({}), usePackageNodeBehavior: () => ({}), withPackageStarter: (value: unknown) => value,
}));
jest.mock('../../../registry/iconRegistry', () => ({ resolveIconRef: () => null }));
jest.mock('../../../utils/authApi', () => ({ getToken: () => 'local-test-token' }));
jest.mock('../../../utils/backendUrl', () => ({ backendUrl: () => 'http://127.0.0.1:5002' }));
jest.mock('../../../registry/projectPackagesStore', () => ({ getCurrentProjectPackages: () => null, subscribe: () => () => {} }));
jest.mock('../../../services/packages', () => ({ packagesApi: { listInstalled: jest.fn() } }));
const { packagesApi } = require('../../../services/packages');
const { loadInstalledPackages } = require('../../../registry/packagesClient');
const { registerBehavior } = require('../../../registry/behaviorRegistry');

test('discovers renamed Sidewalk and Street Vision templates and loads their real bundles', async () => {
  const pkg = path.resolve(__dirname, '../../../../../../../packages/curio.sidewalk-stewards@1');
  const manifest = JSON.parse(fs.readFileSync(path.join(pkg, 'manifest.json'), 'utf8'));
  const bundle = fs.readFileSync(path.join(pkg, manifest.behaviorScript), 'utf8');
  const vision = path.resolve(pkg, '../curio.streetvision@1');
  const visionManifest = JSON.parse(fs.readFileSync(path.join(vision, 'manifest.json'), 'utf8'));
  const visionBundle = fs.readFileSync(path.join(vision, visionManifest.behaviorScript), 'utf8');
  packagesApi.listInstalled.mockResolvedValue({ packages: [manifest, visionManifest].map(entry => ({
    packageId: entry.id, major: 1, version: entry.version, name: entry.name,
    dirName: `${entry.id}@1`, behaviorScript: entry.behaviorScript,
    templates: entry.templates.map((template: any) => ({ ...template,
      id: `${entry.id}/${template.id}@1`, templateId: template.id, source: null })),
  })) });
  const previousFetch = global.fetch; const previousCurio = Object.getOwnPropertyDescriptor(window, 'curio');
  const registered = jest.fn(registerBehavior);
  Object.defineProperty(window, 'curio', { configurable: true, value: { registerBehavior: registered } });
  Object.defineProperty(window, 'React', { configurable: true, value: React });
  global.fetch = jest.fn(async (url: string) => ({ ok: true,
    text: async () => url.includes('curio.streetvision') ? visionBundle : bundle })) as unknown as typeof fetch;
  const nativeAppend = document.body.appendChild.bind(document.body);
  const append = jest.spyOn(document.body, 'appendChild').mockImplementation(node => {
    if (node instanceof HTMLScriptElement) { window.eval(node.textContent ?? ''); return node; }
    return nativeAppend(node);
  });
  try {
    const descriptors = await loadInstalledPackages();
    for (const id of ['curio.sidewalk-stewards', 'curio.streetvision']) {
      expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining(`/api/packages/${id}%401/file/scripts/behaviors.js`), expect.objectContaining({ cache: 'no-store', headers: { Authorization: 'Bearer local-test-token' } }));
    }
    expect(descriptors.map((entry: any) => entry.id).sort()).toEqual([
      'curio.sidewalk-stewards/sidewalk-prepare@1', 'curio.sidewalk-stewards/sidewalk-tile-edit@1',
      'curio.streetvision/street-view-fetcher@1', 'curio.streetvision/street-view-panorama@1',
    ]);
    expect(manifest.templates.map((entry: any) => entry.id).sort()).toEqual(['sidewalk-prepare', 'sidewalk-tile-edit']);
    expect(registered.mock.calls.map(([key]) => key).sort()).toEqual(['sidewalk-prepare', 'sidewalk-tile-edit', 'street-view-fetcher', 'street-view-panorama']);
    const useBehavior = descriptors.find((entry: any) => entry.id === 'curio.sidewalk-stewards/sidewalk-tile-edit@1').adapter.useNodeBehavior;
    expect(typeof useBehavior).toBe('function');
    const tile = { type: 'Feature', properties: { tile_id: 'bundle', network_url: 'bundle-network.geojson', image_url: 'data:image/png;base64,AA==' },
      geometry: { type: 'Polygon', coordinates: [[[0,0],[1,0],[1,1],[0,1],[0,0]]] } };
    const data = { nodeId: 'loaded-bundle', input: { type: 'FeatureCollection', features: [tile] }, interactions: [], outputCallback: jest.fn(), interactionsCallback: jest.fn() };
    const state = { code: JSON.stringify({ schema: 'curio.sidewalk-tile-edit/v1', byTile: { bundle: { network: { type: 'FeatureCollection', features: [] }, originalNetwork: { type: 'FeatureCollection', features: [] }, past: [], future: [], operations: [] } } }), setCode: jest.fn(), setOutput: jest.fn() };
    function NodeBody() { return useBehavior(data, state).contentComponent; }
    render(<NodeBody />);
    const image = await screen.findByRole('img');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeDisabled());
    fireEvent.load(image);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save network' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Save network' }));
    expect(data.outputCallback).toHaveBeenCalledWith('loaded-bundle', expect.objectContaining({ dataType: 'geodataframe' }));
    expect(data.interactionsCallback).toHaveBeenCalledWith(expect.objectContaining({ 'sidewalk.network-edit': expect.objectContaining({ editRevision: 1 }) }), 'loaded-bundle');
  } finally {
    append.mockRestore(); global.fetch = previousFetch;
    if (previousCurio) Object.defineProperty(window, 'curio', previousCurio); else Reflect.deleteProperty(window, 'curio');
  }
});
