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
import { MAX_TAGS, TagsField, parseTagEntry } from '../../pages/discovery/TagsField';
import { DiscoveryAddDialog } from '../../pages/discovery/DiscoveryAddDialog';
import { DiscoveryResourceRow } from '../../pages/discovery/DiscoveryResourceRow';
import type { DiscoveryParameter, DiscoveryResource } from '../../services/discoveryCatalog';

const AREA: DiscoveryParameter = {
  id: 'area', type: 'area', label: 'Area', description: '', required: true, accepts: ['box'], maxAreaKm2: 4,
};
const NAMED: DiscoveryParameter = { ...AREA, accepts: ['names'], maxAreaKm2: undefined };
const LOOP: [number, number, number, number] = [-87.64, 41.875, -87.62, 41.89];

// Places as the server's place search answers them: OpenStreetMap's own name
// and Nominatim's English label (Köln as test_places.py's Nominatim answer gives it).
const CHICAGO = {
  name: 'Chicago', label: 'Chicago, Cook County, Illinois, United States',
  box: [-87.940101, 41.643919, -87.523984, 42.023022], kind: 'boundary/administrative', boundary: true,
};
const KOELN = {
  name: 'Köln', label: 'Cologne, North Rhine-Westphalia, Germany',
  box: [6.77253, 50.83044, 7.162028, 51.084974], kind: 'boundary/administrative', boundary: true,
};
const INNENSTADT = {
  name: 'Innenstadt', label: 'Innenstadt, Cologne, North Rhine-Westphalia, Germany',
  box: [6.929, 50.917, 6.99, 50.955], kind: 'boundary/administrative', boundary: true,
};

/** The place search answers each query with its own places, and none for any other. */
function answerPlaces(answers: Record<string, unknown[]>) {
  mockSearchPlaces.mockImplementation(async (query: string) => ({ places: answers[query] ?? [] }));
}

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
    answerPlaces({
      Chicago: [CHICAGO],
      'Loop, Chicago': [
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

  test('the place in Within is looked up on Enter, never as it is typed, and shown as OpenStreetMap names it', async () => {
    answerPlaces({ Cologne: [KOELN] });
    render(<AreaField parameter={NAMED} value={null} onChange={jest.fn()} />);
    const place = screen.getByPlaceholderText(/A city or region/);
    for (const typed of ['C', 'Col', 'Cologne']) {
      fireEvent.change(place, { target: { value: typed } });
    }
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    expect(mockSearchPlaces).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.keyDown(place, { key: 'Enter' });
    });
    expect(mockSearchPlaces).toHaveBeenCalledTimes(1);
    expect(mockSearchPlaces).toHaveBeenCalledWith('Cologne', expect.anything());
    expect(await screen.findByText('Köln')).toBeInTheDocument();
    expect(screen.getByText(/Cologne, North Rhine-Westphalia, Germany/)).toBeInTheDocument();
  });

  test('Find areas looks up Within first and searches inside the place as OpenStreetMap names it', async () => {
    answerPlaces({
      Cologne: [KOELN],
      'Innenstadt, Köln': [INNENSTADT],
      // Nominatim finds a place by its English name too; the loader does not.
      'Innenstadt, Cologne': [INNENSTADT],
    });
    const onChange = jest.fn();
    render(<AreaField parameter={NAMED} value={null} onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText(/A city or region/), { target: { value: 'Cologne' } });
    fireEvent.change(screen.getByPlaceholderText(/A neighbourhood or district/), { target: { value: 'Innenstadt' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    });
    const found = await screen.findByRole('button', { name: /^Innenstadt/ });
    expect(mockSearchPlaces.mock.calls.map(([query]) => query)).toEqual(['Cologne', 'Innenstadt, Köln']);
    expect(screen.getByText('Köln')).toBeInTheDocument();
    fireEvent.click(found);
    expect(onChange).toHaveBeenLastCalledWith({ names: { geocodeArea: 'Cologne', areas: ['Innenstadt'] } });
  });

  test('a place Within cannot find as a city or region says so, and no area is searched inside it', async () => {
    answerPlaces({
      // A place of that name that is not a boundary has no area to search in.
      Atlantis: [{ name: 'Atlantis', label: 'Atlantis, Paradise Island, Bahamas', box: LOOP, kind: 'tourism/hotel', boundary: false }],
    });
    render(<AreaField parameter={NAMED} value={null} onChange={jest.fn()} />);
    fireEvent.change(screen.getByPlaceholderText(/A city or region/), { target: { value: 'Atlantis' } });
    fireEvent.change(screen.getByPlaceholderText(/A neighbourhood or district/), { target: { value: 'Old Town' } });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    });
    expect(await screen.findByText('No city or region called "Atlantis" in OpenStreetMap.')).toBeInTheDocument();
    expect(mockSearchPlaces.mock.calls.map(([query]) => query)).toEqual(['Atlantis']);
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
      expect.objectContaining({ resourceId: 'abcd-1234' }), 'csv', { area: { box: LOOP } }, 'Crimes',
    );
  });

  test('a row with no parameters offers no Narrow', () => {
    render(<DiscoveryResourceRow resource={portalRow({ parameters: [] })} onDownload={jest.fn()} />);
    expect(screen.queryByRole('button', { name: 'Narrow…' })).toBeNull();
  });

  test('the dialog sends the tags as entered', () => {
    const onAdd = jest.fn();
    render(
      <DiscoveryAddDialog resource={portalRow({ parameters: [AREA, TAGS] })} splitBy={[]} onAdd={onAdd} onCancel={jest.fn()} />,
    );
    fireEvent.click(screen.getByRole('tab', { name: 'Coordinates' }));
    ['West', 'South', 'East', 'North'].forEach((name, i) =>
      fireEvent.change(screen.getByLabelText(name), { target: { value: String(LOOP[i]) } }),
    );
    expect(screen.getByText('Tags is needed.')).toBeInTheDocument();
    const tags = screen.getByRole('combobox', { name: 'Tags' });
    for (const entry of ['amenity = school', 'shop=*']) {
      fireEvent.change(tags, { target: { value: entry } });
      fireEvent.keyDown(tags, { key: 'Enter' });
    }
    fireEvent.click(screen.getByRole('button', { name: 'Add to Data Catalog' }));
    expect(onAdd).toHaveBeenCalledWith({
      title: 'Crimes', parameters: { area: { box: LOOP }, tags: ['amenity=school', 'shop=*'] },
    });
  });
});

