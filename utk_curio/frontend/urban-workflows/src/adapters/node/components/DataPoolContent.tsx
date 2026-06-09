import React, { useState, useEffect } from "react";
import Nav from 'react-bootstrap/Nav';
// mui
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Paper from "@mui/material/Paper";
import { shortenString } from '../../../utils/parsing';
import { fetchPreviewData } from '../../../services/api';

interface DataPoolContentProps {
  activeTab: string;
  onSelectTab: (tab: string) => void;
  tabData: any[];
  tableData: Record<string, unknown>[];
  data?: any;
}

const ContentComponent = ({
  outputTable,
  data,
}: {
  outputTable: any;
  data: any;
}) => {
  const [previewTable, setPreviewTable] = useState<any[]>([]);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [usePreview, setUsePreview] = useState(false);

  // When outputTable changes (e.g. from an interaction), override the stale
  // server preview so the live interacted data is always shown.
  useEffect(() => {
    if (!outputTable || outputTable.length === 0) return;
    setUsePreview(false);
    setIsLoadingPreview(false);
  }, [outputTable]);

  useEffect(() => {
      let cancelled = false;

      const loadPreviewData = async () => {
          const fileId = data.input && typeof data.input === "object"
              ? (data.input.filename ?? data.input.path)
              : null;

          if (!fileId) {
              setPreviewTable([]);
              setUsePreview(false);
              return;
          }

          setIsLoadingPreview(true);
          try {
              const previewData = await fetchPreviewData(fileId);

              let nextPreviewTable: any[] = [];
              if (previewData.dataType === "dataframe" && previewData.data) {
                  const columns = Object.keys(previewData.data);
                  const firstColumn = columns[0];
                  const indices = firstColumn ? Object.keys(previewData.data[firstColumn] ?? {}) : [];
                  nextPreviewTable = indices.map((idx) => {
                      const row: any = {};
                      columns.forEach((col) => { row[col] = previewData.data[col][idx]; });
                      return row;
                  });
              } else if (previewData.dataType === "geodataframe" && previewData.data?.features) {
                  nextPreviewTable = previewData.data.features.map((feature: any) => ({ ...feature.properties }));
              }

              if (cancelled) return;

              setPreviewTable(nextPreviewTable);
              // Keep the already-rendered output table when preview returns
              // no rows or resolves after the input has moved on.
              setUsePreview(nextPreviewTable.length > 0);
          } catch (error) {
              if (cancelled) return;
              console.log("[ContentComponent] Preview fetch failed, falling back to outputTable:", error);
              setUsePreview(false);
          } finally {
              if (!cancelled) {
                  setIsLoadingPreview(false);
              }
          }
      };

      loadPreviewData();

      return () => {
          cancelled = true;
      };
  }, [data.input]);

  // Use preview data if available, otherwise fall back to outputTable
  const displayTable = usePreview && previewTable.length > 0 ? previewTable : outputTable;

  return (
      <div
          className="nowheel"
          style={{ flex: 1, minHeight: 0, minWidth: 0, display: "flex", flexDirection: "column" }}
      >
          {isLoadingPreview && (
              <div style={{ padding: "10px", textAlign: "center", color: "#666" }}>
                  Loading preview...
              </div>
          )}
          {/* Scroll on the TableContainer (not the outer div) so the horizontal
              scrollbar sits at the table's own bottom edge — otherwise it ends
              up at the bottom of the scroll viewport and is only reachable
              after scrolling all the way down. */}
          <TableContainer
              component={Paper}
              sx={{ flex: 1, minHeight: 0, minWidth: 0, overflow: "auto" }}
          >
              <Table aria-label="simple table">
                  {displayTable.length > 0 ? (
                      <TableHead>
                          <TableRow>
                              {Object.keys(displayTable[0]).map(
                                  (column, index) => {
                                      return (
                                          <TableCell
                                              style={{
                                                  fontWeight: "bold",
                                              }}
                                              key={
                                                  "cell_header_" +
                                                  index +
                                                  "_" +
                                                  data.nodeId
                                              }
                                              align="right"
                                          >
                                              {column}
                                          </TableCell>
                                      );
                                  }
                              )}
                          </TableRow>
                      </TableHead>
                  ) : null}

                  <TableBody>
                      {displayTable
                          .slice(0, 100)
                          .map((row: any, index: any) => {
                              return (
                                  <TableRow
                                      key={"row_" + index + data.nodeId}
                                      sx={{
                                          "&:last-child td, &:last-child th":
                                              { border: 0 },
                                      }}
                                  >
                                      {Object.keys(row).map(
                                          (column, columnIndex) => {
                                              return (
                                                  <TableCell
                                                      key={
                                                          "cell_" +
                                                          columnIndex +
                                                          "_" +
                                                          index +
                                                          "_" +
                                                          data.nodeId
                                                      }
                                                      align="right"
                                                  >
                                                      {row[column] !=
                                                          undefined &&
                                                      row[column] != null
                                                          ? shortenString(
                                                                row[
                                                                    column
                                                                ].toString()
                                                            )
                                                          : "null"}
                                                  </TableCell>
                                              );
                                          }
                                      )}
                                  </TableRow>
                              );
                          })}
                  </TableBody>
              </Table>
          </TableContainer>
      </div>
  );
};

