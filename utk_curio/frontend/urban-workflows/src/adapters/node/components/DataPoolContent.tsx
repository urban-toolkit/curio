import React, { useState, useEffect } from "react";
import FrameTabs from './FrameTabs';
import { TabularPreviewTable } from '../../../components/tables/TabularPreviewTable';
import { fetchPreviewData } from '../../../services/api';
import { sandboxArtifactId } from '../../../utils/flowOutputRef';
import { previewTotalRows, rowsFromParseOutput } from '../../../utils/tabularPreview';
import { NodeEmptyState } from '../../../components/nodes/NodeEmptyState';
import { isTabularPayload, resolveNodeEmptyReason } from '../../../utils/nodeEmptyState';
import { poolTabKind, RASTER_TAB_TITLE } from '../../../utils/poolTabs';
import { rasterBandsText, rasterCutText, rasterOf, rasterSizeText } from '../../../utils/raster/rasterDescription';
import { ResolutionType } from '../../../constants';
import nodeSettings from '../../../contracts/nodeSettings.json';

/** The words of each mode and of each select, which an agent's review card
 *  and the backend say them in too (contracts/nodeSettings.json). */
const MODE_LABELS: Record<string, string> = nodeSettings.dataPool.modes;
const SELECT_LABELS = nodeSettings.dataPool.settings;

/** One conflict mode: a label and a select over every ResolutionType. */
function ModeSelect({ label, value, onChange, testId }: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  testId: string;
}) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, margin: 0, whiteSpace: 'nowrap' }}>
      <span>{label}</span>
      <select
        aria-label={label}
        data-testid={testId}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        style={{ padding: '1px 4px', fontSize: 12 }}
      >
        {Object.values(ResolutionType).map((mode) => (
          <option key={mode} value={mode}>{MODE_LABELS[mode]}</option>
        ))}
      </select>
    </label>
  );
}

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
  /**
   * Did a node feeding this one run and fail?
   *
   * Same reasoning as ``connected``: only the behavior can see the graph and
   * the exec status. Defaults to FALSE so a caller that has not said is treated
   * as "no known failure" rather than blaming an upstream node at random.
   */
  upstreamErrored?: boolean;
  /** On a dashboard, is a viewer's run making the pool's rows? */
  upstreamRunning?: boolean;
  /** On a dashboard, why the viewer's run stopped before the pool, if it did. */
  upstreamStopped?: string | null;
  /** On a dashboard, how far the downloads on first use of the steps above the pool have come. */
  upstreamDownloads?: readonly string[];
  /** Are the rows of the input that just arrived still being read? */
  reading?: boolean;
  /** A dashboard's tile: an input not in yet is on its way, with no node to run. */
  onDashboard?: boolean;
  /** How the selects of one chart combine (a ResolutionType). */
  insideChartMode?: string;
  /** How the latest selections of the linked charts combine (a ResolutionType). */
  betweenChartsMode?: string;
  onInsideChartModeChange?: (mode: string) => void;
  onBetweenChartsModeChange?: (mode: string) => void;
}

const ContentComponent = ({
  outputTable,
  data,
}: {
  outputTable: any;
  data: any;
}) => {
  const [previewTable, setPreviewTable] = useState<any[]>([]);
  // The server previews the first 100 rows and says how many there are.
  const [previewTotal, setPreviewTotal] = useState<number | undefined>(undefined);
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
              setPreviewTotal(previewTotalRows(previewData));
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

  // Use preview data if available, otherwise fall back to outputTable. Either
  // way the table shows at most 100 rows and says how many there are.
  const showingPreview = usePreview && previewTable.length > 0;
  const displayTable = showingPreview ? previewTable : outputTable;
  const displayTotal = showingPreview ? previewTotal : outputTable?.length;

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
              totalRows={displayTotal}
              rowKeyPrefix={data.nodeId}
              loading={isLoadingPreview}
              excludeColumns={[]}
          />
      </div>
  );
};

