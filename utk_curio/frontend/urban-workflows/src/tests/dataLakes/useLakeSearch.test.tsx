import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';

import { SEARCH_DEBOUNCE_MS, useLakeSearch } from '../../services/dataLakeCatalog';

jest.mock('../../utils/authApi', () => ({
  apiFetch: jest.fn(),
  getToken: jest.fn(() => 'token'),
}));
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { apiFetch } = require('../../utils/authApi') as { apiFetch: jest.Mock };

const EMPTY = { resources: [], sources: [], nextCursor: null, totalHint: null, truncated: false };

function Probe(props: { q: string; sourceDir?: string }) {
  const { data, loading, searched } = useLakeSearch(props);
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

describe('useLakeSearch', () => {
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
    render(<Probe q="" sourceDir="lake.a.b@1" />);
    await settle();
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  test('a scoped search hits the source endpoint', async () => {
    render(<Probe q="bike" sourceDir="lake.a.b@1" />);
    await settle();
    expect(apiFetch.mock.calls[0][0]).toContain('/sources/lake.a.b%401/search');
  });

  test('a federated search hits the fan-out endpoint', async () => {
    render(<Probe q="bike" />);
    await settle();
    expect(apiFetch.mock.calls[0][0]).toContain('/api/datalakes/search');
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
});
