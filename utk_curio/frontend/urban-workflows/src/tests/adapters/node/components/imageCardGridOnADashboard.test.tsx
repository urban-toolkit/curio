/**
 * A dashboard's Simple View tile shows its rows' images and plays their
 * videos to whoever opens the page, signed in or not (#1117). The media route
 * needs a sign-in, so the page asks the dashboard for links to the files the
 * tile's output names (`POST /api/projects/<id>/dashboard/media`) and reads
 * each file through its link, `/api/media/<token>`. A file the row's own run
 * derived on the server is named with that run's folder (`kept`), and a link
 * past its life is asked for again.
 *
 * Only names the page had before are imported: the tile reads its input with
 * `fetchData`, as on the page, and the cards draw from its rows.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ImageCardGrid from '../../../../adapters/node/components/ImageCardGrid';
import { fetchData } from '../../../../services/api';
import { resetEmbeddedDashboardForTests } from '../../../../standalone/dashboardPayload';

jest.mock('../../../../utils/backendUrl', () => ({ backendUrl: () => 'http://backend.test' }));

const SURVEY = 'data.curio.storage-survey';
const KEPT = `k${'1'.repeat(32)}`;

interface Asked {
  url: string;
  method: string;
  body: any;
}

let asked: Asked[] = [];
/** The links the dashboard answers, by file id; each ask's answer counted. */
let tokens: Record<string, string> = {};
let answered = 0;
const originalFetch = global.fetch;

function photoRow(fileId: string) {
  return {
    name: `${fileId}.jpg`,
    dataset_id: SURVEY,
    file_id: fileId,
    kind: 'image',
    thumbnail: `/api/datasets/${SURVEY}/media/${fileId}?variant=thumb`,
    image_url: `/api/datasets/${SURVEY}/media/${fileId}?variant=original`,
  };
}

/** A video a viewer's run made on the server: its URLs name the run's folder. */
function overlayVideoRow(fileId: string) {
  const id = `${fileId}@0-seg.mp4`;
  return {
    name: 'overlay',
    dataset_id: SURVEY,
    file_id: id,
    kind: 'video',
    thumbnail: `/api/datasets/${SURVEY}/media/${id}?variant=thumb&kept=${KEPT}`,
    image_url: `/api/datasets/${SURVEY}/media/${id}?variant=thumb&kept=${KEPT}`,
  };
}

/** The page as the page server sends it: a payload holding *outputs*. */
function servePage(outputs: Record<string, Record<string, unknown>[]>) {
  const frames: Record<string, unknown> = {};
  for (const [name, rows] of Object.entries(outputs)) {
    const columns: Record<string, unknown[]> = {};
    for (const column of Object.keys(rows[0])) columns[column] = rows.map((row) => row[column]);
    frames[name] = { dataType: 'dataframe', data: columns };
  }
  document.body.innerHTML = '';
  const tag = document.createElement('script');
  tag.id = 'curio-dashboard-payload';
  tag.type = 'application/json';
  tag.textContent = JSON.stringify({ meta: { projectId: 'dash-1', name: 'Survey' }, spec: {}, outputs: frames });
  document.body.appendChild(tag);
  resetEmbeddedDashboardForTests();
}

function grid(rows: Record<string, unknown>[]) {
  return (
    <ImageCardGrid
      nodeId="view"
      rows={rows}
      imageColumns={['thumbnail']}
      interacted={rows.map(() => '0')}
      onClickRow={jest.fn()}
    />
  );
}

beforeEach(() => {
  asked = [];
  tokens = {};
  answered = 0;
  (global as any).URL.createObjectURL = jest.fn(() => 'blob:card');
  (global as any).URL.revokeObjectURL = jest.fn();
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : null;
    asked.push({ url: String(url), method: init?.method ?? 'GET', body });
    if (String(url) === 'http://backend.test/api/projects/dash-1/dashboard/media') {
      answered += 1;
      const links = (body?.files ?? [])
        .filter((file: any) => tokens[file.fileId])
        .map((file: any) => ({ ...file, url: `/api/media/${tokens[file.fileId]}-${answered}` }));
      return { ok: true, status: 200, json: async () => ({ links, expiresIn: 600 }) } as any;
    }
    return { ok: true, status: 200, blob: async () => new Blob(['bytes']) } as any;
  }) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
  jest.restoreAllMocks();
});

