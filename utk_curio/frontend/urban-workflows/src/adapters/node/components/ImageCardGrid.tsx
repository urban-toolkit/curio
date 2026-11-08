import React, { useEffect, useRef, useState } from 'react';
import CSS from 'csstype';
import { ImageSource, resolveImageSources } from '../../../utils/imageColumns';
import { backendUrl } from '../../../utils/backendUrl';
import { apiFetch } from '../../../utils/authApi';
import { collectionMediaPath } from '../../../utils/collectionMedia';
import { useAuthedObjectUrl } from '../../../utils/useAuthedObjectUrl';

/**
 * One card per row: every image column of that row side by side, above the
 * row's remaining values (#276).
 *
 * This replaces a bare 50px thumbnail grid. The card shape is what the retired
 * CV Gallery showed - a picture is rarely useful without the row that produced
 * it - and it generalises: any frame with an image column plus attributes
 * reads the same way.
 *
 * Cards are drawn a page at a time, so a collection of thousands of files
 * fetches one page of thumbnails, not all of them. A video or recording of a
 * collection plays in its card.
 */

/** Cards per page. */
export const CARD_PAGE_SIZE = 48;

interface ImageCardGridProps {
  nodeId: string;
  rows: Record<string, unknown>[];
  /** Columns to draw as images, in order; the rest become the card's caption. */
  imageColumns: string[];
  /** Parallel to `rows`: '1' marks a row selected from a linked Data Pool. */
  interacted: string[];
  onClickRow: (rowIndex: number) => void;
  /** The dataflow a collection's files are read through (`collectionMediaPath`):
   *  on an invited editor's canvas, the owner's, whose collections the
   *  editor's runs load. */
  dataflowId?: string | null;
}

const containerStyle: CSS.Properties = {
  display: 'flex',
  flexWrap: 'wrap',
  alignContent: 'flex-start',
  gap: '8px',
  padding: '8px',
  maxHeight: '100%',
  maxWidth: '100%',
  overflowY: 'auto',
};

const cardStyle: CSS.Properties = {
  border: '1px solid #e2e8f0',
  borderRadius: '8px',
  overflow: 'hidden',
  background: '#fff',
  cursor: 'pointer',
  width: '160px',
};

const selectedCardStyle: CSS.Properties = { ...cardStyle, border: '3px solid red' };
const imageRowStyle: CSS.Properties = { display: 'flex', gap: '2px', background: '#f1f5f9' };
const imgStyle: CSS.Properties = {
  flex: '1 1 0',
  minWidth: 0,
  height: '90px',
  objectFit: 'cover',
  display: 'block',
};
const captionStyle: CSS.Properties = { padding: '6px 8px', fontSize: '10px', color: '#64748b' };
const fieldStyle: CSS.Properties = {
  display: 'block',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
};

/**
 * An `<img>` for one cell. A same-origin `/api/...` image is fetched with the
 * token; see useAuthedObjectUrl. A collection's file is read through the
 * canvas's dataflow (`collectionMediaPath`).
 */
function FrameImage({ source, alt, dataflowId }: { source: ImageSource; alt: string; dataflowId: string | null }) {
  const authed = useAuthedObjectUrl(source.kind === 'authed' ? collectionMediaPath(source.path, dataflowId) : null);
  const src = source.kind === 'direct' ? source.src : authed.url;
  if (!src) {
    // Still fetching, or the fetch failed. Hold the slot either way so the
    // card does not reflow under the user.
    return <div style={{ ...imgStyle, background: authed.failed ? '#e2e8f0' : '#f8fafc' }} />;
  }
  return (
    <img
      src={src}
      alt={alt}
      style={imgStyle}
      onError={(e) => {
        (e.target as HTMLImageElement).style.background = '#e2e8f0';
      }}
    />
  );
}