export default function DataPoolContent({
  activeTab, onSelectTab, tabData, tableData, data = { nodeId: '', input: '' }, connected = false, upstreamErrored = false,
  upstreamRunning = false, upstreamStopped = null, upstreamDownloads, reading = false, onDashboard = false,
  insideChartMode = ResolutionType.OVERWRITE, betweenChartsMode = ResolutionType.OVERWRITE,
  onInsideChartModeChange, onBetweenChartsModeChange,
}: DataPoolContentProps) {
  const wrappers: any[] = (() => {
    if (!data.input || typeof data.input !== "object") return [];
    if (data.input.dataType === "outputs" && Array.isArray(data.input.data)) return data.input.data;
    return [data.input];
  })();

  // A tab is previewed from the server (its first 100 rows, `/get-preview`)
  // only when it is the one frame its input names: tabs map one to one to
  // the inputs, and its input is a frame's reference. Tabs a bundle expands
  // into (a tuple's, a list's, an Autark node's tables; see
  // useTableData.processDataAsync) are no input of their own: piped the input
  // at their place, a tab showed another input's rows, or a preview of the
  // whole bundle, which no table reads (an Autark node's one layer showed a
  // column "0" of blanks). They use outputTable, which already holds the
  // active tab's rows.
  const previewable = (input: any) => !!input && sandboxArtifactId(input) !== null
    && (input.dataType === undefined || input.dataType === 'dataframe' || input.dataType === 'geodataframe');

  // Render only the active tab's content directly instead of via Tab.Pane —
  // react-bootstrap's .tab-pane has display:none/block CSS that fights any
  // attempt to make it a flex child, which broke height propagation to the
  // inner scroll div. Manual rendering keeps a clean flex chain:
  // outer flex column → flex:1 content area → ContentComponent's overflow:auto.
  const hasData = Array.isArray(tabData) && tabData.length > 0;
  const activeIndex = parseInt(activeTab) || 0;
  const activeTabInput = hasData && wrappers.length === tabData.length && previewable(wrappers[activeIndex])
    ? wrappers[activeIndex]
    : '';
  // A raster's tab says it is one, and a value's that it is not tabular: they
  // have no rows to read or show. A raster's tab then says what it is, in the
  // words a chip's hover says it in, from what the pool holds of it: an Autark
  // raster's envelope, or what the sandbox read of a Python one beside its
  // file. A raster the pool holds by its reference alone is not read for it.
  const activeKind = hasData ? poolTabKind(tabData[activeIndex]) : 'table';
  const activeRaster = activeKind === 'raster' ? rasterOf(tabData[activeIndex]) : null;
  const rasterLines = activeRaster
    ? [rasterSizeText(activeRaster), rasterBandsText(activeRaster), rasterCutText(activeRaster)]
      .filter((line): line is string => !!line)
    : [];

  return (
    // overflow:hidden + height:100% pin this component to the parent's box, so
    // only the inner scroll engages — without this clamp, the outer NodeEditor
    // Tab.Pane (overflowY:auto) would scroll the whole node including the tab strip.
    // paddingBottom keeps the table's horizontal scrollbar clear of the play
    // button and NodeEditor's bottom tab nav (both occupy ~25px below NodeEditor's
    // outer div via marginTop:-25px / overflow:visible).
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0, minWidth: 0, paddingBottom: 25 }}>
      {/* How the selections that reach the pool combine (#581). nodrag/nopan
          so React Flow leaves the selects to the pointer. */}
      <div
        className="nodrag nopan nowheel"
        data-testid="data-pool-modes"
        style={{ flexShrink: 0, display: 'flex', flexWrap: 'wrap', columnGap: 12, rowGap: 4, marginBottom: 6, fontSize: 12 }}
      >
        <ModeSelect
          label={SELECT_LABELS.insideChart}
          value={insideChartMode}
          onChange={onInsideChartModeChange}
          testId="data-pool-mode-inside"
        />
        <ModeSelect
          label={SELECT_LABELS.betweenCharts}
          value={betweenChartsMode}
          onChange={onBetweenChartsModeChange}
          testId="data-pool-mode-between"
        />
      </div>
      <FrameTabs
        tabs={hasData ? tabData : []}
        activeKey={activeTab}
        onSelect={onSelectTab}
        testId="data-pool-tabs"
      />
      <div style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {hasData && activeKind === 'raster' ? (
          <NodeEmptyState reason="not-tabular" title={RASTER_TAB_TITLE} hint="" lines={rasterLines} />
        ) : hasData && activeKind === 'value' ? (
          <NodeEmptyState reason="not-tabular" />
        ) : hasData ? (
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
          (() => {
            const reason = resolveNodeEmptyReason({
              connected,
              upstreamErrored,
              upstreamRunning,
              upstreamStopped,
              hasInput: data?.input != null && data.input !== '',
              reading,
              onDashboard,
              // Asked of the PAYLOAD, not of tabData (#347). The premise this
              // used to state - that a zero-row dataframe still yields a tab
              // and so never reaches here - is not true: processDataAsync
              // filters dataframe/geodataframe layers with no rows out before
              // tabData is set (autk-db cannot load an empty layer). So a
              // node that ran and returned an empty table landed here and was
              // told "This input is not tabular data", which is wrong and
              // unactionable. The declared dataType still knows better.
              tabular: isTabularPayload(data?.input),
              rowCount: 0,
            }) ?? 'no-rows';
            return (
              <NodeEmptyState
                reason={reason}
                hint={reason === 'upstream-stopped' ? upstreamStopped ?? undefined : undefined}
                progress={reason === 'upstream-running' ? upstreamDownloads : undefined}
              />
            );
          })()
        )}
      </div>
    </div>
  );
}
