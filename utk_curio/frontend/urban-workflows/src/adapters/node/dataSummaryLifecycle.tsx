import React, { useState, useEffect, useMemo } from 'react';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Paper from '@mui/material/Paper';
import { NodeLifecycleHook } from '../../registry/types';
import OutputContent from '../../components/editing/OutputContent';
import { fetchData } from '../../services/api';

// ── Sub-components ─────────────────────────────────────────────────────────

function DescribeTable({ describe, nodeId }: { describe: Record<string, Record<string, any>>; nodeId: string }) {
  const columns = Object.keys(describe);
  if (columns.length === 0) return null;

  const stats = Object.keys(describe[columns[0]]);

  return (
    <TableContainer component={Paper} style={{ marginTop: '4px' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell style={{ fontWeight: 'bold', padding: '4px 8px' }}>Stat</TableCell>
            {columns.map((col, i) => (
              <TableCell key={`dh_${i}_${nodeId}`} style={{ fontWeight: 'bold', padding: '4px 8px' }}>
                {col}
              </TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {stats.map((stat, i) => (
            <TableRow key={`ds_${i}_${nodeId}`}>
              <TableCell style={{ padding: '4px 8px', fontWeight: 'bold', color: '#555' }}>{stat}</TableCell>
              {columns.map((col, j) => {
                const val = describe[col][stat];
                const display =
                  val === '' || val === null || val === undefined
                    ? '—'
                    : typeof val === 'number'
                    ? val.toFixed(4)
                    : String(val);
                return (
                  <TableCell key={`dv_${i}_${j}_${nodeId}`} style={{ padding: '4px 8px' }}>
                    {display}
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function SummaryContent({ summary, nodeId }: { summary: any; nodeId: string }) {
  const cellStyle = { padding: '4px 8px' };
  const headerStyle = { fontWeight: 'bold', padding: '4px 8px' };
  const hasMissing = summary.missing && Object.values(summary.missing).some((v) => Number(v) > 0);

  return (
    <div className="nowheel" style={{ overflowY: 'auto', height: '100%', padding: '8px', fontSize: '12px' }}>

      {/* Shape */}
      {summary.shape && (
        <div style={{ marginBottom: '12px' }}>
          <strong>Shape</strong>
          <div style={{ color: '#555', marginTop: '4px' }}>
            {summary.shape.rows} rows × {summary.shape.columns} columns
          </div>
        </div>
      )}

      {/* Data types */}
      {summary.dtypes && (
        <div style={{ marginBottom: '12px' }}>
          <strong>Data Types</strong>
          <TableContainer component={Paper} style={{ marginTop: '4px' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell style={headerStyle}>Column</TableCell>
                  <TableCell style={headerStyle}>Type</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {Object.entries(summary.dtypes).map(([col, dtype], i) => (
                  <TableRow key={`dtype_${i}_${nodeId}`}>
                    <TableCell style={cellStyle}>{col}</TableCell>
                    <TableCell style={{ ...cellStyle, color: '#666' }}>{String(dtype)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}

      {/* Missing values — only shown when at least one column has missing data */}
      {hasMissing && (
        <div style={{ marginBottom: '12px' }}>
          <strong>Missing Values</strong>
          <TableContainer component={Paper} style={{ marginTop: '4px' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell style={headerStyle}>Column</TableCell>
                  <TableCell style={headerStyle}>Missing</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {Object.entries(summary.missing)
                  .filter(([, count]) => Number(count) > 0)
                  .map(([col, count], i) => (
                    <TableRow key={`missing_${i}_${nodeId}`}>
                      <TableCell style={cellStyle}>{col}</TableCell>
                      <TableCell style={{ ...cellStyle, color: '#c0392b' }}>{String(count)}</TableCell>
                    </TableRow>
                  ))}
              </TableBody>
            </Table>
          </TableContainer>
        </div>
      )}

      {/* Descriptive statistics */}
      {summary.describe && (
        <div style={{ marginBottom: '12px' }}>
          <strong>Descriptive Statistics</strong>
          <DescribeTable describe={summary.describe} nodeId={nodeId} />
        </div>
      )}

    </div>
  );
}

// ── Default code ───────────────────────────────────────────────────────────

const DEFAULT_CODE = `import pandas as pd

df = arg  # Getting DataFrame from previous node

summary = {
    "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
    "dtypes": df.dtypes.astype(str).to_dict(),
    "missing": df.isnull().sum().to_dict(),
    "describe": df.describe(include="all").fillna("").to_dict(),
}

return summary
`;

// ── Lifecycle hook ─────────────────────────────────────────────────────────

export const useDataSummaryLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [summaryData, setSummaryData] = useState<any>(null);

  // Pre-populate the editor on first drop; respect code already saved in the workflow.
  const defaultValueOverride = data.defaultCode ? undefined : DEFAULT_CODE;

  // After each successful execution, fetch the output file and render it as a summary table.
  // Watching nodeState.output avoids overriding setOutputCallback (which causes render loops).
  useEffect(() => {
    if (nodeState.output.code === 'success') {
      const match = typeof nodeState.output.content === 'string' ? nodeState.output.content.match(/Saved to file: (.+)/) : null;
      if (match) {
        fetchData(match[1].trim())
          .then((result: any) => setSummaryData(result?.data ?? result))
          .catch(() => setSummaryData(null));
      }
    } else {
      setSummaryData(null);
    }
  }, [nodeState.output]);

  // Memoize so the JSX reference is stable across re-renders. NodeEditor
  // auto-switches to the "output" tab whenever `contentComponent` changes
  // identity — without this, any re-render (e.g. React Flow deselecting the
  // node on a pane click) would yank the user out of the code editor.
  const contentComponent = useMemo(
    () =>
      summaryData ? (
        <SummaryContent summary={summaryData} nodeId={data.nodeId} />
      ) : (
        <OutputContent output={nodeState.output} />
      ),
    [summaryData, data.nodeId, nodeState.output],
  );

  return { contentComponent, defaultValueOverride };
};
