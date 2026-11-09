/**
 * The card grid that replaced the bare thumbnail grid (#276).
 *
 * The old grid drew 50px images and nothing else, so retiring the CV Gallery
 * would have lost the per-image values it showed beside each picture. A card
 * carries the row that produced the image, and can carry more than one image
 * column, which is how source and segmentation sit side by side.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import ImageCardGrid, { CARD_PAGE_SIZE } from '../../../../adapters/node/components/ImageCardGrid';
import { PLAYER_TELLS_EVERY_MS } from '../../../../utils/playerSelection';

jest.mock('../../../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));
jest.mock('../../../../utils/authApi', () => ({ getToken: () => 'tok-123', apiFetch: jest.fn() }));

const rows = [
  { image_url: 'https://example.test/a?size=640', image_id: 'CAoSL1', dominant_class: 'vegetation' },
  { image_url: 'https://example.test/b?size=640', image_id: 'CAoSL2', dominant_class: 'road' },
];

const defaultProps = {
  nodeId: 'sv-1',
  rows,
  imageColumns: ['image_url'],
  interacted: ['0', '0'],
  onClickRow: jest.fn(),
};

describe('ImageCardGrid', () => {
  beforeEach(() => jest.clearAllMocks());

  it('draws one image per row', () => {
    render(<ImageCardGrid {...defaultProps} />);
    const imgs = screen.getAllByRole('img');
    expect(imgs).toHaveLength(2);
    expect(imgs[0]).toHaveAttribute('src', 'https://example.test/a?size=640');
  });

  it('captions each card with the rest of its row', () => {
    render(<ImageCardGrid {...defaultProps} />);
    expect(screen.getByText('image_id: CAoSL1')).toBeInTheDocument();
    expect(screen.getByText('dominant_class: vegetation')).toBeInTheDocument();
  });

  it('draws every requested image column side by side', () => {
    const twoColumns = rows.map((r) => ({ ...r, overlay_url: 'https://example.test/o.png' }));
    render(
      <ImageCardGrid
        {...defaultProps}
        rows={twoColumns}
        imageColumns={['image_url', 'overlay_url']}
      />,
    );
    expect(screen.getAllByRole('img')).toHaveLength(4);
  });

  it('reports the row index, not a flattened image index', () => {
    const onClickRow = jest.fn();
    render(<ImageCardGrid {...defaultProps} onClickRow={onClickRow} />);
    fireEvent.click(document.getElementById('imageBox_content_sv-1_1')!);
    expect(onClickRow).toHaveBeenCalledWith(1);
  });

  it('outlines a card the linked pool marked as interacted', () => {
    const { container } = render(<ImageCardGrid {...defaultProps} interacted={['1', '0']} />);
    const cards = container.querySelectorAll('[id^="imageBox_content_sv-1_"]');
    expect(cards[0]).toHaveStyle({ border: '3px solid rgb(255, 0, 0)' });
    expect(cards[1]).not.toHaveStyle({ border: '3px solid rgb(255, 0, 0)' });
  });

  it('ignores an interacted array that does not line up with the rows', () => {
    const { container } = render(<ImageCardGrid {...defaultProps} interacted={['1']} />);
    const cards = container.querySelectorAll('[id^="imageBox_content_sv-1_"]');
    expect(cards[0]).not.toHaveStyle({ border: '3px solid rgb(255, 0, 0)' });
  });

  it('fetches a same-origin /api image with the bearer token and revokes its blob', async () => {
    // A bare <img src> cannot send a header, and the route behind /api resolves
    // which user is asking from that header, so this path is the whole reason
    // overlays can live in a column at all.
    const blob = new Blob(['png'], { type: 'image/png' });
    const fetchMock = jest.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(blob) });
    (global as any).fetch = fetchMock;
    const createObjectURL = jest.fn(() => 'blob:overlay-1');
    const revokeObjectURL = jest.fn();
    (global as any).URL.createObjectURL = createObjectURL;
    (global as any).URL.revokeObjectURL = revokeObjectURL;

    const authed = [{ overlay_url: '/api/datasets/data.curio.mapillary-sample/media/a.jpg', image_id: 'a' }];
    let view: any;
    await act(async () => {
      view = render(
        <ImageCardGrid
          {...defaultProps}
          rows={authed}
          imageColumns={['overlay_url']}
          interacted={['0']}
        />,
      );
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://backend.test/api/datasets/data.curio.mapillary-sample/media/a.jpg',
      { headers: { Authorization: 'Bearer tok-123' }, signal: expect.any(AbortSignal) },
    );
    await waitFor(() => {
      expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:overlay-1');
    });

    const signal: AbortSignal = fetchMock.mock.calls[0][1].signal;
    expect(signal.aborted).toBe(false);
    view.unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:overlay-1');
    // A card no longer shown stops fetching its image.
    expect(signal.aborted).toBe(true);
  });

  it('holds the slot instead of throwing when an authed image fails', async () => {
    (global as any).fetch = jest.fn().mockResolvedValue({ ok: false, status: 404 });
    const authed = [{ overlay_url: '/api/datasets/data.curio.mapillary-sample/media/missing.jpg' }];
    await act(async () => {
      render(
        <ImageCardGrid
          {...defaultProps}
          rows={authed}
          imageColumns={['overlay_url']}
          interacted={['0']}
        />,
      );
    });
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    expect(document.getElementById('imageBox_content_sv-1_0')).toBeInTheDocument();
  });

  it('draws a page of cards at a time', () => {
    const many = Array.from({ length: CARD_PAGE_SIZE + 3 }, (_, i) => ({
      image_url: `https://example.test/${i}.png`,
    }));
    render(
      <ImageCardGrid
        {...defaultProps}
        rows={many}
        interacted={many.map(() => '0')}
      />,
    );
    expect(screen.getAllByRole('img')).toHaveLength(CARD_PAGE_SIZE);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getAllByRole('img')).toHaveLength(3);
    // Row indices stay absolute, so a selection reaches the right row.
    expect(document.getElementById(`imageBox_content_sv-1_${CARD_PAGE_SIZE}`)).toBeInTheDocument();
  });

  it('keeps its page when a selection is written back onto the same rows', () => {
    const many = Array.from({ length: CARD_PAGE_SIZE + 3 }, (_, i) => ({
      file_id: `f${i}`,
      image_url: `https://example.test/${i}.png`,
    }));
    const { rerender } = render(
      <ImageCardGrid {...defaultProps} rows={many} interacted={many.map(() => '0')} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getAllByRole('img')).toHaveLength(3);
    // A linked Data Pool marks the clicked row: a new array, the same frame.
    const marked = many.map((row, i) => ({ ...row, interacted: i === CARD_PAGE_SIZE ? '1' : '0' }));
    rerender(<ImageCardGrid {...defaultProps} rows={marked} interacted={marked.map((r) => r.interacted)} />);
    expect(screen.getAllByRole('img')).toHaveLength(3);
    // A frame with other rows starts on its first page.
    const other = many.slice(1);
    rerender(<ImageCardGrid {...defaultProps} rows={other} interacted={other.map(() => '0')} />);
    expect(screen.getAllByRole('img')).toHaveLength(CARD_PAGE_SIZE);
  });

  it('plays a collection video through a signed link', async () => {
    const { apiFetch } = require('../../../../utils/authApi') as { apiFetch: jest.Mock };
    apiFetch.mockResolvedValue({ url: '/api/media/signed-token' });
    const video = [{
      thumbnail: 'https://example.test/poster.png',
      kind: 'video',
      dataset_id: 'imported.xc1@1',
      file_id: 'b'.repeat(16),
      name: 'clip.mp4',
    }];
    const onClickRow = jest.fn();
    const { container } = render(
      <ImageCardGrid {...defaultProps} rows={video} imageColumns={['thumbnail']} interacted={['0']} onClickRow={onClickRow} />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Play clip.mp4' }));
    });
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/datasets/imported.xc1%401/media/${'b'.repeat(16)}/link`,
      { method: 'POST' },
    );
    await waitFor(() => {
      expect(container.querySelector('video')).toHaveAttribute('src', 'http://backend.test/api/media/signed-token');
    });
    expect(onClickRow).not.toHaveBeenCalled();
  });

  describe('when its signed link lapses', () => {
    // The backend checks a player's signed link on every range the element
    // fetches, and refuses it once its life (`expiresIn`, ten minutes) is
    // over. A seek, or the next range of a long play, after that failed, and
    // the player stopped there for good.
    const { apiFetch } = require('../../../../utils/authApi') as { apiFetch: jest.Mock };
    const MINUTE = 60_000;
    const LINK_PATH = `/api/datasets/imported.xc1%401/media/${'b'.repeat(16)}/link?dataflowId=alices-dataflow`;
    const linkUrl = (n: number) => `http://backend.test/api/media/link-${n}`;
    let clock = 0;
    let now: jest.SpyInstance;
    let play: jest.SpyInstance;

    beforeEach(() => {
      let minted = 0;
      apiFetch.mockReset();
      apiFetch.mockImplementation(() => Promise.resolve({ url: `/api/media/link-${++minted}`, expiresIn: 600 }));
      clock = 1_700_000_000_000;
      now = jest.spyOn(Date, 'now').mockImplementation(() => clock);
      play = jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    });

    afterEach(() => {
      now.mockRestore();
      play.mockRestore();
      apiFetch.mockReset();
    });

    /** Plays a collection's file from its card, on alice's dataflow, and
     *  returns its element once the first link has loaded. */
    async function playCard(kind: 'video' | 'audio'): Promise<HTMLMediaElement> {
      const name = kind === 'video' ? 'clip.mp4' : 'birds.wav';
      const row = {
        thumbnail: 'https://example.test/poster.png',
        kind,
        dataset_id: 'imported.xc1@1',
        file_id: 'b'.repeat(16),
        name,
      };
      const { container } = render(
        <ImageCardGrid
          {...defaultProps}
          rows={[row]}
          imageColumns={['thumbnail']}
          interacted={['0']}
          dataflowId="alices-dataflow"
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: `Play ${name}` }));
      });
      const element = await waitFor(() => {
        const found = container.querySelector(kind);
        expect(found).toHaveAttribute('src', linkUrl(1));
        return found as HTMLMediaElement;
      });
      // The first link plays from the start on its own.
      expect(element).toHaveAttribute('autoplay');
      fireEvent.loadedMetadata(element);
      fireEvent.play(element);
      return element;
    }

    /** What the browser does when the element loads a new link: back to
     *  the start, at the default speed, then its metadata. */
    function loadFresh(element: HTMLMediaElement) {
      element.currentTime = 0;
      element.playbackRate = 1;
      fireEvent.loadedMetadata(element);
    }

    const KINDS = [
      { kind: 'video' as const, file: 'a video' },
      { kind: 'audio' as const, file: 'a recording' },
    ];

    it.each(KINDS)(
      '$file still playing when a range fails after its link lapsed plays on from there on a fresh link',
      async ({ kind }) => {
        const element = await playCard(kind);
        element.playbackRate = 1.5;
        element.currentTime = 683.2;
        fireEvent.timeUpdate(element);
        clock += 11 * MINUTE;
        await act(async () => {
          fireEvent.error(element);
        });

        await waitFor(() => expect(element).toHaveAttribute('src', linkUrl(2)));
        // Asked as the first was, through the same dataflow.
        expect(apiFetch.mock.calls).toEqual([[LINK_PATH, { method: 'POST' }], [LINK_PATH, { method: 'POST' }]]);
        expect(element).not.toHaveAttribute('autoplay');
        loadFresh(element);
        expect([element.currentTime, element.playbackRate]).toEqual([683.2, 1.5]);
        expect(play).toHaveBeenCalledTimes(1);
      },
    );

    it.each(KINDS)(
      '$file paused past its link\'s life stays paused where a seek took it, on a fresh link',
      async ({ kind }) => {
        const element = await playCard(kind);
        element.currentTime = 42;
        fireEvent.timeUpdate(element);
        fireEvent.pause(element);
        // A quarter of an hour later, a seek past what the element holds.
        clock += 15 * MINUTE;
        element.currentTime = 300;
        fireEvent.seeking(element);
        await act(async () => {
          fireEvent.error(element);
        });

        await waitFor(() => expect(element).toHaveAttribute('src', linkUrl(2)));
        expect(element).not.toHaveAttribute('autoplay');
        loadFresh(element);
        expect(element.currentTime).toBe(300);
        expect(play).not.toHaveBeenCalled();
      },
    );

    it('a link that fails while still good asks for none: the failure is the file\'s own', async () => {
      const element = await playCard('video');
      clock += 3 * MINUTE;
      await act(async () => {
        fireEvent.error(element);
      });
      expect(apiFetch).toHaveBeenCalledTimes(1);
      expect(element).toHaveAttribute('src', linkUrl(1));

      // Nor does a fresh link that fails at once: a file that cannot play
      // asks for one link more, not one after another.
      clock += 8 * MINUTE;
      await act(async () => {
        fireEvent.error(element);
      });
      await waitFor(() => expect(element).toHaveAttribute('src', linkUrl(2)));
      await act(async () => {
        fireEvent.error(element);
      });
      expect(apiFetch).toHaveBeenCalledTimes(2);
      expect(element).toHaveAttribute('src', linkUrl(2));
    });
  });

  // Where a card's player stands goes to `onPlayed`, which Simple View sends
  // to the views it is linked to as the range it has played.
  describe('its player tells where it stands', () => {
    const { apiFetch } = require('../../../../utils/authApi') as { apiFetch: jest.Mock };
    const MINUTE = 60_000;
    let clock = 0;
    let now: jest.SpyInstance;
    let play: jest.SpyInstance;

    beforeEach(() => {
      let minted = 0;
      apiFetch.mockReset();
      apiFetch.mockImplementation(() => Promise.resolve({ url: `/api/media/link-${++minted}`, expiresIn: 600 }));
      clock = 1_700_000_000_000;
      now = jest.spyOn(Date, 'now').mockImplementation(() => clock);
      play = jest.spyOn(window.HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    });

    afterEach(() => {
      now.mockRestore();
      play.mockRestore();
      apiFetch.mockReset();
    });

    const fileOf = (name: string, kind: 'video' | 'audio' = 'video') => ({
      thumbnail: 'https://example.test/poster.png',
      kind,
      dataset_id: 'imported.xc1@1',
      file_id: name.replace(/\W/g, '').padEnd(16, 'f'),
      name,
    });

    /** Plays *row*'s card among *rows* and returns its element once its link loaded. */
    async function playCard(rows: Record<string, unknown>[], row: Record<string, unknown>, onPlayed: jest.Mock) {
      const view = render(
        <ImageCardGrid
          {...defaultProps}
          rows={rows}
          imageColumns={['thumbnail']}
          interacted={rows.map(() => '0')}
          onPlayed={onPlayed}
        />,
      );
      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: `Play ${row.name}` }));
      });
      const element = await waitFor(() => {
        const found = view.container.querySelector('video, audio');
        expect(found).toHaveAttribute('src', 'http://backend.test/api/media/link-1');
        return found as HTMLMediaElement;
      });
      fireEvent.loadedMetadata(element);
      return { element, view };
    }

    it.each(['video', 'audio'] as const)(
      'a %s tells where it starts, where a seek takes it and where it stops, at once',
      async (kind) => {
        const row = fileOf(kind === 'video' ? 'clip.mp4' : 'birds.wav', kind);
        const onPlayed = jest.fn();
        const { element } = await playCard([row], row, onPlayed);
        expect(onPlayed).not.toHaveBeenCalled();

        fireEvent.play(element);
        element.currentTime = 5;
        fireEvent.seeking(element);
        fireEvent.seeked(element);
        element.currentTime = 5.5;
        fireEvent.pause(element);

        expect(onPlayed.mock.calls).toEqual([[row, 0], [row, 5], [row, 5.5]]);
      },
    );

    it('while it plays, tells a time at most every PLAYER_TELLS_EVERY_MS, and none it told already', async () => {
      const row = fileOf('clip.mp4');
      const onPlayed = jest.fn();
      const { element } = await playCard([row], row, onPlayed);
      fireEvent.play(element);

      clock += PLAYER_TELLS_EVERY_MS / 2;
      element.currentTime = 0.1;
      fireEvent.timeUpdate(element);
      clock += PLAYER_TELLS_EVERY_MS;
      element.currentTime = 0.35;
      fireEvent.timeUpdate(element);
      clock += PLAYER_TELLS_EVERY_MS;
      fireEvent.timeUpdate(element);
      // A seek tells at once, however soon after.
      element.currentTime = 0.2;
      fireEvent.seeked(element);

      expect(onPlayed.mock.calls).toEqual([[row, 0], [row, 0.35], [row, 0.2]]);
    });

    it('tells null once it closes, when another card plays', async () => {
      const first = fileOf('first.mp4');
      const second = fileOf('second.mp4');
      const onPlayed = jest.fn();
      const { element } = await playCard([first, second], first, onPlayed);
      element.currentTime = 2;
      fireEvent.seeked(element);

      await act(async () => {
        fireEvent.click(screen.getByRole('button', { name: 'Play second.mp4' }));
      });

      expect(onPlayed.mock.calls).toEqual([[first, 2], [first, null]]);
    });

    it('a player that told nothing tells nothing when it closes', async () => {
      const row = fileOf('clip.mp4');
      const onPlayed = jest.fn();
      const { view } = await playCard([row], row, onPlayed);
      view.unmount();
      expect(onPlayed).not.toHaveBeenCalled();
    });

    it('on a fresh link after a lapse, tells nothing until the element stands where the player stood', async () => {
      const row = fileOf('clip.mp4');
      const onPlayed = jest.fn();
      const { element } = await playCard([row], row, onPlayed);
      fireEvent.play(element);
      clock += MINUTE;
      element.currentTime = 683.2;
      fireEvent.timeUpdate(element);
      clock += 11 * MINUTE;
      await act(async () => {
        fireEvent.error(element);
      });
      await waitFor(() => expect(element).toHaveAttribute('src', 'http://backend.test/api/media/link-2'));

      // The fresh link loads at the start before its metadata takes it back.
      element.currentTime = 0;
      fireEvent.timeUpdate(element);
      fireEvent.pause(element);
      fireEvent.loadedMetadata(element);
      expect(element.currentTime).toBe(683.2);
      fireEvent.seeked(element);
      clock += MINUTE;
      element.currentTime = 684;
      fireEvent.timeUpdate(element);

      expect(onPlayed.mock.calls).toEqual([[row, 0], [row, 683.2], [row, 684]]);
    });
  });
});
