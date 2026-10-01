import React from 'react';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';

/**
 * The questions a source declares, as the form a person fills in: the checks
 * it makes before sending, the area field's three ways to a box and its named
 * areas, and the answers it sends with an add or a download.
 */

const mockSearchPlaces = jest.fn();
const mockListCatalog = jest.fn();
const mockExtent = jest.fn();

jest.mock('../../services/discoveryCatalog', () => {
  const actual = jest.requireActual('../../services/discoveryCatalog');
  return {
    ...actual,
    discoveryCatalogApi: {
      ...actual.discoveryCatalogApi,
      searchPlaces: (...args: unknown[]) => mockSearchPlaces(...args),
    },
  };
});
jest.mock('../../services/datasetCatalog', () => {
  const actual = jest.requireActual('../../services/datasetCatalog');
  return {
    ...actual,
    datasetCatalogApi: {
      ...actual.datasetCatalogApi,
      listCatalog: (...args: unknown[]) => mockListCatalog(...args),
      extent: (...args: unknown[]) => mockExtent(...args),
    },
  };
});

import { AreaField, boxAreaKm2, boxProblem } from '../../pages/discovery/AreaField';
import { answered, parameterProblem } from '../../pages/discovery/SourceParameterForm';
import { DiscoveryAddDialog } from '../../pages/discovery/DiscoveryAddDialog';
import { DiscoveryResourceRow } from '../../pages/discovery/DiscoveryResourceRow';
import type { DiscoveryParameter, DiscoveryResource } from '../../services/discoveryCatalog';

const AREA: DiscoveryParameter = {
  id: 'area', type: 'area', label: 'Area', description: '', required: true, accepts: ['box'], maxAreaKm2: 4,
};
const LOOP: [number, number, number, number] = [-87.64, 41.875, -87.62, 41.89];

beforeEach(() => {
  jest.useFakeTimers();
  mockSearchPlaces.mockReset();
  mockListCatalog.mockReset();
  mockExtent.mockReset();
});

afterEach(() => {
  jest.useRealTimers();
});

describe('the checks the form makes', () => {
  test('a box is checked against the map and the source limit', () => {
    expect(boxProblem(LOOP, 4)).toBeNull();
    expect(boxProblem([-87.62, 41.875, -87.64, 41.89])).toMatch(/West must be left of east/);
    expect(boxProblem([-88, 41, -87, 42], 4)).toMatch(/this source takes at most 4.0 km²/);
    expect(boxAreaKm2([0, 0, 1, 1])).toBeCloseTo(12364, -1);
  });

  test('required answers, numbers, dates and links', () => {
    const params: DiscoveryParameter[] = [
      AREA,
      { id: 'n', type: 'integer', label: 'Images', description: '', required: false, min: 1, max: 10 },
      { id: 'd', type: 'dateRange', label: 'Captured', description: '', required: false },
      { id: 'u', type: 'url', label: 'Link', description: '', required: false },
    ];
    expect(parameterProblem(params, {})).toBe('Area is needed.');
    expect(parameterProblem(params, { area: { box: LOOP }, n: 11 })).toBe('Images is at most 10.');
    expect(parameterProblem(params, { area: { box: LOOP }, n: 2.5 })).toBe('Images takes a whole number.');
    expect(parameterProblem(params, { area: { box: LOOP }, d: { start: '2024-02-01', end: '2024-01-01' } }))
      .toBe('Captured starts after it ends.');
    expect(parameterProblem(params, { area: { box: LOOP }, u: 'http://x.org' })).toBe('Link must be an https link.');
    expect(parameterProblem(params, { area: { box: LOOP }, n: 3 })).toBeNull();
  });

  test('empty optional answers are not sent', () => {
    const params: DiscoveryParameter[] = [
      AREA,
      { id: 'h', type: 'choice', label: 'H', description: '', required: false, multiple: true,
        options: [{ value: '0', label: '0' }] },
    ];
    expect(answered(params, { area: { box: LOOP }, h: [] })).toEqual({ area: { box: LOOP } });
  });
});

