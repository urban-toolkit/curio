/**
 * Simple View shows a dict of frames, as a node returns one, a tab per frame,
 * named after its key, as a Data Pool shows it (hook/useTableData): Track
 * Objects' two tables, its videos' overlays and their tracks. The first key's
 * tab is open. In it the overlay's card plays, and the player's range is in
 * the time of the played row's video (utils/playerSelection). Another tab
 * shows its own rows, and leaving a tab closes its player, which takes the
 * range away. While the view reads a dict by its artifact, it says its input
 * is on its way. A dict that holds no frame is the JSON it is.
 */
import React from 'react';
import { render, screen, act, fireEvent, waitFor, within } from '@testing-library/react';
import { useSimpleVisBehavior } from '../../../adapters/node/simpleVisBehavior';
import { NodeType, VisInteractionType } from '../../../constants';
import { PLAYER_SELECT } from '../../../utils/playerSelection';
import { fetchData } from '../../../services/api';

// The flow's updateDataNode keeps its identity from render to render, as
// FlowProvider's (a useCallback in useWorkflowOperations) does.
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

/** A frame, column by column, in the envelope the sandbox hands one over in. */
function frame(rows: Record<string, unknown>[]) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return {
    dataType: 'dataframe',
    data: Object.fromEntries(columns.map((c) => [c, Object.fromEntries(rows.map((row, i) => [i, row[c] ?? null]))])),
  };
}

const WALK = 'a1b2c3d4e5f60718';

/** Track Objects' overlay of a walk tracked from 50 s into it. */
const overlay = {
  thumbnail: 'https://example.test/poster.png',
  kind: 'video',
  dataset_id: 'imported.xc1@1',
  file_id: `${WALK}@50000-sam3abc.mp4`,
  video_file_id: WALK,
  name: 'walk.mp4',
  t_s: 50,
  curb_ramp_objects: 1,
  person_objects: 1,
};

/** The objects it followed, one row each. */
const objects = [
  { video_file_id: WALK, video: 'walk.mp4', object_id: 0, label: 'curb ramp', start_s: 50, end_s: 52.5, frames: 2 },
  { video_file_id: WALK, video: 'walk.mp4', object_id: 1, label: 'person', start_s: 52.5, end_s: 55, frames: 2 },
];

/** Its output as /get answers it: a dict of frames, each value in its own envelope. */
const twoTables = { dataType: 'dict', data: { videos: frame([overlay]), tracks: frame(objects) } };

const tabs = () => screen.getByTestId('simple-view-tabs');
const tabTitles = () => Array.from(tabs().querySelectorAll('.nav-link')).map((tab) => tab.textContent);
const openTab = () => tabs().querySelector('.nav-link.active')?.textContent;
const lastTold = (callback: jest.Mock) => callback.mock.calls[callback.mock.calls.length - 1][0];

const played = (range: [number, number] | null) => ({
  [PLAYER_SELECT]: {
    type: VisInteractionType.INTERVAL,
    data: range ? { t_s: range } : {},
    priority: 1,
    source: NodeType.VIS_SIMPLE,
  },
});

describe('Simple View shows a dict of frames as a tab per frame', () => {
  let play: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    play = jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    (fetchData as jest.Mock).mockResolvedValue(twoTables);
  });

  afterEach(() => play.mockRestore());

  /** The view on Track Objects' output, read by its artifact, as a run hands it on. */
  async function openView() {
    const interactionsCallback = jest.fn();
    const data = {
      nodeId: 'sv-1',
      input: { path: 'art-tracked', dataType: 'dict' },
      outputCallback: jest.fn(),
      interactionsCallback,
    };
    const view = render(<Harness data={data} />);
    await act(async () => {});
    return { view, interactionsCallback };
  }

  /** Plays the overlay's card, and seeks its player to *at* seconds into the overlay. */
  async function playOverlay(view: ReturnType<typeof render>, at: number) {
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Play walk.mp4 from 50 s' }));
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
  }

  it('names each tab after its key, opens the first, and shows no JSON of the dict', async () => {
    const { view } = await openView();
    expect(fetchData).toHaveBeenCalledWith('art-tracked');
    expect(view.container.querySelector('[data-curio-node-text]')).toBeNull();
    await waitFor(() => expect(tabTitles()).toEqual(['videos', 'tracks']));
    expect(openTab()).toBe('videos');
  });

  it("plays the overlay in the videos tab, its range in the time of the played row's video", async () => {
    const { view, interactionsCallback } = await openView();
    await playOverlay(view, 4);
    expect(lastTold(interactionsCallback)).toEqual(played([50, 54]));
  });

  it('shows the tracks tab as a table of its rows, and leaving the videos tab takes the range away', async () => {
    const { view, interactionsCallback } = await openView();
    await playOverlay(view, 2);
    await act(async () => {
      fireEvent.click(within(tabs()).getByText('tracks'));
    });
    expect(openTab()).toBe('tracks');
    expect(screen.getByRole('table', { name: 'simple table' })).toBeInTheDocument();
    expect(screen.getByText('curb ramp')).toBeInTheDocument();
    expect(screen.getByText('person')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Play / })).toBeNull();
    expect(lastTold(interactionsCallback)).toEqual(played(null));
    await act(async () => {
      fireEvent.click(within(tabs()).getByText('videos'));
    });
    expect(openTab()).toBe('videos');
    expect(screen.getByRole('button', { name: 'Play walk.mp4 from 50 s' })).toBeInTheDocument();
  });

  it('says the dict is on its way while it reads it, and never shows the reference it reads it by', async () => {
    let answer: (value: unknown) => void = () => undefined;
    (fetchData as jest.Mock).mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    const input = { path: 'art-tracked', dataType: 'dict' };
    const view = render(<Harness data={{ nodeId: 'sv-1', input, outputCallback: jest.fn(), interactionsCallback: jest.fn() }} />);
    await act(async () => {});
    expect(view.container.querySelector('[data-curio-node-text]')).toBeNull();
    expect(screen.getByText('Computing...')).toBeInTheDocument();
    await act(async () => {
      answer(twoTables);
    });
    expect(tabTitles()).toEqual(['videos', 'tracks']);
  });

  it('shows a dict it holds inline, as a dashboard tile is handed one, as its tabs too', async () => {
    render(<Harness data={{ nodeId: 'sv-1', input: twoTables, outputCallback: jest.fn(), interactionsCallback: jest.fn() }} />);
    await act(async () => {});
    expect(fetchData).not.toHaveBeenCalled();
    expect(tabTitles()).toEqual(['videos', 'tracks']);
    expect(openTab()).toBe('videos');
  });

  it('shows a dict that holds no frame as the JSON it is, with no tabs', async () => {
    const settings = { dataType: 'dict', data: { city: 'Chicago', blocks: 3 } };
    render(<Harness data={{ nodeId: 'sv-1', input: settings, outputCallback: jest.fn(), interactionsCallback: jest.fn() }} />);
    await act(async () => {});
    expect(screen.queryByTestId('simple-view-tabs')).toBeNull();
    expect(document.querySelector('[data-curio-node-text]')?.textContent).toContain('"city": "Chicago"');
  });
});