describe("a dashboard tile's cards", () => {
  test("read the photo through the dashboard's link, not the media route that needs a sign-in", async () => {
    const row = photoRow('aaaaaaaaaaaaaaaa');
    tokens = { aaaaaaaaaaaaaaaa: 'PHOTO' };
    servePage({ 'photos-1.parquet': [row] });
    await fetchData('photos-1.parquet');

    await act(async () => {
      render(grid([row]));
    });

    await waitFor(() => {
      expect(asked.map((a) => a.url)).toContain('http://backend.test/api/media/PHOTO-1?variant=thumb');
    });
    expect(asked.filter((a) => a.url.includes('/api/datasets/'))).toEqual([]);
    const ask = asked.find((a) => a.url.endsWith('/dashboard/media'));
    expect(ask?.method).toBe('POST');
    expect(ask?.body).toEqual({
      fileName: 'photos-1.parquet',
      files: [{ datasetId: SURVEY, fileId: 'aaaaaaaaaaaaaaaa', kept: null }],
    });
    await waitFor(() => expect(screen.getByRole('img')).toHaveAttribute('src', 'blob:card'));
  });

  test("play a video a viewer's run made from the dashboard's link to that run's file", async () => {
    const row = overlayVideoRow('bbbbbbbbbbbbbbbb');
    tokens = { 'bbbbbbbbbbbbbbbb@0-seg.mp4': 'CLIP' };
    servePage({ 'clips-1.parquet': [row] });
    await fetchData('clips-1.parquet');
    await act(async () => {
      render(grid([row]));
    });

    fireEvent.click(screen.getByRole('button', { name: 'Play overlay' }));

    await waitFor(() => {
      expect(document.querySelector('video')?.getAttribute('src')).toBe(
        'http://backend.test/api/media/CLIP-1?variant=original',
      );
    });
    expect(asked.filter((a) => a.url.includes('/api/datasets/'))).toEqual([]);
    const ask = asked.find((a) => a.url.endsWith('/dashboard/media'));
    expect(ask?.body.files).toEqual([{ datasetId: SURVEY, fileId: 'bbbbbbbbbbbbbbbb@0-seg.mp4', kept: KEPT }]);
  });

  test('ask for a link again once it has lapsed', async () => {
    const row = photoRow('cccccccccccccccc');
    tokens = { cccccccccccccccc: 'PHOTO' };
    servePage({ 'photos-2.parquet': [row] });
    await fetchData('photos-2.parquet');
    const opened = Date.now();
    let view: ReturnType<typeof render> | undefined;
    await act(async () => {
      view = render(grid([row]));
    });
    await waitFor(() => {
      expect(asked.map((a) => a.url)).toContain('http://backend.test/api/media/PHOTO-1?variant=thumb');
    });
    view?.unmount();

    // Eleven minutes on, past the link's ten, the card is drawn again.
    jest.spyOn(Date, 'now').mockReturnValue(opened + 11 * 60 * 1000);
    await act(async () => {
      render(grid([row]));
    });

    await waitFor(() => {
      expect(asked.map((a) => a.url)).toContain('http://backend.test/api/media/PHOTO-2?variant=thumb');
    });
    expect(asked.filter((a) => a.url.endsWith('/dashboard/media'))).toHaveLength(2);
  });

  test('read a file no dashboard output names as the canvas reads it, with the sign-in', async () => {
    const row = photoRow('eeeeeeeeeeeeeeee');
    servePage({ 'photos-3.parquet': [photoRow('ffffffffffffffff')] });
    await fetchData('photos-3.parquet');

    await act(async () => {
      render(grid([row]));
    });

    await waitFor(() => {
      expect(asked.map((a) => a.url)).toContain(
        `http://backend.test/api/datasets/${SURVEY}/media/eeeeeeeeeeeeeeee?variant=thumb`,
      );
    });
    expect(asked.filter((a) => a.url.endsWith('/dashboard/media'))).toEqual([]);
  });
});
