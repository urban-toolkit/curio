import React from 'react';
import { render, screen } from '@testing-library/react';
import DataPoolContent from '../../../../adapters/box/components/DataPoolContent';

jest.mock('../../../../utils/parsing', () => ({
  shortenString: (s: string) => s,
}));

describe('DataPoolContent', () => {
  const defaultProps = {
    activeTab: '0',
    onSelectTab: jest.fn(),
    tabData: [{ col: 1 }, { col: 2 }],
    tableData: [{ name: 'Alice' }],
  };

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
});
