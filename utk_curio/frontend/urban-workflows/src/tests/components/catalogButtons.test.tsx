/**
 * The five catalogs on the canvas bar. They used to sit under a "Data" menu,
 * in an order of their own, and the Discovery Catalog could be reached no
 * other way. Now each is one click, in the order the section tabs use on every
 * other page, and each opens its drawer over the dataflow.
 */
import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

const mockOpen = {
  node: jest.fn(),
  data: jest.fn(),
  agent: jest.fn(),
  discovery: jest.fn(),
  model: jest.fn(),
};
const mockPrefetch = jest.fn();

jest.mock('../../providers/packages/NodeCatalogDrawerProvider', () => ({
  useNodeCatalogDrawer: () => ({ openNodeCatalogDrawer: mockOpen.node }),
}));
jest.mock('../../providers/AgentCatalogDrawerProvider', () => ({
  useAgentCatalogDrawerControls: () => ({ openAgentCatalogDrawer: mockOpen.agent }),
}));
jest.mock('../../providers/datasetCatalog', () => ({
  useDatasetCatalogDrawer: () => ({ openDatasetCatalogDrawer: mockOpen.data }),
}));
jest.mock('../../providers/modelCatalog', () => ({
  useModelCatalogDrawer: () => ({ openModelCatalogDrawer: mockOpen.model }),
}));
jest.mock('../../providers/discoveryCatalog', () => ({
  useDiscoveryCatalogDrawer: () => ({ openDiscoveryCatalogDrawer: mockOpen.discovery }),
}));
jest.mock('../../services/datasetCatalog', () => ({
  prefetchDatasetCatalog: (...args: unknown[]) => mockPrefetch(...args),
}));

import { CatalogButtons } from '../../components/menus/top/CatalogButtons';

beforeEach(() => jest.clearAllMocks());

test('lists the catalogs in the section tabs\' order, by their full names', () => {
  render(<CatalogButtons projectId="p1" />);
  const group = screen.getByRole('group', { name: 'Catalogs' });
  expect(within(group).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual([
    'Node Catalog',
    'Data Catalog',
    'Agent Catalog',
    'Discovery Catalog',
    'Model Catalog',
  ]);
});

test('shows a short name that the accessible name contains', () => {
  render(<CatalogButtons projectId="p1" />);
  for (const button of screen.getAllByRole('button')) {
    const label = button.textContent!.trim();
    expect(label.length).toBeGreaterThan(0);
    expect(button.getAttribute('aria-label')!.startsWith(label)).toBe(true);
    // The full name is the tooltip too, for when the labels are hidden.
    expect(button.getAttribute('title')).toBe(button.getAttribute('aria-label'));
  }
});

test.each([
  ['Node Catalog', 'node'],
  ['Data Catalog', 'data'],
  ['Agent Catalog', 'agent'],
  ['Discovery Catalog', 'discovery'],
  ['Model Catalog', 'model'],
] as const)('%s opens its own drawer, and only that one', (name, key) => {
  render(<CatalogButtons projectId="p1" />);
  fireEvent.click(screen.getByRole('button', { name }));
  for (const [other, open] of Object.entries(mockOpen)) {
    expect(open).toHaveBeenCalledTimes(other === key ? 1 : 0);
  }
});

test('warms the Data Catalog on the way in, for a saved dataflow only', () => {
  const { unmount } = render(<CatalogButtons projectId="p1" />);
  fireEvent.mouseEnter(screen.getByRole('button', { name: 'Data Catalog' }));
  expect(mockPrefetch).toHaveBeenCalledWith({ dataflowId: 'p1', includeHub: true, sort: 'recent' });
  unmount();

  mockPrefetch.mockClear();
  render(<CatalogButtons projectId={null} />);
  fireEvent.mouseEnter(screen.getByRole('button', { name: 'Data Catalog' }));
  expect(mockPrefetch).not.toHaveBeenCalled();
});
