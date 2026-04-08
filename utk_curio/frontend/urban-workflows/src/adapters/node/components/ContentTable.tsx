import React, { memo, useMemo } from 'react';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Paper from '@mui/material/Paper';
import { shortenString } from '../../../utils/parsing';

interface ContentTableProps {
  tableData: Record<string, unknown>[];
  nodeId?: string;
}

const ContentTable = memo(({ tableData, nodeId = '' }: ContentTableProps) => {
  const columns = useMemo(() => {
    if (tableData.length === 0) return [];
    return Object.keys(tableData[0]);
  }, [tableData]);

  return (
    <div className="nowheel" style={{ overflowY: 'auto', height: '100%' }}>
      <TableContainer component={Paper}>
        <Table aria-label="simple table">
          {columns.length > 0 && (
            <TableHead>
              <TableRow>
                {columns.map((column, index) => (
                  <TableCell
                    style={{ fontWeight: 'bold' }}
                    key={`cell_header_${index}_${nodeId}`}
                    align="right"
                  >
                    {column}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
          )}

          <TableBody>
            {tableData.slice(0, 100).map((row, rowIndex) => (
              <TableRow
                key={`row_${rowIndex}_${nodeId}`}
                sx={{ '&:last-child td, &:last-child th': { border: 0 } }}
              >
                {columns.map((column, colIndex) => (
                  <TableCell key={`cell_${colIndex}_${rowIndex}_${nodeId}`} align="right">
                    {row[column] != null ? shortenString(String(row[column])) : 'null'}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
});

ContentTable.displayName = 'ContentTable';

export default ContentTable;
