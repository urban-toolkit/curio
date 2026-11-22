import React, { useCallback, useState, useEffect, useMemo, useRef } from 'react';
import { useEdges } from 'reactflow';
import { NodeBehaviorHook } from '../../registry/types';
import { NodeEmptyState } from '../../components/nodes/NodeEmptyState';
import { hasIncomingEdge, resolveNodeEmptyReason } from '../../utils/nodeEmptyState';
import { useGrammarInputState } from '../../hook/useGrammarInputState';
import { NodeType, VisInteractionType } from '../../constants';
import { useProvenanceContext } from '../../providers/ProvenanceProvider';
import { useFlowContext } from '../../providers/FlowProvider';
import { useAgentsDataflowId } from '../../providers/agents/useAgentsDataflowId';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchData } from '../../services/api';
import { formatDate, mapTypes } from '../../utils/formatters';
import { ICodeDataContent } from '../../types';
import { resolveImageColumns } from '../../utils/imageColumns';
import ContentTable from './components/ContentTable';
import { CopyButton } from '../../components/CopyButton';
import ImageCardGrid from './components/ImageCardGrid';
import FrameTabs from './components/FrameTabs';
import { toRows } from '../../utils/rowSource';
import { keyedFramesAsOutputs, unwrapValueEnvelopes } from '../../utils/sandboxEnvelope';
import {
  registerNodeSettingWriter,
  registerNodeWidgetWriter,
  withDeclaredWidgetValues,
} from '../../utils/nodeSettingsWriters';
import nodeSettings from '../../contracts/nodeSettings.json';
import type { SelectDetail } from '../../utils/selectionMatch';
import {
  CARD_SELECT,
  PLAYER_SELECT,
  TIME_COLUMN_WIDGET,
  latestSelect,
  playedRange,
  playerSelect,
  timeColumnOf,
} from '../../utils/playerSelection';
import { tryGetNodeDescriptor } from '../../registry/nodeRegistry';
import { normalizeWidgets, type WidgetDef } from '../../utils/widgets/widgetModel';
import { SimpleViewTimeColumn } from './SimpleViewTimeColumn';

/** The widgets Simple View's own controls draw: its Time column, set from
 *  its Widgets tab, has no row of the editor's (NodeEditor's `ownWidgets`). */
const OWN_WIDGETS = [TIME_COLUMN_WIDGET];

/** The picker's label, and its word for every image column, which an agent's
 *  review card and the backend say the setting in too
 *  (contracts/nodeSettings.json). */
const IMAGE_COLUMN_LABEL = nodeSettings.simpleVis.settings.imageColumn;
const ALL_IMAGE_COLUMNS_WORD = nodeSettings.simpleVis.all;

function buildTableRows(parsedOutput: ICodeDataContent): any[] {
  // Was a fourth copy of the same column-major flatten; see utils/rowSource.
  return toRows(parsedOutput as any);
}

type SimpleVisMode = 'table' | 'image' | 'text';

/** Sentinel for "show every image column", the default. */
export const ALL_IMAGE_COLUMNS = 'all';

