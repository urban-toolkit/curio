/**
 * Node Researcher post-it note — the dev/89 REFERENCE package behavior.
 *
 * This is the canonical source the Package Builder's reference draft ships
 * (`sources/node-researcher-note.tsx`, compiled to `scripts/behaviors.js` by
 * the pinned build service). It is deliberately self-contained: `react`
 * resolves to the HOST's window.React through the compiler's external shims,
 * and the compact appearance derivation below mirrors the shared
 * node-appearance utility's contract (same palette, same WCAG AA rule) —
 * a package bundle cannot import Curio frontend internals.
 *
 * DOD posture (dev/89 §3 "Node Researcher DOD profile"): presentation only.
 * The node's persisted content is the fixed note body (the agent copied its
 * reply/web-search summary in at proposal time); this behavior renders it as
 * safe text/markdown-lite — plain React elements, NEVER raw HTML — inside a
 * roughly square post-it whose per-instance color arrives via
 * `data.appearance.backgroundColor`. No Run control, no ports, no editor,
 * no Python, no network.
 */

import React from "react";

export const BEHAVIOR_KEY = "node-researcher-note";

/* ── appearance (compact copy of the shared node-appearance contract) ── */

const NAMED_COLORS: Record<string, string> = {
  yellow: "#fef3c0",
  pink: "#fbd3e0",
  blue: "#cfe8f7",
  green: "#d5f0d1",
  orange: "#ffddc0",
  lavender: "#e4dcf7",
};
const DEFAULT_BACKGROUND = NAMED_COLORS.yellow;
const MIN_CONTRAST = 4.5;
const HEX_RE = /^#[0-9a-fA-F]{6}$/;

function luminance(hex: string): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return (
    0.2126 * lin(parseInt(hex.slice(1, 3), 16)) +
    0.7152 * lin(parseInt(hex.slice(3, 5), 16)) +
    0.0722 * lin(parseInt(hex.slice(5, 7), 16))
  );
}

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

function normalize(value: unknown): string | null {
  if (typeof value !== "string" || !value || /\s/.test(value)) return null;
  const named = NAMED_COLORS[value.toLowerCase()];
  if (named) return named;
  if (!HEX_RE.test(value)) return null;
  const hex = value.toLowerCase();
  const best = Math.max(contrast(hex, "#1f2430"), contrast(hex, "#ffffff"));
  return best >= MIN_CONTRAST ? hex : null;
}

function derive(background: unknown) {
  const bg = normalize(background) ?? DEFAULT_BACKGROUND;
  const darkInk = contrast(bg, "#1f2430") >= contrast(bg, "#ffffff");
  const foreground = darkInk ? "#1f2430" : "#ffffff";
  let link = darkInk ? "#1d4ed8" : "#93c5fd";
  if (contrast(bg, link) < MIN_CONTRAST) link = foreground;
  return { bg, foreground, link, border: darkInk ? "rgba(0,0,0,0.25)" : "rgba(255,255,255,0.35)" };
}

/* ── markdown-lite: a SAFE subset rendered as React elements ──────────── */
/* Headings (#/##/###), bullet lists (- ), **bold**, and [text](https://…)
 * links. Everything else — raw HTML included — renders as literal text
 * (React escapes strings), so unsafe content is inert by construction. */

const INLINE_RE = /(\*\*[^*]+\*\*|\[[^\]]+\]\(https:\/\/[^\s)]+\))/g;

function renderInline(text: string, keyPrefix: string, linkColor: string): React.ReactNode[] {
  return text.split(INLINE_RE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (/^\*\*[^*]+\*\*$/.test(part)) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    const link = /^\[([^\]]+)\]\((https:\/\/[^\s)]+)\)$/.exec(part);
    if (link) {
      return (
        <a key={key} href={link[2]} rel="noopener noreferrer" style={{ color: linkColor }}>
          {link[1]}
        </a>
      );
    }
    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

function renderMarkdownLite(text: string, linkColor: string): React.ReactNode[] {
  const blocks: React.ReactNode[] = [];
  let bullets: React.ReactNode[] = [];
  const flushBullets = (key: string) => {
    if (!bullets.length) return;
    blocks.push(<ul key={key} style={{ margin: "4px 0", paddingLeft: 18 }}>{bullets}</ul>);
    bullets = [];
  };
  text.split(/\r?\n/).forEach((line, i) => {
    const key = `b${i}`;
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    if (heading) {
      flushBullets(`${key}-ul`);
      const level = heading[1].length;
      const size = level === 1 ? 15 : level === 2 ? 14 : 13;
      blocks.push(
        <div key={key} role="heading" aria-level={level}
             style={{ fontSize: size, fontWeight: 700, margin: "6px 0 2px" }}>
          {renderInline(heading[2], key, linkColor)}
        </div>,
      );
      return;
    }
    if (/^-\s+/.test(line)) {
      bullets.push(<li key={key}>{renderInline(line.replace(/^-\s+/, ""), key, linkColor)}</li>);
      return;
    }
    flushBullets(`${key}-ul`);
    if (line.trim()) {
      blocks.push(<p key={key} style={{ margin: "4px 0" }}>{renderInline(line, key, linkColor)}</p>);
    }
  });
  flushBullets("tail-ul");
  return blocks;
}

