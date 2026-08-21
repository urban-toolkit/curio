import React from "react";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import { shortenString } from "../../utils/parsing";
import { visiblePreviewColumns } from "../../utils/tabularPreview";

export interface TabularPreviewTableProps {
  rows: Record<string, unknown>[];
  rowKeyPrefix?: string;
  maxRows?: number;
  excludeColumns?: string[];
  loading?: boolean;
  loadingMessage?: string;
  emptyMessage?: string;
  className?: string;
}

function formatCell(value: unknown): string {
  if (value === undefined || value === null) {
    return "null";
  }
  return shortenString(String(value));
}

export const TabularPreviewTable: React.FC<TabularPreviewTableProps> = ({
  rows,
  rowKeyPrefix = "preview",
  maxRows = 100,
  excludeColumns = [],
  loading = false,
  loadingMessage = "Loading preview...",
  emptyMessage = "No rows to preview",
  className,
}) => {
  const displayRows = rows.slice(0, maxRows);
  const columns = visiblePreviewColumns(displayRows, excludeColumns);

  return (
    <div className={className}>
      {loading ? (
        <div style={{ padding: "10px", textAlign: "center", color: "#666" }}>
          {loadingMessage}
        </div>
      ) : null}
      <TableContainer component={Paper}>
        <Table aria-label="tabular preview">
          {columns.length > 0 ? (
            <TableHead>
              <TableRow>
                {columns.map((column, index) => (
                  <TableCell
                    key={`${rowKeyPrefix}_header_${column}`}
                    align="right"
                    style={{ fontWeight: "bold" }}
                  >
                    {column}
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
          ) : null}
          <TableBody>
            {displayRows.length === 0 && !loading ? (
              <TableRow>
                <TableCell colSpan={Math.max(columns.length, 1)} align="center">
                  {emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              displayRows.map((row, rowIndex) => (
                <TableRow
                  key={`${rowKeyPrefix}_row_${rowIndex}`}
                  sx={{ "&:last-child td, &:last-child th": { border: 0 } }}
                >
                  {columns.map((column, columnIndex) => (
                    <TableCell
                      key={`${rowKeyPrefix}_cell_${rowIndex}_${columnIndex}`}
                      align="right"
                    >
                      {formatCell(row[column])}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
};
