/**
 * The Column Filter example node reads a real Curio DataFrame (#194).
 *
 * Not a port mismatch, not host plumbing, not connection validation. The
 * package assumed the wrong DataFrame shape: `asFrame` required each column to
 * be a **row map** and explicitly rejected arrays, while Curio's sandbox
 * serialises with `to_dict(orient='list')` - so each column IS an array.
 * `asFrame` returned null for every real DataFrame, `setFrame(null)` ran, and
 * the node rendered "Connect a DataFrame upstream and run that node." forever,
 * with nothing thrown and nothing in the console to go on.
 *
 * The behaviour is imported from `packages/` rather than `src/`, the pattern
 * `noContentNodeDelete.test.ts` established: this is the reference example for
 * authoring custom-UI nodes, and its source is what people copy.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { useColumnFilterBehavior } = require(
  '../../../../../../../packages/curio.example-ui@1/sources/columnFilterBehavior',
);

/** Exactly what `parseOutput(pd.DataFrame(...))` puts on the wire: each column
 *  an array, the row index implied by position. */
const SANDBOX_FRAME = {
  dataType: 'dataframe',
  data: {
    population: [2746, 8804, 12],
    name: ['Andersonville', 'Loop', 'Tiny'],
  },
};

/** The other encoding a hand-written spec or a bare `to_dict()` produces. */
const ROW_MAP_FRAME = {
  dataType: 'dataframe',
  data: {
    population: { '0': 2746, '1': 8804, '2': 12 },
    name: { '0': 'Andersonville', '1': 'Loop', '2': 'Tiny' },
  },
};

interface Rendered {
  outputCallback: jest.Mock;
  setOutput: jest.Mock;
}

async function renderNode(payload: unknown): Promise<Rendered> {
  const outputCallback = jest.fn();
  const setOutput = jest.fn();

  const Probe: React.FC = () => {
    const behavior = useColumnFilterBehavior(
      {
        nodeId: 'cf-1',
        // Passed inline rather than as a {path} ref, so no fetch is involved.
        input: payload,
        outputCallback,
      },
      { output: { code: '', content: '' }, setOutput, templateData: {} },
    );
    return <>{behavior.contentComponent}</>;
  };

  await act(async () => {
    render(<Probe />);
  });
  return { outputCallback, setOutput };
}

describe('Column Filter with the shape Curio actually sends', () => {
  test('renders its column picker, not the connect-upstream hint', async () => {
    await renderNode(SANDBOX_FRAME);

    // The reported symptom, and the thing that must not come back.
    await waitFor(() => {
      expect(
        screen.queryByText(/Connect a DataFrame upstream/i),
      ).not.toBeInTheDocument();
    });

    const select = screen.getAllByRole('combobox')[0] as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    // Only the numeric column is worth thresholding.
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toContain('population');
    expect(options).not.toContain('name');
  });

  test('counts the matching rows', async () => {
    await renderNode(SANDBOX_FRAME);

    await waitFor(() => {
      // Threshold defaults to 0 with ">", so all three rows match.
      expect(screen.getByText(/3 of 3 rows match/i)).toBeInTheDocument();
    });
  });

  test('emits a column-array payload, preserving the input encoding', async () => {
    const { outputCallback } = await renderNode(SANDBOX_FRAME);

    await waitFor(() => screen.getByRole('button'));
    const threshold = screen.getByDisplayValue('0');
    fireEvent.change(threshold, { target: { value: '1000' } });

    await waitFor(() => {
      expect(screen.getByText(/2 of 3 rows match/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button'));

    expect(outputCallback).toHaveBeenCalledTimes(1);
    const [, payload] = outputCallback.mock.calls[0];
    expect(payload.dataType).toBe('dataframe');
    // Arrays in, arrays out - the downstream payload stays byte-compatible
    // with what the sandbox produced.
    expect(Array.isArray(payload.data.population)).toBe(true);
    expect(payload.data.population).toEqual([2746, 8804]);
    expect(payload.data.name).toEqual(['Andersonville', 'Loop']);
  });
});

describe('Column Filter with the legacy row-map shape', () => {
  test('still works, so hand-written specs are not broken', async () => {
    await renderNode(ROW_MAP_FRAME);

    await waitFor(() => {
      expect(
        screen.queryByText(/Connect a DataFrame upstream/i),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText(/3 of 3 rows match/i)).toBeInTheDocument();
  });

  test('emits a row map when it was given one', async () => {
    const { outputCallback } = await renderNode(ROW_MAP_FRAME);

    await waitFor(() => screen.getByRole('button'));
    fireEvent.change(screen.getByDisplayValue('0'), { target: { value: '1000' } });
    await waitFor(() => {
      expect(screen.getByText(/2 of 3 rows match/i)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('button'));

    const [, payload] = outputCallback.mock.calls[0];
    expect(Array.isArray(payload.data.population)).toBe(false);
    expect(payload.data.population).toEqual({ '0': 2746, '1': 8804 });
  });
});

describe('Column Filter with a shape it genuinely cannot read', () => {
  test('a row-oriented list is still refused', async () => {
    // The frame itself being an array means row-oriented records, which this
    // node does not support - that reject is deliberate and stays.
    await renderNode({
      dataType: 'dataframe',
      data: [{ population: 2746 }, { population: 8804 }],
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Connect a DataFrame upstream/i),
      ).toBeInTheDocument();
    });
  });
});