/* ── the post-it ──────────────────────────────────────────────────────── */

export interface NodeResearcherNoteData {
  code?: string;
  title?: string;
  appearance?: { backgroundColor?: string };
  /** Host-provided recolor sink: receives the NORMALIZED hex. When absent
   * the color row is read-only labels (the host chrome — NodeColorControl —
   * remains the first-party recolor surface). */
  onAppearanceChange?: (backgroundColor: string) => void;
}

export function NodeResearcherNote({ data }: { data: NodeResearcherNoteData }): JSX.Element {
  const text = typeof data?.code === "string" ? data.code : "";
  const colors = derive(data?.appearance?.backgroundColor);
  const title = data?.title || "Research note";
  const [hexDraft, setHexDraft] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const canRecolor = typeof data?.onAppearanceChange === "function";

  const commitHex = () => {
    if (!hexDraft.trim() || !canRecolor) return;
    const normalized = normalize(hexDraft.trim());
    if (!normalized) {
      setError("Use a palette name or an accessible six-digit #rrggbb hex.");
      return;
    }
    setError(null);
    setHexDraft("");
    data.onAppearanceChange!(normalized);
  };

  return (
    <div
      role="note"
      aria-label={title}
      style={{
        width: 260,
        minHeight: 240,
        maxHeight: 340,
        display: "flex",
        flexDirection: "column",
        background: colors.bg,
        color: colors.foreground,
        border: `1px solid ${colors.border}`,
        borderRadius: 6,
        boxShadow: "0 2px 6px rgba(0,0,0,0.18)",
        padding: 10,
        fontSize: 12.5,
        lineHeight: 1.45,
        boxSizing: "border-box",
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 6, borderBottom: `1px solid ${colors.border}`, paddingBottom: 4 }}>
        {title}
      </div>
      <div data-testid="note-body" style={{ overflowY: "auto", flex: 1, wordBreak: "break-word" }}>
        {text.trim() ? (
          renderMarkdownLite(text, colors.link)
        ) : (
          <p style={{ opacity: 0.75, fontStyle: "italic", margin: 0 }}>
            Nothing here yet — this note fills in from the agent's reply.
          </p>
        )}
      </div>
      {canRecolor && (
        <div style={{ marginTop: 8 }}>
          <div role="group" aria-label="Note color" style={{ display: "flex", gap: 4 }}>
            {Object.entries(NAMED_COLORS).map(([name, hex]) => (
              <button
                key={name}
                type="button"
                aria-label={`Set color ${name}`}
                onClick={() => { setError(null); data.onAppearanceChange!(hex); }}
                style={{
                  width: 16, height: 16, borderRadius: 4, background: hex,
                  border: colors.bg === hex ? "2px solid #1f2430" : "1px solid rgba(0,0,0,0.3)",
                  cursor: "pointer", padding: 0,
                }}
              />
            ))}
            <input
              aria-label="Custom hex color"
              value={hexDraft}
              placeholder="#rrggbb"
              maxLength={7}
              onChange={(e) => setHexDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commitHex(); } }}
              onBlur={commitHex}
              aria-invalid={error !== null}
              style={{ width: 64, fontSize: 10.5, fontFamily: "monospace",
                       border: `1px solid ${colors.border}`, borderRadius: 3, padding: "0 3px" }}
            />
          </div>
          <div role="status" aria-live="polite" style={{ fontSize: 10.5, color: colors.foreground }}>
            {error ?? ""}
          </div>
        </div>
      )}
    </div>
  );
}

/** The behavior hook (docs/EXTENDING.md §5): presentation only — no editor
 * override, no send-code, no loading state; just the note as content. */
export function useNodeResearcherNoteBehavior(data: NodeResearcherNoteData): { contentComponent: React.ReactNode } {
  return { contentComponent: <NodeResearcherNote data={data} /> };
}

/* Registration side effect — the compiled bundle's whole job. Guarded so the
 * source is also importable as a plain module (tests, host-less tooling). */
const w = typeof window !== "undefined" ? (window as unknown as {
  curio?: { registerBehavior?: (key: string, hook: unknown) => void };
}) : undefined;
if (w?.curio?.registerBehavior) {
  w.curio.registerBehavior(BEHAVIOR_KEY, useNodeResearcherNoteBehavior);
}
