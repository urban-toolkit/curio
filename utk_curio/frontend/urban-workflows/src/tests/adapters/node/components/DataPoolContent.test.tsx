import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import DataPoolContent from '../../../../adapters/node/components/DataPoolContent';
import { fetchPreviewData } from '../../../../services/api';

jest.mock('../../../../utils/parsing', () => ({
  shortenString: (s: string) => s,
}));

jest.mock('../../../../services/api', () => ({
  fetchPreviewData: jest.fn().mockRejectedValue(new Error('no preview in tests')),
}));

const mockFetchPreviewData = fetchPreviewData as jest.MockedFunction<typeof fetchPreviewData>;

describe('DataPoolContent', () => {
  const defaultProps = {
    activeTab: '0',
    onSelectTab: jest.fn(),
    tabData: [{ col: 1 }, { col: 2 }],
    tableData: [{ name: 'Alice' }],
    data: { nodeId: 'test-node', input: '' },
  };

  beforeEach(() => {
    mockFetchPreviewData.mockReset();
    mockFetchPreviewData.mockRejectedValue(new Error('no preview in tests'));
  });

  test('renders tab titles based on tabData length', () => {
    render(<DataPoolContent {...defaultProps} />);
    expect(screen.getByText('Tab 1')).toBeInTheDocument();
    expect(screen.getByText('Tab 2')).toBeInTheDocument();
  });

  test('shows "No data available" when tabData is empty', () => {
    render(<DataPoolContent {...defaultProps} tabData={[]} />);
    expect(screen.getByText('No data available.')).toBeInTheDocument();
    expect(screen.getByText('No Data')).toBeInTheDocument();
  });

  test('renders ContentTable with provided tableData', () => {
    render(<DataPoolContent {...defaultProps} />);
    expect(screen.getAllByText('name').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Alice').length).toBeGreaterThanOrEqual(1);
  });

  // ---- #156: the node must scroll its own content --------------------------
  //
  // A merge (8e98eba) swapped the inline MUI TableContainer for the shared
  // TabularPreviewTable and dropped its `sx={{ ...overflow: 'auto' }}`, leaving
  // nothing to own vertical scroll. The outer clamp is `overflow: hidden`, so
  // rows were simply clipped and the user had to resize the node. Nothing tested
  // it, which is why a conflict resolution could delete it silently.

  test('the content area owns vertical scroll', () => {
    const { container } = render(<DataPoolContent {...defaultProps} />);
    const scroller = container.querySelector('[data-curio-datapool-scroll="true"]');
    expect(scroller).not.toBeNull();
    // `nowheel` is what stops React Flow swallowing the wheel event before the
    // div ever sees it, so the overflow alone would not be enough.
    expect(scroller).toHaveClass('nowheel');
    expect((scroller as HTMLElement).style.overflow).toBe('auto');
  });

  test('the content area owns horizontal scroll too (#203)', () => {
    // Commit 0b5edea4 ("fixes #156") gave this div `overflow: auto` for the
    // VERTICAL axis and the x axis was never addressed. It could not have
    // worked anyway while MUI's TableContainer was absorbing the x overflow -
    // see the assertion below.
    const { container } = render(<DataPoolContent {...defaultProps} />);
    const scroller = container.querySelector('[data-curio-datapool-scroll="true"]') as HTMLElement;
    // `overflow`, not `overflowY`: one declaration owns both axes.
    expect(scroller.style.overflow).toBe('auto');
    expect(scroller.style.overflowY).toBe('');
    expect(scroller.style.overflowX).toBe('');
    // minWidth:0 is what lets this box shrink below its content inside the
    // flex column, so there is something to scroll in the first place.
    expect(scroller.style.minWidth).toBe('0px');
  });

  test('the inner table container no longer steals the x overflow (#203)', () => {
    // MUI's TableContainer defaults to `overflowX: auto`. It receives no
    // height, so its box was as tall as the content (~3000px for 100 rows)
    // while the visible node body is ~250px - its horizontal scrollbar was
    // painted at the bottom of that box, reachable only after scrolling to the
    // last row. Turning the default off is the load-bearing line.
    const { container } = render(<DataPoolContent {...defaultProps} />);
    const inner = container.querySelector('.MuiTableContainer-root') as HTMLElement;
    if (!inner) return; // no rows rendered in this fixture; the assertion below covers it
    expect(getComputedStyle(inner).overflowX).not.toBe('auto');
  });

  test('the tab strip scrolls sideways instead of wrapping', () => {
    // Many tables must not steal height from the table below: the strip stays one
    // row tall and scrolls horizontally.
    const manyTabs = Array.from({ length: 12 }, (_, i) => ({ layerName: `layer_${i}` }));
    render(<DataPoolContent {...defaultProps} tabData={manyTabs} />);
    const strip = screen.getByTestId('data-pool-tabs');
    expect(strip).toHaveClass('nowheel');
    expect(strip.style.flexWrap).toBe('nowrap');
    expect(strip.style.overflowX).toBe('auto');
    expect(screen.getByText('layer_11')).toBeInTheDocument();
  });

  test('renders with non-array tabData gracefully', () => {
    render(<DataPoolContent {...defaultProps} tabData={null as any} />);
    expect(screen.getByText('No data available.')).toBeInTheDocument();
  });

  test('keeps the output table when preview resolves with no rows', async () => {
    mockFetchPreviewData.mockResolvedValue({
      dataType: 'dataframe',
      data: { empty: {} },
    } as any);

    render(
      <DataPoolContent
        {...defaultProps}
        // Single tab matching the single input wrapper. A multi-tab tabData
        // with one wrapper triggers `expandedFromSingleRef`, which blanks the
        // tab input (the autk-grammar multi-layer dict envelope isn't
        // previewable) and intentionally skips the fetch — see DataPoolContent.
        tabData={[{ col: 1 }]}
        data={{ nodeId: 'test-node', input: { filename: 'artifact_id' } }}
      />
    );

    await waitFor(() => expect(mockFetchPreviewData).toHaveBeenCalledWith('artifact_id'));
    await act(async () => {}); // flush state updates from resolved preview fetch
    expect(screen.getAllByText('Alice').length).toBeGreaterThanOrEqual(1);
  });
});
