import React, { useState, useEffect } from "react";
import Tabs from 'react-bootstrap/Tabs';
import Tab from 'react-bootstrap/Tab';
import { TabularPreviewTable } from '../../../components/tables/TabularPreviewTable';
import { fetchPreviewData } from '../../../services/api';
import { sandboxArtifactId } from '../../../utils/flowOutputRef';
import { rowsFromParseOutput } from '../../../utils/tabularPreview';

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
          style={{ overflowY: "auto", height: "100%" }}
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

export default function DataPoolContent({ activeTab, onSelectTab, tabData, tableData, data = { nodeId: '', input: '' } }: DataPoolContentProps) {
  const wrappers: any[] = (() => {
    if (!data.input || typeof data.input !== "object") return [];
    if (data.input.dataType === "outputs" && Array.isArray(data.input.data)) return data.input.data;
    return [data.input];
  })();

  return (
    <Tabs
      id="data-tabs"
      activeKey={activeTab}
      onSelect={(k) => onSelectTab(k || '0')}
      className="mb-3"
    >
      {Array.isArray(tabData) && tabData.length > 0 ? (
        tabData.map((_, index) => (
          <Tab eventKey={index.toString()} title={`Tab ${index + 1}`} key={index}>
            <ContentComponent outputTable={tableData} data={{ ...data, input: wrappers[index] ?? '' }} />
          </Tab>
        ))
      ) : (
        <Tab eventKey="0" title="No Data">
          <div style={{ padding: '10px', textAlign: 'center' }}>No data available.</div>
        </Tab>
      )}
    </Tabs>
  );
}
