import React from 'react';
import Tabs from 'react-bootstrap/Tabs';
import Tab from 'react-bootstrap/Tab';
import ContentTable from './ContentTable';

interface DataPoolContentProps {
  activeTab: string;
  onSelectTab: (tab: string) => void;
  tabData: any[];
  tableData: Record<string, unknown>[];
}

export default function DataPoolContent({ activeTab, onSelectTab, tabData, tableData }: DataPoolContentProps) {
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
            <ContentTable tableData={tableData} />
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