export default function DataPoolContent({ activeTab, onSelectTab, tabData, tableData, data = { nodeId: '', input: '' } }: DataPoolContentProps) {
  const wrappers: any[] = (() => {
    if (!data.input || typeof data.input !== "object") return [];
    if (data.input.dataType === "outputs" && Array.isArray(data.input.data)) return data.input.data;
    return [data.input];
  })();

  // Tabs derived from expanding a single artifact (autk-grammar's multi-layer
  // wrapper persists as one `dict`-kind ref whose payload is an `outputs`
  // envelope — see useTableData.processDataAsync) have no 1:1 wrapper ref:
  // wrappers.length === 1 but tabData.length === N. Don't pipe wrappers[0]
  // into tab 0 in that case — its preview fetch round-trips the whole
  // multi-MB outputs payload only to fall back to outputTable (the artifact's
  // dataType is `dict`, which has no previewable shape), so tab 0 lags while
  // every other tab is instant. Force-empty input on all tabs makes them
  // uniformly use outputTable, which already holds the active layer's data.
  const expandedFromSingleRef = wrappers.length === 1 && tabData.length > 1;

  // Render only the active tab's content directly instead of via Tab.Pane —
  // react-bootstrap's .tab-pane has display:none/block CSS that fights any
  // attempt to make it a flex child, which broke height propagation to the
  // inner scroll div. Manual rendering keeps a clean flex chain:
  // outer flex column → flex:1 content area → ContentComponent's overflow:auto.
  const hasData = Array.isArray(tabData) && tabData.length > 0;
  const activeIndex = parseInt(activeTab) || 0;
  const activeTabInput = hasData && !expandedFromSingleRef ? (wrappers[activeIndex] ?? '') : '';

  return (
    // overflow:hidden + height:100% pin this component to the parent's box, so
    // only the inner scroll engages — without this clamp, the outer NodeEditor
    // Tab.Pane (overflowY:auto) would scroll the whole node including the tab strip.
    // paddingBottom keeps the table's horizontal scrollbar clear of the play
    // button and NodeEditor's bottom tab nav (both occupy ~25px below NodeEditor's
    // outer div via marginTop:-25px / overflow:visible).
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, minWidth: 0, paddingBottom: 25 }}>
      <Nav
        variant="tabs"
        activeKey={activeTab}
        onSelect={(k) => onSelectTab(k || '0')}
        className="mb-3"
        style={{ flexShrink: 0 }}
      >
        {hasData ? (
          tabData.map((entry, index) => {
            const title = entry && typeof entry === 'object' && entry.layerName
              ? String(entry.layerName)
              : `Tab ${index + 1}`;
            return (
              <Nav.Item key={index}>
                <Nav.Link eventKey={index.toString()}>{title}</Nav.Link>
              </Nav.Item>
            );
          })
        ) : (
          <Nav.Item>
            <Nav.Link eventKey="0">No Data</Nav.Link>
          </Nav.Item>
        )}
      </Nav>
      <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {hasData ? (
          <ContentComponent
            key={activeIndex}
            outputTable={tableData}
            data={{ ...data, input: activeTabInput }}
          />
        ) : (
          <div style={{ padding: '10px', textAlign: 'center' }}>No data available.</div>
        )}
      </div>
    </div>
  );
}
