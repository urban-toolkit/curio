/**
 * The hook `scripts/new_package.py --with-ui` writes, as package authors start
 * from it (#1333).
 *
 * The hook is read from the test package made with the scaffold,
 * `test_frontend/packages/test.ui-node@1`, as `noContentNodeDelete.test.ts`
 * reads a package's source: it is what people copy. It reads an output by its
 * reference with the host's `window.curio.fetchData`, and it hands on what it
 * makes as a stored output: `window.curio.storeOutput` keeps the rows, and the
 * reference it answers goes downstream. Rows handed on as they are reach a
 * chart but never a Python or JavaScript node, and no save records them.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { useUiNodeBehavior } = require(
  '../../../../../../../utk_curio/backend/tests/test_frontend/packages/test.ui-node@1/sources/uiNodeBehavior',
);

/** What `parseOutput(pd.DataFrame(...))` puts on the wire: each column an array. */
const FRAME = { dataType: 'dataframe', data: { population: [2746, 8804, 12], name: ['Andersonville', 'Loop', 'Tiny'] } };
const REF = { path: 'art-12', dataType: 'dataframe' };

async function renderNode(input: unknown) {
  const outputCallback = jest.fn();
  const setOutput = jest.fn();
  const Probe: React.FC = () => {
    const behavior = useUiNodeBehavior(
      { nodeId: 'ui-1', input, outputCallback },
      { output: { code: '', content: '' }, setOutput, templateData: {} },
    );
    return <>{behavior.contentComponent}</>;
  };
  await act(async () => {
    render(<Probe />);
  });
  return { outputCallback, setOutput };
}

const originalFetch = global.fetch;

beforeEach(() => {
  delete (window as any).curio;
  global.fetch = jest.fn(async () => ({ ok: false, status: 500, json: async () => ({}) })) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
  delete (window as any).curio;
});

test('it reads a reference through the host fetchData and lists the columns', async () => {
  const fetchData = jest.fn(async () => FRAME);
  (window as any).curio = { fetchData, storeOutput: jest.fn() };

  await renderNode(REF);

  await waitFor(() => expect(screen.queryByText(/Connect a DataFrame upstream/i)).not.toBeInTheDocument());
  expect(fetchData).toHaveBeenCalledWith('art-12');
  const select = screen.getByRole('combobox') as HTMLSelectElement;
  expect(Array.from(select.options).map((o) => o.value)).toEqual(['population', 'name']);
  expect(global.fetch).not.toHaveBeenCalled();
});

test('it stores the column it sends and hands on the reference the host answers', async () => {
  const storeOutput = jest.fn(async () => ({ path: 'art-kept', dataType: 'dataframe' }));
  (window as any).curio = { fetchData: jest.fn(async () => FRAME), storeOutput };
  const { outputCallback, setOutput } = await renderNode(REF);

  await waitFor(() => screen.getByRole('button', { name: 'Send this column downstream' }));
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send this column downstream' }));
  });

  expect(storeOutput).toHaveBeenCalledWith('ui-1', { data: { population: [2746, 8804, 12] }, dataType: 'dataframe' });
  expect(outputCallback).toHaveBeenCalledTimes(1);
  expect(outputCallback).toHaveBeenCalledWith('ui-1', { path: 'art-kept', dataType: 'dataframe' });
  expect(setOutput).toHaveBeenLastCalledWith({ code: 'success', content: '' });
});

test('on a host without storeOutput it posts the rows to /storeOutput itself', async () => {
  (window as any).curio = { fetchData: jest.fn(async () => FRAME) };
  global.fetch = jest.fn(async () => ({
    ok: true, status: 200, json: async () => ({ output: { path: 'art-posted', dataType: 'dataframe' } }),
  })) as unknown as typeof fetch;
  const { outputCallback } = await renderNode(REF);

  await waitFor(() => screen.getByRole('button', { name: 'Send this column downstream' }));
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send this column downstream' }));
  });

  const [url, init] = (global.fetch as unknown as jest.Mock).mock.calls[0];
  expect(String(url)).toMatch(/\/storeOutput$/);
  expect(JSON.parse(init.body)).toEqual({ value: { data: { population: [2746, 8804, 12] }, dataType: 'dataframe' } });
  expect(outputCallback).toHaveBeenCalledWith('ui-1', { path: 'art-posted', dataType: 'dataframe' });
});

test('a store that fails hands nothing on and says why', async () => {
  const storeOutput = jest.fn(async () => { throw new Error('Could not keep the output (HTTP 500)'); });
  (window as any).curio = { fetchData: jest.fn(async () => FRAME), storeOutput };
  const { outputCallback, setOutput } = await renderNode(REF);

  await waitFor(() => screen.getByRole('button', { name: 'Send this column downstream' }));
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send this column downstream' }));
  });

  expect(outputCallback).not.toHaveBeenCalled();
  expect(setOutput).toHaveBeenLastCalledWith({ code: 'error', content: 'Could not keep the output (HTTP 500)' });
});
