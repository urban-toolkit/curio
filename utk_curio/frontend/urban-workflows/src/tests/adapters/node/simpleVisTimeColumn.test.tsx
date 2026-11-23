/**
 * Simple View's Time column: the column its player's range names in the views
 * linked to it (utils/playerSelection). A linked view lights the rows whose
 * value in that column lies in the range played, by the matcher every view's
 * selection goes through (`selectionMatch.selectIndices`), so a table that
 * keeps its time in another column links with no node that renames it to
 * t_s. A played row's own start stays its t_s, the column Curio's media nodes
 * write it in. A Simple View that holds no Time column, as one saved before it
 * had the setting, names t_s.
 */
import React from 'react';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';
import { NodeType, VisInteractionType } from '../../../constants';
import { PLAYER_SELECT } from '../../../utils/playerSelection';
import { objectRows, selectIndices } from '../../../utils/selectionMatch';

const mockUpdateDataNode = jest.fn();

jest.mock('reactflow', () => ({ useEdges: () => [{ source: 'up', target: 'sv-1' }] }));
jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'wf' }, updateDataNode: mockUpdateDataNode }),
}));
jest.mock('../../../providers/ToastProvider', () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock('../../../services/api', () => ({ fetchData: jest.fn() }));
jest.mock('../../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));
jest.mock('../../../utils/authApi', () => ({
  getToken: () => 'tok-123',
  apiFetch: jest.fn(() => Promise.resolve({ url: '/api/media/link-1', expiresIn: 600 })),
}));

const nodeState = { setOutput: jest.fn() } as any;

function Harness({ data }: { data: any }) {
  const { contentComponent } = useSimpleVisBehavior(data, nodeState);
  return <>{contentComponent}</>;
}

/** A frame of rows, column by column, as the sandbox hands one over. */
function frame(rows: Record<string, unknown>[]) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return {
    dataType: 'dataframe',
    data: Object.fromEntries(columns.map((c) => [c, Object.fromEntries(rows.map((row, i) => [i, row[c] ?? null]))])),
  };
}

const video = (name: string, extra: Record<string, unknown> = {}) => ({
  thumbnail: 'https://example.test/poster.png',
  kind: 'video',
  dataset_id: 'imported.xc1@1',
  file_id: name.replace(/\W/g, '').padEnd(16, 'f'),
  name,
  ...extra,
});

/** The Simple View's Time column, as its Widgets tab keeps it in the node. */
const timeColumn = (value: string) => [
  { name: 'time_column', type: 'text', label: 'Time column', default: 't_s', value },
];

/** A walk's points as a linked map or chart holds them, its time in walked_s. */
const WALK = [
  { label: 'before', walked_s: 49 },
  { label: 'early', walked_s: 51 },
  { label: 'late', walked_s: 53.5 },
  { label: 'after', walked_s: 55 },
  // A point that keeps its time in t_s alone: walked_s names nothing in it.
  { label: 'other column', t_s: 52 },
];

/** The selects the view last told the flow. */
const lastTold = (callback: jest.Mock) => callback.mock.calls[callback.mock.calls.length - 1][0];

/** The points of WALK a linked view lights for the player's select. */
const lit = (told: Record<string, any>) =>
  selectIndices(told[PLAYER_SELECT], objectRows(WALK)).map((index) => WALK[index].label);

describe("Simple View's Time column", () => {
  let play: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    play = jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  });

  afterEach(() => play.mockRestore());

  /** Opens the view on *rows*, plays the card whose Play is named *play*,
   *  and seeks it to *at* seconds. */
  async function playTo(rows: Record<string, unknown>[], playName: string, at: number, extra: Record<string, unknown> = {}) {
    const interactionsCallback = jest.fn();
    const data = { nodeId: 'sv-1', input: frame(rows), outputCallback: jest.fn(), interactionsCallback, ...extra };
    const view = render(<Harness data={data} />);
    await act(async () => {});
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: playName }));
    });
    const element = await waitFor(() => {
      const found = view.container.querySelector('video');
      expect(found).toHaveAttribute('src', 'http://backend.test/api/media/link-1');
      return found as HTMLMediaElement;
    });
    fireEvent.loadedMetadata(element);
    await act(async () => {
      element.currentTime = at;
      fireEvent.seeked(element);
    });
    return { interactionsCallback, view, data };
  }

  it('sends the range it played on the column its Time column names', async () => {
    const { interactionsCallback } = await playTo(
      [video('walk.mp4')], 'Play walk.mp4', 4, { widgets: timeColumn('walked_s') },
    );
    // The walk's video plays from 0: 4 s in, the range is 0 to 4 s.
    expect(lastTold(interactionsCallback)[PLAYER_SELECT]).toEqual({
      type: VisInteractionType.INTERVAL,
      data: { walked_s: [0, 4] },
      priority: 1,
      source: NodeType.VIS_SIMPLE,
    });
  });

  it("keeps a played row's own start in its t_s: an overlay 50 s into its walk lights the points walked from 50 s", async () => {
    // Its Play still names where it starts in its walk.
    const { interactionsCallback } = await playTo(
      [video('overlay.mp4', { t_s: 50 })], 'Play overlay.mp4 from 50 s', 4, { widgets: timeColumn('walked_s') },
    );
    const told = lastTold(interactionsCallback);
    expect(told[PLAYER_SELECT].data).toEqual({ walked_s: [50, 54] });
    expect(lit(told)).toEqual(['early', 'late']);
  });

  it('names t_s when the node holds no Time column, as a Simple View saved before the setting', async () => {
    const { interactionsCallback } = await playTo([video('overlay.mp4', { t_s: 50 })], 'Play overlay.mp4 from 50 s', 4);
    const told = lastTold(interactionsCallback);
    expect(told[PLAYER_SELECT].data).toEqual({ t_s: [50, 54] });
    // The walk's points keep their time in walked_s: only the one with t_s is lit.
    expect(lit(told)).toEqual(['other column']);
  });

  it('names t_s when the Time column is left empty', async () => {
    const { interactionsCallback } = await playTo(
      [video('overlay.mp4', { t_s: 50 })], 'Play overlay.mp4 from 50 s', 4, { widgets: timeColumn('  ') },
    );
    expect(lastTold(interactionsCallback)[PLAYER_SELECT].data).toEqual({ t_s: [50, 54] });
  });

  it('moves the range it holds to a Time column set while a card stands paused, at once', async () => {
    const { interactionsCallback, view, data } = await playTo(
      [video('overlay.mp4', { t_s: 50 })], 'Play overlay.mp4 from 50 s', 4, { widgets: timeColumn('t_s') },
    );
    expect(lastTold(interactionsCallback)[PLAYER_SELECT].data).toEqual({ t_s: [50, 54] });
    await act(async () => {
      view.rerender(<Harness data={{ ...data, widgets: timeColumn('walked_s') }} />);
    });
    const told = lastTold(interactionsCallback);
    expect(told[PLAYER_SELECT]).toEqual({
      type: VisInteractionType.INTERVAL,
      data: { walked_s: [50, 54] },
      priority: 1,
      source: NodeType.VIS_SIMPLE,
    });
    expect(lit(told)).toEqual(['early', 'late']);
  });
});
