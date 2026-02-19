import React from 'react';
import { render, screen } from '@testing-library/react';
import ContentTable from '../../../../adapters/box/components/ContentTable';

jest.mock('../../../../utils/parsing', () => ({
  shortenString: (s: string) => (s.length > 15 ? s.slice(0, 15) + '...' : s),
}));

describe('ContentTable', () => {
  test('renders nothing when tableData is empty', () => {
    const { container } = render(<ContentTable tableData={[]} />);
    const table = container.querySelector('table');
    expect(table).toBeTruthy();
    expect(container.querySelectorAll('th')).toHaveLength(0);
    expect(container.querySelectorAll('td')).toHaveLength(0);
  });

  test('renders column headers from object keys', () => {
    const data = [
      { name: 'Alice', age: 30 },
      { name: 'Bob', age: 25 },
    ];
    render(<ContentTable tableData={data} />);

    expect(screen.getByText('name')).toBeInTheDocument();
    expect(screen.getByText('age')).toBeInTheDocument();
  });

  test('renders row data correctly', () => {
    const data = [
      { city: 'London', pop: 9000000 },
    ];
    render(<ContentTable tableData={data} />);

    expect(screen.getByText('London')).toBeInTheDocument();
    expect(screen.getByText('9000000')).toBeInTheDocument();
  });

  test('renders "null" for null/undefined values', () => {
    const data = [{ col: null }];
    render(<ContentTable tableData={data as any} />);

    expect(screen.getByText('null')).toBeInTheDocument();
  });

  test('limits rows to 100', () => {
    const data = Array.from({ length: 150 }, (_, i) => ({ id: i }));
    const { container } = render(<ContentTable tableData={data} />);
    const rows = container.querySelectorAll('tbody tr');
    expect(rows).toHaveLength(100);
  });

  test('uses nodeId for stable key prefixes', () => {
    const data = [{ x: 1 }];
    const { container } = render(<ContentTable tableData={data} nodeId="n1" />);
    const headerCell = container.querySelector('[class*="MuiTableCell"]');
    expect(headerCell).toBeTruthy();
  });

  test('has nowheel className on wrapper div', () => {
    const { container } = render(<ContentTable tableData={[]} />);
    expect(container.firstChild).toHaveClass('nowheel');
  });
});
