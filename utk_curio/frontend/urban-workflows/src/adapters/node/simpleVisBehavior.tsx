import React, { useCallback, useState, useEffect, useMemo, useRef } from 'react';
import { useEdges } from 'reactflow';
import { NodeBehaviorHook } from '../../registry/types';
import { NodeEmptyState } from '../../components/nodes/NodeEmptyState';
import { hasIncomingEdge, resolveNodeEmptyReason } from '../../utils/nodeEmptyState';
import { NodeType, VisInteractionType } from '../../constants';
import { useProvenanceContext } from '../../providers/ProvenanceProvider';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchData } from '../../services/api';
import { formatDate, mapTypes } from '../../utils/formatters';
import { ICodeDataContent } from '../../types';
import { resolveImageColumns } from '../../utils/imageColumns';
import ContentTable from './components/ContentTable';
import ImageCardGrid from './components/ImageCardGrid';

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

/** Sentinel for "show every image column", the default. */
export const ALL_IMAGE_COLUMNS = 'all';

function toDisplayString(input: any): string {
  const value = input?.data !== undefined ? input.data : input;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isFrame(input: any): boolean {
  const dt = input?.dataType;
  return dt === 'dataframe' || dt === 'geodataframe';
}

/** The node's persisted image-column choice; see the picker below. */
export function resolveImageColumnChoice(data: any): string {
  const raw = data?.simpleVis?.imageColumn;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  return trimmed || ALL_IMAGE_COLUMNS;
}

/**
 * What to render, derived once from a resolved payload.
 *
 * Rows come first and the mode follows from them. That ordering is the fix for
 * #276: the previous check read `input.data.image_id`, a DataFrame *column
 * map*, so a GeoDataFrame, whose columns live under `features[i].properties`,
 * could never be images however it was shaped, and a column of image URLs had
 * no path at all. `buildTableRows` already flattened both shapes; now one
 * answer serves the table, the images and the interaction flags alike.
 */
function deriveView(parsedInput: any): {
  mode: SimpleVisMode;
  rows: any[];
  imageColumns: string[];
  textContent: string;
} {
  const rows = isFrame(parsedInput) ? buildTableRows(parsedInput) : [];
  const imageColumns = resolveImageColumns(rows);
  if (imageColumns.length > 0) return { mode: 'image', rows, imageColumns, textContent: '' };
  if (isFrame(parsedInput)) return { mode: 'table', rows, imageColumns: [], textContent: '' };
  return { mode: 'text', rows: [], imageColumns: [], textContent: toDisplayString(parsedInput) };
}

export const useSimpleVisBehavior: NodeBehaviorHook = (data, nodeState) => {
  // Which of the empty states this is depends on whether anything is wired in,
  // which only the graph knows. Same read as mergeFlowBehavior.
  const edges = useEdges();
  const connected = hasIncomingEdge(edges, data.nodeId);
  // Lazy init: if input is already present on mount (e.g. in tests) seed the
  // view so the first render already produces a contentComponent. The effect
  // will overwrite this once it fetches any path reference.
  const initial = useMemo(() => deriveView(data.input), []);
  const [currentMode, setCurrentMode] = useState<SimpleVisMode>(initial.mode);
  const [rows, setRows] = useState<any[]>(initial.rows);
  const [imageColumns, setImageColumns] = useState<string[]>(initial.imageColumns);
  const [textContent, setTextContent] = useState<string>(initial.textContent);
  const [interactions, _setInteractions] = useState<any>({});
  const interactionsRef = useRef(interactions);
  const dataInputBypass = useRef(false);

  const setInteractions = (newData: any) => {
    interactionsRef.current = newData;
    _setInteractions(newData);
  };

  const { nodeExecProv } = useProvenanceContext();
  const { workflowNameRef, updateDataNode } = useFlowContext();
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

      const view = deriveView(parsedInput);
      setCurrentMode(view.mode);
      setRows(view.rows);
      setImageColumns(view.imageColumns);
      setTextContent(view.textContent);

      nodeState.setOutput({ code: 'success', content: parsedInput });
      if (typeof data.outputCallback === 'function') {
        data.outputCallback(data.nodeId, data.input);
      }
    };

    handleInput();
  }, [data.input]);

  useEffect(() => {
    if (typeof data.interactionsCallback === 'function') {
      data.interactionsCallback(interactions, data.nodeId);
    }
  }, [interactions]);

  // A card is a row, so the index sent downstream is the row index. It used to
  // be the position in a flattened image list, which only matched when every
  // cell held exactly one image.
  const clickRow = useCallback((rowIndex: number) => {
    setInteractions({
      images_click: {
        type: VisInteractionType.POINT,
        data: [rowIndex],
        priority: 1,
        source: NodeType.VIS_SIMPLE,
      },
    });
  }, []);

  // Written back by a linked Data Pool, onto the row itself for both frame
  // shapes, so this no longer has to know which shape it came from.
  const interacted = useMemo(
    () => rows.map((row) => (row?.interacted === '1' ? '1' : '0')),
    [rows],
  );

  const choice = resolveImageColumnChoice(data);
  const shownImageColumns = useMemo(() => {
    if (choice === ALL_IMAGE_COLUMNS) return imageColumns;
    const pinned = imageColumns.filter((c) => c === choice);
    // A pinned column the current frame does not carry falls back to all,
    // rather than rendering an empty node and blaming the data.
    return pinned.length > 0 ? pinned : imageColumns;
  }, [choice, imageColumns]);

  const pickColumn = useCallback(
    (value: string) => {
      updateDataNode(data.nodeId, {
        ...data,
        simpleVis: { ...(data as any).simpleVis, imageColumn: value },
      });
    },
    [data, updateDataNode],
  );

  // Memoize so the JSX reference is stable across re-renders. NodeEditor
  // auto-switches to the "output" tab whenever `contentComponent` changes
  // identity — without this, any re-render (e.g. React Flow deselecting the
  // node on a pane click) would yank the user out of the code editor.
  const contentComponent = useMemo<React.ReactNode | undefined>(() => {
    if (currentMode === 'table' && rows.length > 0) {
      return <ContentTable tableData={rows} nodeId={data.nodeId} />;
    }
    if (currentMode === 'image' && rows.length > 0 && shownImageColumns.length > 0) {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {imageColumns.length > 1 && (
            <label
              className="nodrag"
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', fontSize: 11 }}
            >
              <span>Image column</span>
              <select
                aria-label="Image column"
                data-curio-image-column="true"
                value={choice}
                onChange={(e) => pickColumn(e.target.value)}
                style={{ fontSize: 11 }}
              >
                <option value={ALL_IMAGE_COLUMNS}>all</option>
                {imageColumns.map((column) => (
                  <option key={column} value={column}>{column}</option>
                ))}
              </select>
            </label>
          )}
          <div style={{ flex: 1, minHeight: 0 }}>
            <ImageCardGrid
              nodeId={data.nodeId}
              rows={rows}
              imageColumns={shownImageColumns}
              interacted={interacted}
              onClickRow={clickRow}
            />
          </div>
        </div>
      );
    }
    if (currentMode === 'text' && textContent) {
      return (
        <pre style={{ margin: 0, padding: '8px', fontSize: '12px', overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {textContent}
        </pre>
      );
    }
    // Every branch above now requires actual content, so this is reached
    // whenever there is none — where it used to return `undefined` and
    // UniversalNode rendered nothing at all (#224). `ContentTable` with an
    // empty array was the same defect wearing a table: it drew an empty
    // <Table> and looked like a node that had failed.
    return (
      <NodeEmptyState
        reason={
          resolveNodeEmptyReason({
            connected,
            hasInput: data.input != null && data.input !== '',
            // 'text' is the fallback mode for anything that is not a frame,
            // so a text mode with no content is a payload we cannot show.
            tabular: currentMode !== 'text',
            rowCount: rows.length,
          }) ?? 'not-tabular'
        }
      />
    );
  }, [currentMode, rows, imageColumns, shownImageColumns, choice, interacted, textContent, data.nodeId, data.input, connected, clickRow, pickColumn]);

  return {
    contentComponent,
    setSendCodeCallbackOverride: (_: any) => {},
  };
};
