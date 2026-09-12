import React, { useEffect, useState } from 'react';
import CSS from 'csstype';
import { ImageSource, resolveImageSource } from '../../../utils/imageColumns';
import { backendUrl } from '../../../utils/backendUrl';
import { getToken } from '../../../utils/authApi';

/**
 * One card per row: every image column of that row side by side, above the
 * row's remaining values (#276).
 *
 * This replaces a bare 50px thumbnail grid. The card shape is what the retired
 * CV Gallery showed - a picture is rarely useful without the row that produced
 * it - and it generalises: any frame with an image column plus attributes
 * reads the same way.
 */

interface ImageCardGridProps {
  nodeId: string;
  rows: Record<string, unknown>[];
  /** Columns to draw as images, in order; the rest become the card's caption. */
  imageColumns: string[];
  /** Parallel to `rows`: '1' marks a row selected from a linked Data Pool. */
  interacted: string[];
  onClickRow: (rowIndex: number) => void;
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
 * An `<img>` for one cell.
 *
 * A same-origin `/api/...` image is served by Curio's backend, which resolves
 * WHICH user is asking from the bearer token - and a bare `<img src>` cannot
 * send a header, so it would resolve to the shared guest and 404 for everyone
 * signed in. Fetch those with the token and hand the DOM an object URL.
 */
function FrameImage({ value, alt }: { value: unknown; alt: string }) {
  const source: ImageSource | null = resolveImageSource(value);
  const authedPath = source?.kind === 'authed' ? source.path : null;
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!authedPath) return;
    let revoked: string | null = null;
    let cancelled = false;
    setObjectUrl(null);
    setFailed(false);
    const token = getToken();
    fetch(`${backendUrl()}${authedPath}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((blob) => {
        if (cancelled) return;
        revoked = URL.createObjectURL(blob);
        setObjectUrl(revoked);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    // Revoke on unmount and whenever the path changes, or every re-render
    // leaks a blob for the lifetime of the document.
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [authedPath]);

  if (!source) return null;
  const src = source.kind === 'direct' ? source.src : objectUrl;
  if (!src) {
    // Still fetching, or the fetch failed. Hold the slot either way so the
    // card does not reflow under the user.
    return <div style={{ ...imgStyle, background: failed ? '#e2e8f0' : '#f8fafc' }} />;
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

export default function ImageCardGrid({
  nodeId,
  rows,
  imageColumns,
  interacted,
  onClickRow,
}: ImageCardGridProps) {
  const captionColumns = (row: Record<string, unknown>) =>
    Object.keys(row).filter((c) => !imageColumns.includes(c) && c !== 'interacted');

  return (
    <div className="nowheel nodrag" id={`imageBox_content_${nodeId}`} style={containerStyle}>
      {rows.map((row, index) => {
        const isSelected =
          interacted != null && interacted.length === rows.length && interacted[index] === '1';

        return (
          <div
            key={index}
            id={`imageBox_content_${nodeId}_${index}`}
            style={isSelected ? selectedCardStyle : cardStyle}
            onClick={() => onClickRow(index)}
          >
            <div style={imageRowStyle}>
              {imageColumns.map((column) => (
                <FrameImage key={column} value={row[column]} alt={`${column} ${index}`} />
              ))}
            </div>
            <div style={captionStyle}>
              {captionColumns(row).slice(0, 4).map((column) => (
                <span key={column} style={fieldStyle} title={`${column}: ${String(row[column])}`}>
                  {column}: {row[column] == null ? 'null' : String(row[column])}
                </span>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