function toDisplayString(input: any): string {
  // The payload's own envelope, whatever its type, then the ones the sandbox
  // puts around each element of a list (#516).
  const value = unwrapValueEnvelopes(input?.data !== undefined ? input.data : input);
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

/** A reference to an artifact whose content the view has not read yet. */
function isUnread(input: any): boolean {
  return typeof input?.path === 'string' && input.path !== '' && !('data' in input);
}

/**
 * The frames of a dict of frames, as a node returns one (`{"videos": ...,
 * "tracks": ...}`), each a tab named after its key, as a Data Pool shows them
 * (hook/useTableData); null for any other input, a JSON dict among them,
 * which shows as its text.
 */
function frameTabs(parsedInput: any): any[] | null {
  if (parsedInput?.dataType !== 'dict') return null;
  return keyedFramesAsOutputs(parsedInput.data)?.data ?? null;
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
  // Nothing wired in yet, or an upstream that has not run. There is no payload
  // to describe, so every branch stays empty and the caller falls through to
  // the empty state that says which of those it is (#224). Without this guard a
  // freshly dropped node has `input === ''`, whose JSON is the two-character
  // string `""`, which is truthy and renders as a text payload.
  if (parsedInput == null || parsedInput === '') {
    return { mode: 'text', rows: [], imageColumns: [], textContent: '' };
  }
  const rows = isFrame(parsedInput) ? buildTableRows(parsedInput) : [];
  const imageColumns = resolveImageColumns(rows);
  if (imageColumns.length > 0) return { mode: 'image', rows, imageColumns, textContent: '' };
  if (isFrame(parsedInput)) return { mode: 'table', rows, imageColumns: [], textContent: '' };
  // A reference the view reads before it shows it, of anything but a table
  // (a dict of frames a node returns, say), is no text: until its read ends,
  // the body says its input is on its way.
  if (isUnread(parsedInput)) return { mode: 'text', rows: [], imageColumns: [], textContent: '' };
  return { mode: 'text', rows: [], imageColumns: [], textContent: toDisplayString(parsedInput) };
}

/**
 * What to render of an input: a dict of frames as its tabs, the one at
 * *open* shown (the first when it has no tab there), and any other input as
 * itself, with no tabs.
 */
function deriveInput(parsedInput: any, open: number) {
  const tabs = frameTabs(parsedInput);
  const shown = tabs && open < tabs.length ? open : 0;
  return { tabs, open: shown, ...deriveView(tabs ? tabs[shown] : parsedInput) };
}

export const useSimpleVisBehavior: NodeBehaviorHook = (data, nodeState) => {
  // Which of the empty states this is depends on whether anything is wired in,
  // which only the graph knows.
  const edges = useEdges();
  const connected = hasIncomingEdge(edges, data.nodeId);
  // Whether the node feeding it ran and failed, asked as the Data Pool asks it
  // (#347); on a dashboard, a viewer's run making the rows, or why it stopped
  // before them, and how far the downloads of the steps above have come.
  const { upstreamErrored, upstreamRunning, upstreamStopped, upstreamDownloads, onDashboard } = useGrammarInputState(data.nodeId);
  // A fresh list each render: the content below changes with what it says.
  const downloadsSaid = upstreamDownloads.join("\n");
  // Lazy init: if input is already present on mount seed the view so the
  // first render already produces a contentComponent. One that carries its
  // rows shows at once, a dict of frames as its tabs; the effect reads one
  // that names its artifact.
  const initial = useMemo(() => deriveInput(data.input, 0), []);
  const [currentMode, setCurrentMode] = useState<SimpleVisMode>(initial.mode);
  const [rows, setRows] = useState<any[]>(initial.rows);
  const [imageColumns, setImageColumns] = useState<string[]>(initial.imageColumns);
  const [textContent, setTextContent] = useState<string>(initial.textContent);
  // A dict of frames' tabs, and the open one, whose frame the view shows.
  const [tabs, setTabs] = useState<any[] | null>(initial.tabs);
  const [openTab, setOpenTab] = useState<number>(initial.open);
  const tabsRef = useRef<any[] | null>(initial.tabs);
  const openTabRef = useRef<number>(initial.open);
  const [interactions, setInteractions] = useState<Record<string, SelectDetail>>({});
  const interactionsRef = useRef(interactions);
  const dataInputBypass = useRef(false);
  // While the rows of the input that just arrived are read (a fetch of its
  // path): the body says what it shows is coming, not that the input is not a
  // table. Told in the render that brings the input, not an effect after it:
  // an input is read once the read of it, the latest, has ended. The one the
  // node mounted with is read already when its first view above holds its
  // rows; one that names its artifact is read as a later one is.
  const [readInput, setReadInput] = useState<unknown>(() => (data.input?.path ? null : data.input));
  const latestInputRef = useRef<unknown>(data.input);
  const reading = data.input != null && data.input !== '' && data.input !== readInput;

  // A select of this view made the latest of its selects (utils/playerSelection),
  // which the flow sends over its interaction edges: a click on a card, or
  // what a card's player has played.
  const tellSelect = useCallback((name: string, select: SelectDetail) => {
    const next = latestSelect(interactionsRef.current, name, select);
    interactionsRef.current = next;
    setInteractions(next);
  }, []);

  const { nodeExecProv } = useProvenanceContext();
  const { workflowNameRef, updateDataNode } = useFlowContext();
  // The node's data as it is now, which the writes and the player's tell below
  // read: through a ref, so they keep their identity, and so does the view's
  // body, whatever the node's data becomes.
  const dataRef = useRef(data);
  dataRef.current = data;
  // The dataflow the cards read a collection's files through, as the canvas's
  // Data Catalog lists them (`useAgentsDataflowId`): on an invited editor's
  // canvas, the owner's, whose collections the editor's runs load.
  const dataflowId = useAgentsDataflowId();
  const { showToast } = useToastContext();
  // The read of the input that arrived last, until it ends: what a run that
  // asks the view waits for (`untilHandedOn`, below).
  const readingRef = useRef<Promise<void> | null>(null);

  /** Shows one frame, or a value, as derived (`deriveView`). */
  const show = useCallback((view: ReturnType<typeof deriveView>) => {
    setCurrentMode(view.mode);
    setRows(view.rows);
    setImageColumns(view.imageColumns);
    setTextContent(view.textContent);
  }, []);

  /** Opens the tab at *open* of *frames*, a dict of frames' tabs, or none. */
  const openTabOf = useCallback((frames: any[] | null, open: number) => {
    tabsRef.current = frames;
    openTabRef.current = open;
    setTabs(frames);
    setOpenTab(open);
  }, []);

  // A click on a tab shows its frame as the view shows any frame. A player
  // that plays in the tab it leaves closes, which takes its range away.
  const selectTab = useCallback((key: string) => {
    const frames = tabsRef.current;
    const index = Number(key);
    if (!frames || !Number.isInteger(index) || index < 0 || index >= frames.length) return;
    openTabOf(frames, index);
    show(deriveView(frames[index]));
  }, [openTabOf, show]);

  useEffect(() => {
    const handleInput = async () => {
      // The input the node mounted with is read too: it can reach the node
      // before the node mounts, as a dashboard's saved output reaches a tile,
      // and its first view above cannot read a path. It is no new run, so it
      // is filed in no provenance and sent no further, as a later input is.
      const arrived = dataInputBypass.current;
      dataInputBypass.current = true;
      if (data.input == null || data.input === '') return;

      const input = data.input;
      latestInputRef.current = input;
      try {
        const startTime = formatDate(new Date());
        const typesInput = input.dataType ? [input.dataType] : [];

        let parsedInput = input;
        if (parsedInput.path) {
          try {
            parsedInput = await fetchData(parsedInput.path);
          } catch (err) {
            showToast('Error fetching data. Please try again.', 'error');
            return;
          }
        }

        if (arrived) {
          nodeExecProv(startTime, startTime, workflowNameRef.current, data.nodeId, mapTypes(typesInput), mapTypes(typesInput), '');
        }

        // A dict of frames keeps the tab open at its place, as a Data
        // Pool's tabs do, when the new input has one there.
        const view = deriveInput(parsedInput, openTabRef.current);
        openTabOf(view.tabs, view.open);
        show(view);

        // Downstream first, then the outcome: the outcome is what tells a Run All
        // this node is done, and the nodes it feeds must have the rows by then.
        if (arrived && typeof data.outputCallback === 'function') {
          data.outputCallback(data.nodeId, input);
        }
        nodeState.setOutput({ code: 'success', content: parsedInput });
      } finally {
        // A failed read ends it too: the body then says what it has.
        if (latestInputRef.current === input) setReadInput(input);
      }
    };

    readingRef.current = handleInput();
  }, [data.input]);

  // The view has no Play, so a run that asks it waits for this instead: its
  // rows on their way to the nodes it feeds. A run on the server ends with the
  // step that makes the view's input, and the page asks the view in the render
  // that brings it. Counted done then, the run asked the Spatial Join below
  // before the rows landed, and the join had no input_0 to join.
  const untilHandedOn = useCallback(async () => {
    // A newer input that arrived meanwhile is read before the run goes on.
    while (readingRef.current) {
      const read = readingRef.current;
      try {
        await read;
      } catch {
        // A read that failed hands nothing on: nothing is left to wait for.
      }
      if (readingRef.current === read) readingRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (typeof data.interactionsCallback === 'function') {
      data.interactionsCallback(interactions, data.nodeId);
    }
  }, [interactions]);

  // A card is a row, so the index sent downstream is the row index. It used to
  // be the position in a flattened image list, which only matched when every
  // cell held exactly one image.
  const clickRow = useCallback((rowIndex: number) => {
    tellSelect(CARD_SELECT, {
      type: VisInteractionType.POINT,
      data: [rowIndex],
      source: NodeType.VIS_SIMPLE,
    } as SelectDetail);
  }, [tellSelect]);

  // The column the player's range names in the views linked to this one: its
  // Time column, t_s until set (utils/playerSelection).
  const timeColumn = timeColumnOf((data as any).widgets);

  // What a card's player has played, from its file's start to where it
  // stands, as an interval on the Time column; one that holds nothing once it
  // closes. A selection this view receives moves no player. The column is
  // read from the node's data as it tells, so a new value changes no
  // callback the view's body holds: NodeEditor would take a new body for a
  // new run and leave the Widgets tab the value was set on.
  const played = useCallback((row: Record<string, unknown>, at: number | null) => {
    const column = timeColumnOf((dataRef.current as any).widgets);
    tellSelect(PLAYER_SELECT, playerSelect(at === null ? null : playedRange(row, at), column));
  }, [tellSelect]);

  // A Time column set while a player holds a range moves the range to it at
  // once, at the priority it holds: the linked views light their rows by the
  // new column without waiting for the player to tell its time again.
  useEffect(() => {
    const held = interactionsRef.current[PLAYER_SELECT];
    const [column] = Object.keys(held?.data ?? {});
    if (!held || column === undefined || column === timeColumn) return;
    const next = { ...interactionsRef.current, [PLAYER_SELECT]: { ...held, data: { [timeColumn]: held.data[column] } } };
    interactionsRef.current = next;
    setInteractions(next);
  }, [timeColumn]);

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

  // All clears the setting: the node shows every image column, as one that
  // never picked a column does. A dataflow saved before keeps the word "all",
  // which the node still reads as every column.
  const pickColumn = useCallback(
    (value: string) => {
      const current = dataRef.current as any;
      const simpleVis = { ...current.simpleVis };
      if (value === ALL_IMAGE_COLUMNS) delete simpleVis.imageColumn;
      else simpleVis.imageColumn = value;
      updateDataNode(current.nodeId, { ...current, simpleVis });
    },
    [updateDataNode],
  );

  // The Time column's widget: the node's own, else its template's, for a node
  // that holds none yet (one saved before it had the setting), which names t_s.
  const heldTimeWidget = normalizeWidgets((data as any).widgets).find((widget) => widget.name === TIME_COLUMN_WIDGET);
  const timeWidget: WidgetDef | undefined = heldTimeWidget
    ?? (tryGetNodeDescriptor((data as any).nodeType)?.widgets ?? []).find((widget) => widget.name === TIME_COLUMN_WIDGET);
  const timeWidgetRef = useRef(timeWidget);
  timeWidgetRef.current = timeWidget;

  // A Time column set on the Widgets tab is the node's, as a pick of its image
  // column is: kept in its widgets, saved with it, and run by nothing, since
  // it changes no rows the view hands on. A node with no widget of it yet
  // takes its template's, with the value set.
  const setTimeColumn = useCallback(
    (value: string) => {
      const current = dataRef.current as any;
      const template = timeWidgetRef.current ? [timeWidgetRef.current] : [];
      const next = withDeclaredWidgetValues(normalizeWidgets(current.widgets), { [TIME_COLUMN_WIDGET]: value }, template);
      updateDataNode(current.nodeId, { ...current, widgets: next });
    },
    [updateDataNode],
  );
  // An agent's applied change sets the Time column as the field does
  // (utils/nodeSettingsWriters): the same write, which runs nothing.
  const setTimeColumnRef = useRef(setTimeColumn);
  setTimeColumnRef.current = setTimeColumn;
  useEffect(
    () => registerNodeWidgetWriter(data.nodeId, TIME_COLUMN_WIDGET, (value) =>
      setTimeColumnRef.current(typeof value === 'string' ? value : '')),
    [data.nodeId],
  );

  // The Time column's field, the node's own control: on its Widgets tab, and
  // on its dashboard tile, read-only there as every text widget is.
  const timeWidgetKey = JSON.stringify(timeWidget ?? null);
  const controlsComponent = useMemo<React.ReactNode | undefined>(
    () => (timeWidget
      ? <SimpleViewTimeColumn widget={timeWidget} onCommit={setTimeColumn} dashboard={onDashboard} />
      : undefined),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [timeWidgetKey, setTimeColumn, onDashboard],
  );

  // An agent's applied change picks the column as the picker does
  // (utils/nodeSettingsWriters); one that names no column picks All.
  const pickColumnRef = useRef(pickColumn);
  pickColumnRef.current = pickColumn;
  useEffect(
    () => registerNodeSettingWriter(data.nodeId, 'simpleVis', (setting) =>
      pickColumnRef.current(setting.imageColumn || ALL_IMAGE_COLUMNS)),
    [data.nodeId],
  );

  // Memoize so the JSX reference is stable across re-renders. NodeEditor
  // auto-switches to the "output" tab whenever `contentComponent` changes
  // identity — without this, any re-render (e.g. React Flow deselecting the
  // node on a pane click) would yank the user out of the code editor.
  const contentComponent = useMemo<React.ReactNode | undefined>(() => {
    // A dict of frames: a tab per frame, as a Data Pool's, above the open
    // tab's frame, shown as the view shows any frame.
    const inTabs = (body: React.ReactNode) => (tabs ? (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <FrameTabs tabs={tabs} activeKey={String(openTab)} onSelect={selectTab} testId="simple-view-tabs" />
        <div style={{ flex: 1, minHeight: 0 }}>{body}</div>
      </div>
    ) : body);
    if (currentMode === 'table' && rows.length > 0) {
      return inTabs(<ContentTable tableData={rows} nodeId={data.nodeId} />);
    }
    if (currentMode === 'image' && rows.length > 0 && shownImageColumns.length > 0) {
      return inTabs(
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {imageColumns.length > 1 && (
            <label
              className="nodrag"
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', fontSize: 11 }}
            >
              <span>{IMAGE_COLUMN_LABEL}</span>
              <select
                aria-label={IMAGE_COLUMN_LABEL}
                data-curio-image-column="true"
                value={choice}
                onChange={(e) => pickColumn(e.target.value)}
                style={{ fontSize: 11 }}
              >
                <option value={ALL_IMAGE_COLUMNS}>{ALL_IMAGE_COLUMNS_WORD}</option>
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
              dataflowId={dataflowId}
              onPlayed={played}
            />
          </div>
        </div>,
      );
    }
    if (currentMode === 'text' && textContent) {
      // This pane is where an upstream error's text lands, so it is the string
      // a user most often needs to hand to an agent (#267). `.react-flow__node`
      // sets `user-select: none` so a drag pans the node, which made it
      // unselectable; `nodrag` releases the gesture and `userSelect` re-enables
      // the selection, the same pairing CodeEditor's output pane uses. `nowheel`
      // because the pane scrolls horizontally on its own.
      return inTabs(
        <div style={{ position: 'relative', height: '100%' }}>
          {/* Floated over the pane rather than above it: the node body is
              short, and a header row would cost a line of the text itself. */}
          <div
            className="nodrag"
            style={{ position: 'absolute', top: 4, right: 4, zIndex: 1 }}
          >
            <CopyButton value={textContent} label="Copy text" />
          </div>
          <pre
            className="nodrag nowheel"
            data-curio-node-text="true"
            style={{
              margin: 0,
              padding: '8px',
              fontSize: '12px',
              overflowX: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              userSelect: 'text',
              cursor: 'text',
            }}
          >
            {textContent}
          </pre>
        </div>,
      );
    }
    // Every branch above now requires actual content, so this is reached
    // whenever there is none — where it used to return `undefined` and
    // UniversalNode rendered nothing at all (#224). `ContentTable` with an
    // empty array was the same defect wearing a table: it drew an empty
    // <Table> and looked like a node that had failed.
    const reason = resolveNodeEmptyReason({
      connected,
      upstreamErrored,
      upstreamRunning,
      upstreamStopped,
      hasInput: data.input != null && data.input !== '',
      reading,
      onDashboard,
      // 'text' is the fallback mode for anything that is not a frame,
      // so a text mode with no content is a payload we cannot show.
      tabular: currentMode !== 'text',
      rowCount: rows.length,
    }) ?? 'not-tabular';
    return inTabs(
      <NodeEmptyState
        reason={reason}
        hint={reason === 'upstream-stopped' ? upstreamStopped ?? undefined : undefined}
        progress={reason === 'upstream-running' ? upstreamDownloads : undefined}
      />,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentMode, rows, imageColumns, shownImageColumns, choice, interacted, textContent, data.nodeId, data.input, connected, upstreamErrored, upstreamRunning, upstreamStopped, downloadsSaid, reading, onDashboard, clickRow, played, pickColumn, tabs, openTab, selectTab]);

  return {
    contentComponent,
    controlsComponent,
    ownWidgets: OWN_WIDGETS,
    // No Play: the editor's send-code callback reaches no header, so the node
    // shows no Play, run status or Save output toggle.
    setSendCodeCallbackOverride: (_: any) => {},
    untilHandedOn,
  };
};
