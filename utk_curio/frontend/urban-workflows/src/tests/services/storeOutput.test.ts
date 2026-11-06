/**
 * `storeOutput` keeps rows a node made in the browser as an output (#1333).
 *
 * A node that hands on rows as they are reaches a chart, which reads them in
 * the browser, but never a Python or JavaScript node, whose run reads only a
 * stored output, and no save records them. `storeOutput` asks the backend to
 * keep them (`/storeOutput`) and answers the reference to hand on instead. A
 * dashboard viewer's run that asked the page for the node keeps them for that
 * page (`keepPageResult`), as an Autark node's layers are. Packages get it as
 * `window.curio.storeOutput`.
 */
const mockAsked = { node: '' };
const mockKeepPageResult = jest.fn();
jest.mock('../../services/runs/dashboardRunSteps', () => ({
  askedOfPage: (nodeId: string) => nodeId === mockAsked.node,
  keepPageResult: (...args: unknown[]) => mockKeepPageResult(...args),
}));
jest.mock('../../utils/authApi', () => ({ getToken: () => 'the-token' }));
jest.mock('../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));

import { storeOutput } from '../../services/api';

const ROWS = { dataType: 'geodataframe' as const, data: { type: 'FeatureCollection', features: [] } };

function answer(status: number, body: unknown) {
  const fetchMock = jest.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });
  (global as any).fetch = fetchMock;
  return fetchMock;
}

beforeEach(() => {
  mockAsked.node = '';
  jest.clearAllMocks();
});

test('the rows go to /storeOutput with the sign-in, and the reference comes back', async () => {
  const fetchMock = answer(200, { output: { path: 'art-joined', dataType: 'geodataframe' } });

  await expect(storeOutput('sj-1', ROWS)).resolves.toEqual({ path: 'art-joined', dataType: 'geodataframe' });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe('http://backend.test/storeOutput');
  expect(init.method).toBe('POST');
  expect(init.headers.Authorization).toBe('Bearer the-token');
  expect(JSON.parse(init.body)).toEqual({ value: ROWS });
  expect(mockKeepPageResult).not.toHaveBeenCalled();
});

test('a refusal is an error that carries its reason', async () => {
  answer(400, { error: 'The output must be an object whose dataType is dataframe or geodataframe.' });

  await expect(storeOutput('sj-1', ROWS)).rejects.toThrow(
    'The output must be an object whose dataType is dataframe or geodataframe.',
  );
});

test('an answer with no reference is an error too', async () => {
  answer(500, {});

  await expect(storeOutput('sj-1', ROWS)).rejects.toThrow('Could not keep the output (HTTP 500)');
});

test("a viewer's run that asked the page for the node keeps the rows for that page", async () => {
  const fetchMock = answer(200, {});
  mockAsked.node = 'sj-1';
  mockKeepPageResult.mockResolvedValue({ path: 'kept-art', dataType: 'geodataframe' });

  await expect(storeOutput('sj-1', ROWS)).resolves.toEqual({ path: 'kept-art', dataType: 'geodataframe' });

  expect(mockKeepPageResult).toHaveBeenCalledWith('sj-1', ROWS);
  expect(fetchMock).not.toHaveBeenCalled();
});