const TAGS: DiscoveryParameter = {
  id: 'tags', type: 'tags', label: 'Tags', description: '', required: true, suggestions: ['amenity', 'shop'],
};

/** The field, holding its own answer as the dialog does. */
function TagsHarness({ initial = [] as string[] }) {
  const [value, setValue] = React.useState<string[]>(initial);
  return <TagsField parameter={TAGS} value={value} onChange={setValue} />;
}

describe('the tags field', () => {
  test('an entry is key=value or key=*, with the spaces around each part dropped', () => {
    expect(parseTagEntry('amenity=school')).toBe('amenity=school');
    expect(parseTagEntry(' addr:street = Golf Road ')).toBe('addr:street=Golf Road');
    expect(parseTagEntry('shop=*')).toBe('shop=*');
    for (const bad of ['amenity', 'amenity=', '=school', 'na me=x', 'name="x"', 'a[b]=c', 'name=a\\b', `k=${'x'.repeat(256)}`]) {
      expect(parseTagEntry(bad)).toBeNull();
    }
  });

  test('the form checks the entries and their number', () => {
    expect(parameterProblem([TAGS], { tags: ['amenity=school'] })).toBeNull();
    expect(parameterProblem([TAGS], {})).toBe('Tags is needed.');
    expect(parameterProblem([TAGS], { tags: ['amenity'] })).toBe('Tags: "amenity" is not a tag.');
    const many = Array.from({ length: MAX_TAGS + 1 }, (_, i) => `k${i}=*`);
    expect(parameterProblem([TAGS], { tags: many })).toBe(`Tags takes at most ${MAX_TAGS} tags.`);
  });

  test('Enter adds a chip, once; a chip can be removed', () => {
    render(<TagsHarness />);
    const input = screen.getByRole('combobox', { name: 'Tags' });
    fireEvent.change(input, { target: { value: 'amenity=school' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.change(input, { target: { value: 'amenity=school' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getAllByText('amenity=school')).toHaveLength(1);
    expect(input).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Remove amenity=school' }));
    expect(screen.queryByText('amenity=school')).toBeNull();
  });

  test('an entry that is not a tag says so and adds nothing', () => {
    render(<TagsHarness />);
    const input = screen.getByRole('combobox', { name: 'Tags' });
    fireEvent.change(input, { target: { value: 'amenity' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByText('"amenity" is not a tag: write key=value or key=*.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Remove/ })).toBeNull();
  });

  test('the suggested keys are offered as key=*', () => {
    const { container } = render(<TagsHarness />);
    const options = [...container.querySelectorAll('datalist option')].map((o) => o.getAttribute('value'));
    expect(options).toEqual(['amenity=*', 'shop=*']);
  });

  test(`at ${MAX_TAGS} tags the field takes no more`, () => {
    render(<TagsHarness initial={Array.from({ length: MAX_TAGS }, (_, i) => `k${i}=*`)} />);
    expect(screen.getByRole('combobox', { name: 'Tags' })).toBeDisabled();
    expect(screen.getByText(`${MAX_TAGS} tags at most.`)).toBeInTheDocument();
  });
});
