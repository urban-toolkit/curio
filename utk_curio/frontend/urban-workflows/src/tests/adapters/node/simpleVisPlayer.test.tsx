/**
 * Simple View's player as a selection source: what a card's player has
 * played, from its file's start to where it stands, goes to the flow as an
 * interval on `t_s`, beside the click on a card, by the rule a chart tells its
 * selects (utils/playerSelection). The flow sends it over the view's
 * interaction edges like any view's selection.
 */
import React from 'react';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';
import { NodeType, VisInteractionType } from '../../../constants';
import { CARD_SELECT, PLAYER_SELECT } from '../../../utils/playerSelection';

jest.mock('reactflow', () => ({ useEdges: () => [{ source: 'up', target: 'sv-1' }] }));
jest.mock('../../../providers/ProvenanceProvider', () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock('../../../providers/FlowProvider', () => ({
  useFlowContext: () => ({ workflowNameRef: { current: 'wf' }, updateDataNode: jest.fn() }),
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

/** Renders the view's body, keeping each one it renders in *bodies*. */
function Harness({ data, bodies }: { data: any; bodies?: unknown[] }) {
  const { contentComponent } = useSimpleVisBehavior(data, nodeState);
  bodies?.push(contentComponent);
  return <>{contentComponent}</>;
}

/** A frame of video rows, column by column, as the sandbox hands one over. */
function videos(rows: Record<string, unknown>[]) {
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

/** The selects the view last told the flow. */
const lastTold = (callback: jest.Mock) => callback.mock.calls[callback.mock.calls.length - 1][0];

const interval = (range: [number, number] | null, priority: number) => ({
  type: VisInteractionType.INTERVAL,
  data: range ? { t_s: range } : {},
  priority,
  source: NodeType.VIS_SIMPLE,
});

describe("Simple View's player as a selection", () => {
  let play: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    play = jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  });

  afterEach(() => play.mockRestore());

  /** Opens the view on *rows* and plays *name*'s card; returns its element. */
  async function playCard(rows: Record<string, unknown>[], name: string, extra: Record<string, unknown> = {}) {
    const interactionsCallback = jest.fn();
    const bodies: unknown[] = [];
    const data = { nodeId: 'sv-1', input: videos(rows), outputCallback: jest.fn(), interactionsCallback, ...extra };
    const view = render(<Harness data={data} bodies={bodies} />);
    await act(async () => {});
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: `Play ${name}` }));
    });
    const element = await waitFor(() => {
      const found = view.container.querySelector('video');
      expect(found).toHaveAttribute('src', 'http://backend.test/api/media/link-1');
      return found as HTMLMediaElement;
    });
    fireEvent.loadedMetadata(element);
    return { element, interactionsCallback, bodies, view, data };
  }

  it("tells the flow the range a video has played, from its start to where it stands, as an interval on t_s", async () => {
    const { element, interactionsCallback } = await playCard([video('walk.mp4')], 'walk.mp4');
    await act(async () => {
      fireEvent.play(element);
    });
    expect(lastTold(interactionsCallback)).toEqual({ [PLAYER_SELECT]: interval([0, 0], 1) });
    await act(async () => {
      element.currentTime = 4.5;
      fireEvent.seeked(element);
    });
    expect(interactionsCallback).toHaveBeenLastCalledWith({ [PLAYER_SELECT]: interval([0, 4.5], 1) }, 'sv-1');
  });

  it("an overlay's range is in the time of its video: it starts at the overlay's t_s", async () => {
    const { element, interactionsCallback } = await playCard([video('overlay.mp4', { t_s: 50 })], 'overlay.mp4');
    await act(async () => {
      element.currentTime = 4;
      fireEvent.seeked(element);
    });
    expect(lastTold(interactionsCallback)).toEqual({ [PLAYER_SELECT]: interval([50, 54], 1) });
  });

  it("a click on a card after it is the latest select, and the player's range stays at priority 0", async () => {
    const { element, interactionsCallback } = await playCard([video('walk.mp4'), video('other.mp4')], 'walk.mp4');
    await act(async () => {
      element.currentTime = 2;
      fireEvent.seeked(element);
    });
    await act(async () => {
      fireEvent.click(document.getElementById('imageBox_content_sv-1_1')!);
    });
    expect(lastTold(interactionsCallback)).toEqual({
      [PLAYER_SELECT]: interval([0, 2], 0),
      [CARD_SELECT]: { type: VisInteractionType.POINT, data: [1], priority: 1, source: NodeType.VIS_SIMPLE },
    });
  });

  it('a player that closes takes its range away: a new frame closes it', async () => {
    const { element, interactionsCallback, view, data } = await playCard([video('walk.mp4')], 'walk.mp4');
    await act(async () => {
      element.currentTime = 3;
      fireEvent.seeked(element);
    });
    await act(async () => {
      view.rerender(<Harness data={{ ...data, input: videos([video('next.mp4')]) }} />);
    });
    expect(lastTold(interactionsCallback)).toEqual({ [PLAYER_SELECT]: interval(null, 1) });
  });

  it("keeps the view's body as it was while the player tells its time, so the node stays on its tab", async () => {
    const { element, bodies } = await playCard([video('walk.mp4')], 'walk.mp4');
    const body = bodies[bodies.length - 1];
    await act(async () => {
      fireEvent.play(element);
      element.currentTime = 1;
      fireEvent.seeked(element);
      element.currentTime = 2;
      fireEvent.pause(element);
    });
    expect(bodies[bodies.length - 1]).toBe(body);
    expect(document.querySelector('video')).toBe(element);
  });

  it('a selection the view receives moves no player and tells nothing back', async () => {
    const { element, interactionsCallback, view, data } = await playCard([video('walk.mp4')], 'walk.mp4');
    await act(async () => {
      element.currentTime = 3;
      fireEvent.seeked(element);
    });
    const told = interactionsCallback.mock.calls.length;
    const picked = [{ nodeId: 'map', details: { autk_selection: { type: 'POINT', data: [{ t_s: 1 }], priority: 1 } }, priority: 1 }];
    await act(async () => {
      view.rerender(<Harness data={{ ...data, interactions: picked }} />);
    });
    expect(element.currentTime).toBe(3);
    expect(interactionsCallback.mock.calls.length).toBe(told);
  });
});
