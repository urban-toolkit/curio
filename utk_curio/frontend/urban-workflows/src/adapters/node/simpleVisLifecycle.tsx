import React, { useCallback, useState, useEffect, useMemo, useRef } from 'react';
import { NodeLifecycleHook } from '../../registry/types';
import { NodeType, VisInteractionType } from '../../constants';
import { useProvenanceContext } from '../../providers/ProvenanceProvider';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchData } from '../../services/api';
import { formatDate, mapTypes } from '../../utils/formatters';
import { ICodeDataContent } from '../../types';
import ContentTable from './components/ContentTable';
import ImageGrid from './components/ImageGrid';

function buildTableRows(parsedOutput: ICodeDataContent): any[] {
  if (!parsedOutput || !parsedOutput.data) return [];
  if (parsedOutput.dataType === 'dataframe') {
    const columns = Object.keys(parsedOutput.data);
    if (columns.length === 0) return [];
    const indices = Object.keys(parsedOutput.data[columns[0]]);
    return indices.map((i) => {
      const row: any = {};
      for (const col of columns) row[col] = parsedOutput.data[col][i];
      return row;
    });
  }
  if (parsedOutput.dataType === 'geodataframe' && parsedOutput.data?.features?.length > 0) {
    const columns = Object.keys(parsedOutput.data.features[0].properties);
    return parsedOutput.data.features.map((f: any) => {
      const row: any = {};
      for (const col of columns) row[col] = f.properties[col];
      return row;
    });
  }
  return [];
}

type SimpleVisMode = 'table' | 'image' | 'text';

function toDisplayString(input: any): string {
  const value = input?.data !== undefined ? input.data : input;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function getMode(input: any): SimpleVisMode {
  const dt = input?.dataType;
  if (dt === 'dataframe' || dt === 'geodataframe') {
    if (input?.data?.image_id) return 'image';
    return 'table';
  }
  return 'text';
}

export const useSimpleVisLifecycle: NodeLifecycleHook = (data, nodeState) => {
  // Lazy init: if input is already present on mount (e.g. in tests) seed the
  // mode so the first render already produces a contentComponent. The effect
  // will overwrite this once it fetches any path reference.
  const [currentMode, setCurrentMode] = useState<SimpleVisMode>(() => getMode(data.input));
  const [outputTable, setOutputTable] = useState<any[]>([]);
  const [images, setImages] = useState<string[]>([]);
  const [interacted, setInteracted] = useState<string[]>([]);
  const [textContent, setTextContent] = useState<string>('');
  const [interactions, _setInteractions] = useState<any>({});
  const interactionsRef = useRef(interactions);
  const dataInputBypass = useRef(false);

  const setInteractions = (newData: any) => {
    interactionsRef.current = newData;
    _setInteractions(newData);
  };

  const { nodeExecProv } = useProvenanceContext();
  const { workflowNameRef } = useFlowContext();
  const { showToast } = useToastContext();

  useEffect(() => {
    const handleInput = async () => {
      const shouldProcess = dataInputBypass.current;
      dataInputBypass.current = true;
      if (!shouldProcess) return;
      if (data.input == null || data.input === '') return;

      const startTime = formatDate(new Date());
      const execId = NodeType.VIS_SIMPLE + '-' + data.nodeId;
      const typesInput = data.input.dataType ? [data.input.dataType] : [];

      let parsedInput = data.input;
      if (parsedInput.path) {
        try {
          parsedInput = await fetchData(parsedInput.path);
        } catch (err) {
          showToast('Error fetching data. Please try again.', 'error');
          return;
        }
      }

      nodeExecProv(startTime, startTime, workflowNameRef.current, execId, mapTypes(typesInput), mapTypes(typesInput), '');

      const mode = getMode(parsedInput);
      setCurrentMode(mode);

      if (mode === 'text') {
        setTextContent(toDisplayString(parsedInput));
      } else if (mode === 'image') {
        if (!parsedInput.data?.image_id || !parsedInput.data?.image_content) {
          showToast("Image needs a DataFrame with 'image_id' and 'image_content' columns.", 'error');
          return;
        }
        const newImages: string[] = [];
        const newInteracted: string[] = [];
        for (const key of Object.keys(parsedInput.data.image_content)) {
          const iterator: string[] = Array.isArray(parsedInput.data.image_content[key])
            ? [...parsedInput.data.image_content[key]]
            : [parsedInput.data.image_content[key]];
          for (const base64ImageContent of iterator) {
            newInteracted.push(parsedInput.data.interacted != undefined ? parsedInput.data.interacted[key] : '0');
            newImages.push('data:image/png;base64,' + base64ImageContent);
          }
        }
        setImages(newImages);
        setInteracted(newInteracted);
      } else if (mode === 'table') {
        setOutputTable(buildTableRows(parsedInput));
      }

      nodeState.setOutput({ code: 'success', content: parsedInput });
      data.outputCallback(data.nodeId, data.input);
    };

    handleInput();
  }, [data.input]);

  useEffect(() => {
    data.interactionsCallback(interactions, data.nodeId);
  }, [interactions]);

  const clickImage = useCallback((index: number) => {
    setInteractions({
      images_click: {
        type: VisInteractionType.POINT,
        data: [index],
        priority: 1,
        source: NodeType.VIS_SIMPLE,
      },
    });
  }, []);

  // Memoize so the JSX reference is stable across re-renders. NodeEditor
  // auto-switches to the "output" tab whenever `contentComponent` changes
  // identity — without this, any re-render (e.g. React Flow deselecting the
  // node on a pane click) would yank the user out of the code editor.
  const contentComponent = useMemo<React.ReactNode | undefined>(() => {
    if (currentMode === 'table') {
      return <ContentTable tableData={outputTable} nodeId={data.nodeId} />;
    }
    if (currentMode === 'image') {
      return (
        <ImageGrid
          nodeId={data.nodeId}
          images={images}
          interacted={interacted}
          onClickImage={clickImage}
        />
      );
    }
    if (currentMode === 'text' && textContent) {
      return (
        <pre style={{ margin: 0, padding: '8px', fontSize: '12px', overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {textContent}
        </pre>
      );
    }
    return undefined;
  }, [currentMode, outputTable, images, interacted, textContent, data.nodeId, clickImage]);

  return {
    contentComponent,
    setSendCodeCallbackOverride: (_: any) => {},
  };
};
