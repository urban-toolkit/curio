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
