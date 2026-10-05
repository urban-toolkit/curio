import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';

import { SEARCH_DEBOUNCE_MS, useDiscoverySearch } from '../../services/discoveryCatalog';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const EMPTY = { resources: [], sources: [], nextCursor: null, totalHint: null, truncated: false };

function Probe(props: { q: string; sourceDir?: string }) {
  const { data, loading, searched } = useDiscoverySearch(props);
  return (
    <div>
      <span data-testid="count">{data.resources.length}</span>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="searched">{String(searched)}</span>
    </div>
  );
}

beforeEach(() => {
  jest.useFakeTimers();
  apiFetch.mockReset();
  apiFetch.mockResolvedValue(EMPTY);
});
afterEach(() => {
  jest.runOnlyPendingTimers();
  jest.useRealTimers();
});

async function settle() {
  await act(async () => {
    jest.advanceTimersByTime(SEARCH_DEBOUNCE_MS + 10);
  });
}

describe('useDiscoverySearch', () => {
  test('a settled query issues exactly one request', async () => {
    render(<Probe q="bike" />);
    expect(apiFetch).not.toHaveBeenCalled();
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  test('typing fast issues one fan-out, not one per keystroke', async () => {
    // A federated search is N real requests against N third parties. Letting a
    // five-letter word fire five of those is how a portal starts rate-limiting
    // Curio.
    const { rerender } = render(<Probe q="b" />);
    for (const q of ['bi', 'bik', 'bike']) {
      act(() => {
        jest.advanceTimersByTime(80);
      });
      rerender(<Probe q={q} />);
    }
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch.mock.calls[0][0]).toContain('q=bike');
  });

  test('an empty federated query asks nothing at all', async () => {
    render(<Probe q="   " />);
    await settle();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  test('an empty SCOPED query is allowed, because a catalogue can be listed', async () => {
    render(<Probe q="" sourceDir="source.a.b@1" />);
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  test('a scoped search hits the source endpoint', async () => {
    render(<Probe q="bike" sourceDir="source.a.b@1" />);
    await settle();
    expect(apiFetch.mock.calls[0][0]).toContain('/sources/source.a.b%401/search');
  });

  test('a federated search hits the fan-out endpoint', async () => {
    render(<Probe q="bike" />);
    await settle();
    expect(apiFetch.mock.calls[0][0]).toContain('/api/discovery/search');
  });

  test('every request carries an abort signal', async () => {
    render(<Probe q="bike" />);
    await settle();
    expect(apiFetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  test('an abort is not reported as an error', async () => {
    // It is the expected outcome of the next keystroke, not a failure.
    const abort = Object.assign(new Error('aborted'), { name: 'AbortError' });
    apiFetch.mockRejectedValue(abort);
    render(<Probe q="bike" />);
    await settle();
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('count').textContent).toBe('0');
  });

  test('unmounting aborts the in-flight request', async () => {
    let captured: AbortSignal | undefined;
    apiFetch.mockImplementation((_p: string, o: RequestInit) => {
      captured = o.signal as AbortSignal;
      // Settles when aborted rather than never settling: a promise left
      // pending keeps a jest worker alive past teardown.
      return new Promise((_resolve, reject) => {
        captured!.addEventListener('abort', () =>
          reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
        );
      });
    });
    const { unmount } = render(<Probe q="bike" />);
    await settle();
    expect(captured!.aborted).toBe(false);
    unmount();
    expect(captured!.aborted).toBe(true);
    // Let the rejection land inside the test rather than after it.
    await act(async () => {});
  });

  test('a federated search asks again while a storage source is being scanned', async () => {
    const scanning = { ...EMPTY, sources: [{ sourceId: 'source.curio.example-storage', status: 'scanning' }] };
    const done = {
      ...EMPTY,
      resources: [{ sourceId: 'source.curio.example-storage', resourceId: 'noise', name: 'Noise recordings' }],
      sources: [{ sourceId: 'source.curio.example-storage', status: 'ok', count: 1 }],
    };
    apiFetch.mockResolvedValueOnce(scanning).mockResolvedValueOnce(done);
    render(<Probe q="noise" />);
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('count').textContent).toBe('0');
    // The first answer's rows are not held back while it waits.
    expect(screen.getByTestId('loading').textContent).toBe('false');
    await act(async () => {
      jest.advanceTimersByTime(1000);
    });
    await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('1'));
    expect(apiFetch).toHaveBeenCalledTimes(2);
    // Once every source has answered, it stops asking.
    await act(async () => {
      jest.advanceTimersByTime(5000);
    });
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });
});

function PagedProbe(props: { q: string; sourceDir?: string }) {
  const { data, loadMore, loadingMore } = useDiscoverySearch(props);
  return (
    <div>
      <span data-testid="ids">{data.resources.map((r) => r.resourceId).join(',')}</span>
      <span data-testid="next">{String(data.nextCursor)}</span>
      <span data-testid="more">{String(loadingMore)}</span>
      <button onClick={loadMore}>more</button>
    </div>
  );
}

const row = (resourceId: string) => ({ sourceId: 'source.a.b', resourceId, name: resourceId });

async function ids(expected: string) {
  await waitFor(() => expect(screen.getByTestId('ids').textContent).toBe(expected));
}

describe("useDiscoverySearch: a source's next page", () => {
  test('loadMore asks the source for the page after the rows shown, and adds its rows below', async () => {
    apiFetch
      .mockResolvedValueOnce({ ...EMPTY, resources: [row('a'), row('b')], nextCursor: '2', totalHint: 3 })
      .mockResolvedValueOnce({ ...EMPTY, resources: [row('c')], nextCursor: null, totalHint: 3 });
    render(<PagedProbe q="bike" sourceDir="source.a.b@1" />);
    await settle();
    await ids('a,b');

    await act(async () => {
      fireEvent.click(screen.getByText('more'));
    });
    await ids('a,b,c');
    expect(apiFetch).toHaveBeenCalledTimes(2);
    const next = apiFetch.mock.calls[1][0] as string;
    expect(next).toContain('/sources/source.a.b%401/search');
    expect(next).toContain('cursor=2');
    expect(next).toContain('q=bike');
    expect(screen.getByTestId('next').textContent).toBe('null');
    expect(screen.getByTestId('more').textContent).toBe('false');
  });

  test('a row the next page repeats is shown once', async () => {
    apiFetch
      .mockResolvedValueOnce({ ...EMPTY, resources: [row('a'), row('b')], nextCursor: '2' })
      .mockResolvedValueOnce({ ...EMPTY, resources: [row('b'), row('c')], nextCursor: null });
    render(<PagedProbe q="bike" sourceDir="source.a.b@1" />);
    await settle();
    await ids('a,b');
    await act(async () => {
      fireEvent.click(screen.getByText('more'));
    });
    await ids('a,b,c');
  });

  test('with no next page, loadMore asks nothing', async () => {
    apiFetch.mockResolvedValueOnce({ ...EMPTY, resources: [row('a')], nextCursor: null });
    render(<PagedProbe q="bike" sourceDir="source.a.b@1" />);
    await settle();
    await ids('a');
    fireEvent.click(screen.getByText('more'));
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  test('a search across sources asks for no next page', async () => {
    apiFetch.mockResolvedValueOnce({ ...EMPTY, resources: [row('a')], nextCursor: '20' });
    render(<PagedProbe q="bike" />);
    await settle();
    await ids('a');
    fireEvent.click(screen.getByText('more'));
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  test('a next page that lands after the query changed is dropped', async () => {
    let answerMore: (page: unknown) => void = () => undefined;
    apiFetch
      .mockResolvedValueOnce({ ...EMPTY, resources: [row('a')], nextCursor: '1' })
      .mockImplementationOnce(() => new Promise((resolve) => { answerMore = resolve; }))
      .mockResolvedValueOnce({ ...EMPTY, resources: [row('x')], nextCursor: null });
    const { rerender } = render(<PagedProbe q="bike" sourceDir="source.a.b@1" />);
    await settle();
    await ids('a');
    fireEvent.click(screen.getByText('more'));
    expect(screen.getByTestId('more').textContent).toBe('true');

    rerender(<PagedProbe q="bus" sourceDir="source.a.b@1" />);
    await settle();
    await ids('x');
    expect(screen.getByTestId('more').textContent).toBe('false');
    await act(async () => {
      answerMore({ ...EMPTY, resources: [row('b')], nextCursor: null });
    });
    expect(screen.getByTestId('ids').textContent).toBe('x');
  });
});