describe('the area field', () => {
  test('four typed coordinates are a box, shown back with its size', () => {
    const onChange = jest.fn();
    const { rerender } = render(<AreaField parameter={AREA} value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Coordinates' }));
    ['West', 'South', 'East', 'North'].forEach((name, i) =>
      fireEvent.change(screen.getByLabelText(name), { target: { value: String(LOOP[i]) } }),
    );
    expect(onChange).toHaveBeenLastCalledWith({ box: LOOP });
    rerender(<AreaField parameter={AREA} value={{ box: LOOP }} onChange={onChange} />);
    expect(screen.getByText(/-87\.6400, 41\.8750 to -87\.6200, 41\.8900/)).toBeInTheDocument();
    expect(screen.getByText(/of at most 4\.0 km²/)).toBeInTheDocument();
  });

  test('a place search gives a box and the place name', async () => {
    mockSearchPlaces.mockResolvedValue({
      places: [{ name: 'Loop', label: 'Loop, Chicago, Illinois', box: LOOP, kind: 'boundary/administrative', boundary: true }],
    });
    const onChange = jest.fn();
    render(<AreaField parameter={AREA} value={null} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Area: search a place'), { target: { value: 'Loop, Chicago' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    });
    fireEvent.click(await screen.findByRole('option', { name: /Loop, Chicago, Illinois/ }));
    expect(mockSearchPlaces).toHaveBeenCalledWith('Loop, Chicago', expect.anything());
    expect(onChange).toHaveBeenLastCalledWith({ box: LOOP, label: 'Loop' });
  });

  test('a place is searched only when asked for, never as it is typed', async () => {
    // Nominatim's usage policy forbids auto-complete on its API.
    mockSearchPlaces.mockResolvedValue({ places: [] });
    render(<AreaField parameter={AREA} value={null} onChange={jest.fn()} />);
    const field = screen.getByLabelText('Area: search a place');
    for (const typed of ['L', 'Lo', 'Loop', 'Loop, Chicago']) {
      fireEvent.change(field, { target: { value: typed } });
    }
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    expect(mockSearchPlaces).not.toHaveBeenCalled();
    expect(screen.queryByText('No place by that name.')).toBeNull();

    await act(async () => {
      fireEvent.keyDown(field, { key: 'Enter' });
    });
    expect(mockSearchPlaces).toHaveBeenCalledTimes(1);
    expect(mockSearchPlaces).toHaveBeenCalledWith('Loop, Chicago', expect.anything());
    expect(await screen.findByText('No place by that name.')).toBeInTheDocument();
  });

  test('the place search credits OpenStreetMap', () => {
    render(<AreaField parameter={AREA} value={null} onChange={jest.fn()} />);
    expect(screen.getByRole('link', { name: 'OpenStreetMap contributors ↗' })).toHaveAttribute(
      'href',
      'https://www.openstreetmap.org/copyright',
    );
  });

  test("a dataset's extent gives a box", async () => {
    mockListCatalog.mockResolvedValue({
      items: [
        { id: 'imported.xparks', title: 'Parks', format: 'geojson', featureCount: 10 },
        { id: 'imported.xtable', title: 'Plain table', format: 'csv', featureCount: null },
      ],
      facets: {},
    });
    mockExtent.mockResolvedValue({ datasetId: 'imported.xparks', title: 'Parks', box: LOOP });
    const onChange = jest.fn();
    render(<AreaField parameter={AREA} value={null} onChange={onChange} />);
    fireEvent.click(screen.getByRole('tab', { name: "A dataset's extent" }));
    const select = await screen.findByLabelText('A dataset in your Data Catalog');
    expect(screen.queryByRole('option', { name: 'Plain table' })).toBeNull();
    fireEvent.change(select, { target: { value: 'imported.xparks' } });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ box: LOOP, label: 'Parks' }));
  });

  test('named areas, where the source takes them, are a place and OSM boundaries inside it', async () => {
    mockSearchPlaces.mockResolvedValue({
      places: [
        { name: 'Loop', label: 'Loop, Chicago', box: LOOP, kind: 'boundary/administrative', boundary: true },
        { name: 'Loop Street', label: 'Loop Street, Chicago', box: LOOP, kind: 'highway/residential', boundary: false },
      ],
    });
    const onChange = jest.fn();
    render(
      <AreaField parameter={{ ...AREA, accepts: ['box', 'names'], maxAreaKm2: undefined }} value={null} onChange={onChange} />,
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Named areas' }));
    fireEvent.change(screen.getByPlaceholderText(/A city or region/), { target: { value: 'Chicago' } });
    fireEvent.change(screen.getByPlaceholderText(/A neighbourhood or district/), { target: { value: 'Loop' } });
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    expect(mockSearchPlaces).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    });
    expect(mockSearchPlaces).toHaveBeenCalledWith('Loop, Chicago', expect.anything());
    // Only boundaries are named areas.
    expect(screen.queryByText('Loop Street')).toBeNull();
    fireEvent.click(await screen.findByRole('button', { name: /^Loop/ }));
    expect(onChange).toHaveBeenLastCalledWith({ names: { geocodeArea: 'Chicago', areas: ['Loop'] } });
  });
});

