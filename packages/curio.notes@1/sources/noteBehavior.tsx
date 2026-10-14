import React from 'react';
import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';

/**
 * Note: a post-it on the canvas.
 *
 * The node's content is its text (`data.code`, also read as `data.content`)
 * and `data.appearance.backgroundColor` its color, as the Researcher agent
 * writes them. The text is simple markdown, drawn as React elements, never as
 * HTML: `#`/`##` headings, `- ` bullets, `**bold**`, and `[label](https://…)`
 * links (any other link is shown as text). A note runs nothing: it has no
 * handles, and a run counts it done at once (`disablePlay`).
 */

const PALETTE: Record<string, string> = {
  yellow: '#fff3b0',
  pink: '#ffd6e0',
  blue: '#cfe8ff',
  green: '#d5f5d0',
  orange: '#ffe0b8',
  lavender: '#e6dcff',
};

const HEX = /^#[0-9a-fA-F]{6}$/;

export function noteColor(raw: unknown): string {
  if (typeof raw !== 'string') return PALETTE.yellow;
  const key = raw.trim().toLowerCase();
  if (PALETTE[key]) return PALETTE[key];
  return HEX.test(raw.trim()) ? raw.trim() : PALETTE.yellow;
}

/** Dark text on a light note, light text on a dark one. */
export function textColor(background: string): string {
  const n = parseInt(background.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? '#1e1f23' : '#ffffff';
}

const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

/** One line's bold spans and links, as React elements. */
export function inline(text: string, keyPrefix: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE)) {
    const at = match.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const token = match[0];
    const key = `${keyPrefix}-${index++}`;
    if (token.startsWith('**')) {
      out.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else {
      const label = token.slice(1, token.indexOf(']('));
      const href = token.slice(token.indexOf('](') + 2, -1);
      out.push(
        /^https:\/\//.test(href)
          ? <a key={key} href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>{label}</a>
          : `${label} (${href})`,
      );
    }
    last = at + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** The note's text as blocks: headings, bullet lists and paragraphs. */
export function renderMarkdown(text: string): React.ReactNode[] {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (!bullets.length) return;
    const at = blocks.length;
    blocks.push(
      <ul key={`ul-${at}`} style={{ margin: '4px 0', paddingLeft: 18 }}>
        {bullets.map((item, i) => <li key={i}>{inline(item, `li-${at}-${i}`)}</li>)}
      </ul>,
    );
    bullets = [];
  };
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = raw.trimEnd();
    if (/^\s*[-*] /.test(line)) {
      bullets.push(line.replace(/^\s*[-*] /, ''));
      return;
    }
    flush();
    if (!line.trim()) return;
    const heading = line.match(/^(#{1,3}) (.*)$/);
    if (heading) {
      blocks.push(
        <div key={`h-${i}`} style={{ fontWeight: 700, fontSize: heading[1].length === 1 ? 15 : 13, margin: '6px 0 2px' }}>
          {inline(heading[2], `h-${i}`)}
        </div>,
      );
      return;
    }
    blocks.push(<p key={`p-${i}`} style={{ margin: '4px 0' }}>{inline(line, `p-${i}`)}</p>);
  });
  flush();
  return blocks;
}

export const useNoteBehavior: NodeBehaviorHook = (data) => {
  const raw = (data as any)?.content ?? (data as any)?.code;
  const text = typeof raw === 'string' ? raw : '';
  const background = noteColor((data as any)?.appearance?.backgroundColor);
  const color = textColor(background);
  return {
    disablePlay: true,
    handlesOverride: [],
    contentComponent: (
      <div
        className="nowheel"
        data-testid="curio-note"
        style={{
          background,
          color,
          borderRadius: 6,
          padding: '10px 12px',
          fontSize: 12.5,
          lineHeight: 1.45,
          maxHeight: 360,
          overflowY: 'auto',
          boxShadow: '0 2px 6px rgba(0, 0, 0, 0.12)',
        }}
      >
        {text.trim() ? renderMarkdown(text) : <span style={{ opacity: 0.6 }}>An empty note.</span>}
      </div>
    ),
  };
};
