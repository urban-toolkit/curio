import React, { useState, useEffect, useRef } from 'react';
import { NodeLifecycleHook } from '../../registry/types';
import { NodeType } from '../../constants';
import { useProvenanceContext } from '../../providers/ProvenanceProvider';
import { useFlowContext } from '../../providers/FlowProvider';
import { formatDate, getType, mapTypes } from '../../utils/formatters';
import useTableData from '../../hook/useTableData';
import { ICodeDataContent } from '../../types';
import ContentTable from './components/ContentTable';

export const useTableLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [outputTable, setOutputTable] = useState<any[]>([]);
  const dataInputBypass = useRef(false);

  const { nodeExecProv } = useProvenanceContext();
  const { workflowNameRef } = useFlowContext();

  useEffect(() => {
    if (dataInputBypass.current) {
      const startTime = formatDate(new Date());
      let typesInput: string[] = [];

      if (data.input != null && data.input !== '') {
        typesInput = getType([data.input]);
        nodeState.setOutput({ code: 'success', content: data.input! });
        data.outputCallback(data.nodeId, data.input);
      }

      const typesOutput: string[] = [...typesInput];

      nodeExecProv(
        startTime,
        startTime,
        workflowNameRef.current,
        NodeType.VIS_TABLE + '-' + data.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOutput),
        '',
      );
    }
    dataInputBypass.current = true;
  }, [data.input]);

  const { createTableData } = useTableData({ data });

  const createTable = (tableOutput: ICodeDataContent | string) => {
    if (tableOutput != '') {
      return createTableData(tableOutput as ICodeDataContent);
    }
    return [];
  };

  useEffect(() => {
    setOutputTable(createTable(nodeState.output.content));
  }, [nodeState.output]);

  const contentComponent = (
    <ContentTable tableData={outputTable} nodeId={data.nodeId} />
  );

  return {
    contentComponent,
    setSendCodeCallbackOverride: (_: any) => {},
  };
}