const portalRow = (over: Partial<DiscoveryResource> = {}): DiscoveryResource => ({
  sourceId: 'source.a.portal',
  sourceName: 'Alpha Portal',
  resourceId: 'abcd-1234',
  name: 'Crimes',
  description: '',
  publisher: '',
  formats: ['csv'],
  updatedAt: null,
  landingUrl: null,
  sizeHint: null,
  acquirable: true,
  alreadyHeldDatasetId: null,
  heldFormats: {},
  parameters: [{ ...AREA, required: false, maxAreaKm2: undefined }],
  ...over,
});

describe('what an add or a download sends', () => {
  test('the dialog sends the answers with the title', () => {
    const onAdd = jest.fn();
    render(
      <DiscoveryAddDialog resource={portalRow({ parameters: [AREA] })} splitBy={[]} onAdd={onAdd} onCancel={jest.fn()} />,
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Coordinates' }));
    ['West', 'South', 'East', 'North'].forEach((name, i) =>
      fireEvent.change(screen.getByLabelText(name), { target: { value: String(LOOP[i]) } }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    expect(onAdd).toHaveBeenCalledWith({ title: 'Crimes', parameters: { area: { box: LOOP } } });
  });

  test('a required answer missing keeps the dialog from sending', () => {
    const onAdd = jest.fn();
    render(
      <DiscoveryAddDialog resource={portalRow({ parameters: [AREA] })} splitBy={[]} onAdd={onAdd} onCancel={jest.fn()} />,
    );
    expect(screen.getByText('Area is needed.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    expect(onAdd).not.toHaveBeenCalled();
  });

  test('a portal row downloads whole in one click, or narrowed from its own dialog', () => {
    const onDownload = jest.fn();
    render(<DiscoveryResourceRow resource={portalRow()} onDownload={onDownload} />);
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    expect(onDownload).toHaveBeenLastCalledWith(expect.objectContaining({ resourceId: 'abcd-1234' }), 'csv');

    fireEvent.click(screen.getByRole('button', { name: 'Narrow…' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Coordinates' }));
    ['West', 'South', 'East', 'North'].forEach((name, i) =>
      fireEvent.change(screen.getByLabelText(name), { target: { value: String(LOOP[i]) } }),
    );
    fireEvent.click(screen.getAllByRole('button', { name: 'Download' }).at(-1)!);
    expect(onDownload).toHaveBeenLastCalledWith(
      expect.objectContaining({ resourceId: 'abcd-1234' }), 'csv', { area: { box: LOOP } },
    );
  });

  test('a row with no parameters offers no Narrow', () => {
    render(<DiscoveryResourceRow resource={portalRow({ parameters: [] })} onDownload={jest.fn()} />);
    expect(screen.queryByRole('button', { name: 'Narrow…' })).toBeNull();
  });
});