/** A collection row that plays: a video or a recording, named by its ids. */
function playable(row: Record<string, unknown>): { datasetId: string; fileId: string; kind: 'video' | 'audio' } | null {
  const { kind, dataset_id: datasetId, file_id: fileId } = row;
  if ((kind !== 'video' && kind !== 'audio') || typeof datasetId !== 'string' || typeof fileId !== 'string') {
    return null;
  }
  return { datasetId, fileId, kind };
}

const playButtonStyle: CSS.Properties = {
  position: 'absolute',
  left: '6px',
  bottom: '6px',
  border: 0,
  borderRadius: '10px',
  padding: '2px 8px',
  fontSize: '10px',
  fontWeight: 600,
  background: 'rgba(15, 23, 42, 0.75)',
  color: '#fff',
  cursor: 'pointer',
};

/**
 * A failure this close to a link's lapse, or after it, is taken for the
 * lapse: the page counts a link's life from when the link arrives, a little
 * after the backend started counting.
 */
const LAPSE_MARGIN_MS = 60_000;

/** Where a player stands: its time, whether it plays, and its speed. */
interface PlayerPlace {
  at: number;
  playing: boolean;
  rate: number;
}

/** A signed link, and when it lapses by this page's clock. */
interface MediaLink {
  url: string;
  lapsesAt: number;
  /** Where the player stood when the link before this one lapsed; null for
   *  the first link, which plays from the start. */
  resume: PlayerPlace | null;
}

const playerStyle: CSS.Properties = { width: '100%', display: 'block' };

/**
 * Plays one file. `<video>` and `<audio>` cannot send the token, so the
 * backend is asked for a short-lived signed link first. The backend checks
 * the link on every range the element fetches, so once the link lapses, a
 * seek or the next range of a long play fails: the player then asks for a
 * fresh link and goes on from where it stood, playing or paused. A failure
 * while the link is still good is the file's own, and stops the player.
 */
function Player({ datasetId, fileId, kind, dataflowId }: {
  datasetId: string;
  fileId: string;
  kind: 'video' | 'audio';
  dataflowId: string | null;
}) {
  const [link, setLink] = useState<MediaLink | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Set when a link lapses: asks for the next one, which resumes there.
  const [lapse, setLapse] = useState<PlayerPlace | null>(null);
  // Where the player stands, from its own events: what a browser reports
  // once a fetch has failed is not the same in every browser.
  const stands = useRef({ at: 0, playing: false });

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ url: string; expiresIn: number }>(
      collectionMediaPath(
        `/api/datasets/${encodeURIComponent(datasetId)}/media/${encodeURIComponent(fileId)}/link`,
        dataflowId,
      ),
      { method: 'POST' },
    )
      .then((res) => {
        if (cancelled) return;
        // A link whose answer gives no life is never taken for lapsed.
        const life = Number.isFinite(res.expiresIn) ? res.expiresIn * 1000 : Infinity;
        setLink({ url: `${backendUrl()}${res.url}`, lapsesAt: Date.now() + life, resume: lapse });
      })
      .catch((err: Error) => !cancelled && setError(err.message || 'This file cannot be played.'));
    return () => {
      cancelled = true;
    };
  }, [datasetId, fileId, dataflowId, lapse]);

  if (error) return <div style={{ ...captionStyle, color: '#b42318' }}>{error}</div>;
  if (!link) return <div style={{ ...imgStyle, background: '#f8fafc' }} />;
  const media = {
    src: link.url,
    controls: true,
    // A fresh link starts where the lapsed one stood, playing only if it played.
    autoPlay: link.resume === null,
    style: playerStyle,
    onPlay: () => {
      stands.current.playing = true;
    },
    onPause: () => {
      stands.current.playing = false;
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      stands.current.at = e.currentTarget.currentTime;
    },
    onSeeking: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      stands.current.at = e.currentTarget.currentTime;
    },
    onError: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      if (Date.now() < link.lapsesAt - LAPSE_MARGIN_MS) return;
      setLapse({ ...stands.current, rate: e.currentTarget.playbackRate });
    },
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      const resume = link.resume;
      if (!resume) return;
      const element = e.currentTarget;
      element.currentTime = resume.at;
      element.playbackRate = resume.rate;
      // A start the browser refuses leaves the player paused there.
      if (resume.playing) Promise.resolve(element.play()).catch(() => undefined);
    },
  };
  return kind === 'video' ? <video {...media} /> : <audio {...media} />;
}

