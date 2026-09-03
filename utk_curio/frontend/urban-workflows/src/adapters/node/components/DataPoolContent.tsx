import React, { useState, useEffect } from "react";
import Nav from 'react-bootstrap/Nav';
import { TabularPreviewTable } from '../../../components/tables/TabularPreviewTable';
import { fetchPreviewData } from '../../../services/api';
import { sandboxArtifactId } from '../../../utils/flowOutputRef';
import { rowsFromParseOutput } from '../../../utils/tabularPreview';
import { NodeEmptyState } from '../../../components/nodes/NodeEmptyState';
import { resolveNodeEmptyReason } from '../../../utils/nodeEmptyState';

interface DataPoolContentProps {
  activeTab: string;
  onSelectTab: (tab: string) => void;
  tabData: any[];
  tableData: Record<string, unknown>[];
  data?: any;
  /**
   * Is anything wired into this pool's input?
   *
   * Only the behavior can see the graph, so it is passed down. Defaults to
   * FALSE, which is the honest reading when a caller has not said: an
   * unconnected pool is the commonest way to arrive at an empty body, and
   * claiming otherwise would send the user to run a node that does not exist.
   */
  connected?: boolean;
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
          const fileId = sandboxArtifactId(data.input);

          if (!fileId) {
              setPreviewTable([]);
              setUsePreview(false);
              return;
          }

          setIsLoadingPreview(true);
          try {
              const previewData = await fetchPreviewData(fileId);
              const nextPreviewTable = rowsFromParseOutput(previewData);

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
          data-curio-datapool-scroll="true"
          // overflow:'auto' is what makes this the scroll owner. The outer clamp
          // below is overflow:'hidden', so without it the rows are simply clipped
          // and the user has to resize the node to see them (#156).
          style={{ flex: 1, minHeight: 0, minWidth: 0, display: "flex", flexDirection: "column", overflow: "auto" }}
      >
          <TabularPreviewTable
              rows={displayTable}
              rowKeyPrefix={data.nodeId}
              loading={isLoadingPreview}
              excludeColumns={[]}
          />
      </div>
  );
};

export default function DataPoolContent({ activeTab, onSelectTab, tabData, tableData, data = { nodeId: '', input: '' }, connected = false }: DataPoolContentProps) {
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
        className="mb-3 nowheel"
        // nowrap + overflowX keeps the strip one row tall regardless of table
        // count, so adding tables never steals height from the table below.
        // `nowheel` stops React Flow swallowing the scroll (#156).
        style={{ flexShrink: 0, flexWrap: 'nowrap', overflowX: 'auto' }}
        data-testid="data-pool-tabs"
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
        ) : null}
      </Nav>
      <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {hasData ? (
          <ContentComponent
            key={activeIndex}
            outputTable={tableData}
            data={{ ...data, input: activeTabInput }}
          />
        ) : (
          // "No data available." was true but not useful: it named the state
          // and not the cause, so an unconnected pool and one whose upstream had
          // not run said the same thing (#224). The fake "No Data" TAB above it
          // is gone for the same reason — it looked like a tab you could open.
          <NodeEmptyState
            reason={
              resolveNodeEmptyReason({
                connected,
                hasInput: data?.input != null && data.input !== '',
                // A pool only ever renders tables, and ``tabData`` is empty in
                // this branch, so an input that got here produced nothing
                // table-shaped. That is "not tabular", not "no rows": a
                // dataframe with zero rows still yields a tab and renders as an
                // empty table above, so it never reaches here. Passing `true`
                // sent every such payload to "The input ran, but came back
                // empty", which is exactly the uninformative message #224 was
                // about.
                tabular: false,
                rowCount: 0,
              }) ?? 'no-rows'
            }
          />
        )}
      </div>
    </div>
  );
}
