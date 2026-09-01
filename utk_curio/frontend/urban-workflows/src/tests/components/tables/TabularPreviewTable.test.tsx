/**
 * The shared preview table lets its columns overflow (#203).
 *
 * No test file existed for this component at all, which matters because it has
 * three consumers: the Data Pool node (`DataPoolContent`), and the two dataset
 * previews (`DatasetBundlePreview`, `DatasetTablePreview`). The two defects
 * here were the same in every one of them.
 *
 * 1. MUI's `TableContainer` defaults to `overflowX: auto`. It is given no
 *    height, so its box is as tall as its content (up to 100 rows, ~3000px)
 *    while the visible node body is ~250px — its horizontal scrollbar was
 *    painted at the bottom of that 3000px box, reachable only after scrolling
 *    to the last row. It also *absorbed* the x overflow, so the node's own
 *    scroller never got a scrollbar of its own.
 * 2. Nothing set a min-width on `<Table>`. MUI's `width: 100%` with
 *    `table-layout: auto`, plus `shortenString` truncating cells to 15 chars,
 *    means the browser squeezes every column toward min-content instead of
 *    overflowing — the crushed columns in the report.
 */
import React from 'react';
import { render } from '@testing-library/react';
import { TabularPreviewTable } from '../../../components/tables/TabularPreviewTable';

jest.mock('../../../utils/parsing', () => ({
  shortenString: (s: string) => s,
}));

/** A frame wide enough that the browser would otherwise crush the columns. */
function wideRows(columnCount = 30, rowCount = 3) {
  return Array.from({ length: rowCount }, (_, r) => {
    const row: Record<string, unknown> = {};
    for (let c = 0; c < columnCount; c += 1) {
      row[`column_number_${c}`] = `value ${r}-${c}`;
    }
    return row;
  });
}

function renderTable(rows: Record<string, unknown>[] = wideRows()) {
  return render(<TabularPreviewTable rows={rows} rowKeyPrefix="t" />);
}

describe('TabularPreviewTable overflow ownership', () => {
  test('the table declares a max-content min-width, so it overflows', () => {
    const { container } = renderTable();
    const table = container.querySelector('table') as HTMLElement;

    expect(table).not.toBeNull();
    // Without this the columns are squeezed toward min-content rather than
    // overflowing, and no scrollbar ever appears on any ancestor.
    expect(getComputedStyle(table).minWidth).toBe('max-content');
  });

  test('the MUI container no longer claims the x overflow for itself', () => {
    const { container } = renderTable();
    const mui = container.querySelector('.MuiTableContainer-root') as HTMLElement;

    expect(mui).not.toBeNull();
    // `visible`, so the overflow passes through to the consumer's own
    // scroller — the Data Pool's `overflow: auto` div, which is sized to the
    // visible node body rather than to the full height of the rows.
    expect(getComputedStyle(mui).overflowX).toBe('visible');
  });

  test('the wrapper can shrink inside a flex parent', () => {
    // A flex item refuses to go below its content size without these, so the
    // ancestor scroller would have nothing to scroll.
    const { container } = renderTable();
    const wrapper = container.firstElementChild as HTMLElement;

    expect(wrapper.style.display).toBe('flex');
    expect(wrapper.style.flexDirection).toBe('column');
    expect(wrapper.style.minHeight).toBe('0px');
    expect(wrapper.style.minWidth).toBe('0px');
  });
});

describe('TabularPreviewTable still renders its content', () => {
  test('every column gets a header', () => {
    const { container } = renderTable(wideRows(30, 2));
    expect(container.querySelectorAll('thead th')).toHaveLength(30);
  });

  test('rows are capped by maxRows', () => {
    const { container } = render(
      <TabularPreviewTable rows={wideRows(3, 50)} rowKeyPrefix="t" maxRows={10} />,
    );
    expect(container.querySelectorAll('tbody tr')).toHaveLength(10);
  });

  test('an empty frame renders no headers and does not throw', () => {
    const { container } = render(<TabularPreviewTable rows={[]} rowKeyPrefix="t" />);
    expect(container.querySelectorAll('thead th')).toHaveLength(0);
  });

  test('the loading message shows while loading', () => {
    const { getByText } = render(
      <TabularPreviewTable
        rows={[]}
        rowKeyPrefix="t"
        loading
        loadingMessage="Loading preview…"
      />,
    );
    expect(getByText('Loading preview…')).toBeInTheDocument();
  });
});
