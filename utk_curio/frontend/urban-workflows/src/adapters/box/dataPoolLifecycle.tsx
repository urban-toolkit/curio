import React, { useState, useEffect, useMemo } from 'react';
import { BoxLifecycleHook } from '../../registry/types';
import useTableData from '../../hook/useTableData';
import { ICodeData, ICodeDataContent } from '../../types';
import DataPoolContent from './components/DataPoolContent';

export const useDataPoolLifecycle: BoxLifecycleHook = (data, boxState) => {
  const [output, setOutput] = useState<ICodeData>({ code: '', content: '' });

  const {
    createTableData,
    parseOutputData,
    customWidgetsCallback,
    processDataAsync,
    activeTab,
    setActiveTab,
    tabData,
  } = useTableData({ data });

  useEffect(() => {
    let cancelled = false;
    const loadData = async () => {
      const result = await processDataAsync();
      if (!cancelled) setOutput(result as ICodeData);
    };
    loadData();
    return () => { cancelled = true; };
  }, [data.input, data.newPropagation]);

  useEffect(() => {
    if (output.content !== '' && data.interactions !== undefined) {
      const { newOutput, propagationObj } = parseOutputData({ output });
      const clonedOutput = JSON.parse(JSON.stringify(newOutput));
      setOutput({ code: 'success', content: clonedOutput });
      data.outputCallback(data.nodeId, clonedOutput);
      data.propagationCallback(propagationObj);
    }
  }, [data.interactions]);

  const displayTable = tabData[parseInt(activeTab)] || {};

  const tableData = useMemo(() => {
    if (displayTable && displayTable !== '' && displayTable !== '[]') {
      return createTableData(displayTable as ICodeDataContent);
    }
    return [];
  }, [displayTable, createTableData]);

  const contentComponent = (
    <DataPoolContent
      activeTab={activeTab}
      onSelectTab={setActiveTab}
      tabData={tabData}
      tableData={tableData}
    />
  );

  return {
    contentComponent,
    customWidgetsCallback,
    setOutputCallbackOverride: setOutput,
    setSendCodeCallbackOverride: () => {},
  };
}