const pagerStyle: CSS.Properties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'flex-end',
  gap: '8px',
  width: '100%',
  fontSize: '11px',
  color: '#64748b',
};

/** What makes a frame a different one: how many rows, and which comes first. */
function frameKey(rows: Record<string, unknown>[]): string {
  const head = rows[0] ?? {};
  const id = head.file_id ?? head.path ?? head.image_url ?? head.thumbnail ?? '';
  return `${rows.length}:${String(id)}`;
}

export default function ImageCardGrid({
  nodeId,
  rows,
  imageColumns,
  interacted,
  onClickRow,
  dataflowId = null,
}: ImageCardGridProps) {
  const [page, setPage] = useState(0);
  const [playing, setPlaying] = useState<number | null>(null);
  // A new frame starts on its first page. A selection written back onto the
  // same rows is not a new frame, so the page and the player stay.
  const frame = frameKey(rows);
  useEffect(() => {
    setPage(0);
    setPlaying(null);
  }, [frame]);

  const captionColumns = (row: Record<string, unknown>) =>
    Object.keys(row).filter((c) => !imageColumns.includes(c) && c !== 'interacted');
  const pages = Math.max(1, Math.ceil(rows.length / CARD_PAGE_SIZE));
  const first = Math.min(page, pages - 1) * CARD_PAGE_SIZE;
  const shown = rows.slice(first, first + CARD_PAGE_SIZE);

  return (
    <div className="nowheel nodrag" id={`imageBox_content_${nodeId}`} style={containerStyle}>
      {shown.map((row, offset) => {
        const index = first + offset;
        const isSelected =
          interacted != null && interacted.length === rows.length && interacted[index] === '1';
        const media = playable(row);

        return (
          <div
            key={index}
            id={`imageBox_content_${nodeId}_${index}`}
            style={isSelected ? selectedCardStyle : cardStyle}
            onClick={() => onClickRow(index)}
          >
            {media && playing === index ? (
              <div onClick={(e) => e.stopPropagation()}>
                {/* One player per file and dataflow: where it stood belongs to that file. */}
                <Player
                  key={`${media.datasetId}/${media.fileId}/${dataflowId ?? ''}`}
                  {...media}
                  dataflowId={dataflowId}
                />
              </div>
            ) : (
              <div style={{ ...imageRowStyle, position: 'relative' }}>
                {imageColumns.flatMap((column) =>
                  // A cell can hold several images; see resolveImageSources.
                  resolveImageSources(row[column]).map((source, i) => (
                    <FrameImage
                      key={`${column}-${i}`}
                      source={source}
                      alt={`${column} ${index}`}
                      dataflowId={dataflowId}
                    />
                  )),
                )}
                {media ? (
                  <button
                    type="button"
                    style={playButtonStyle}
                    aria-label={`Play ${String(row.name ?? media.kind)}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      setPlaying(index);
                    }}
                  >
                    ▶ Play
                  </button>
                ) : null}
              </div>
            )}
            <div style={captionStyle}>
              {captionColumns(row).slice(0, 4).map((column) => (
                <span key={column} style={fieldStyle} data-tooltip={`${column}: ${String(row[column])}`}>
                  {column}: {row[column] == null ? 'null' : String(row[column])}
                </span>
              ))}
            </div>
          </div>
        );
      })}
      {pages > 1 ? (
        <div style={pagerStyle}>
          <span>
            {(first + 1).toLocaleString()} to {(first + shown.length).toLocaleString()} of{' '}
            {rows.length.toLocaleString()}
          </span>
          <button type="button" disabled={first === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
            Previous
          </button>
          <button
            type="button"
            disabled={first + CARD_PAGE_SIZE >= rows.length}
            onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
