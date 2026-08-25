/**
 * THE frontend node-appearance utility (memo dev/89 §3) — the
 * constant-for-constant mirror of the backend's
 * `utk_curio/backend/app/packages/node_appearance.py`. One validation /
 * normalization / derivation truth per layer; behaviors and controls never
 * re-implement color rules.
 *
 * Contract: a named palette (yellow default, pink, blue, green, orange,
 * lavender) mapped centrally to design-token hexes, plus six-digit `#RRGGBB`
 * custom colors only. Shorthand hex, alpha, CSS expressions, and whitespace
 * are refused; a background no foreground can read at WCAG AA (4.5:1) is
 * invalid. Legacy tolerance lives ONLY in {@link resolveBackground}: stored
 * junk renders as the default yellow, never as unreadable ink.
 */

export const NAMED_COLORS: Record<string, string> = {
  yellow: "#fef3c0",
  pink: "#fbd3e0",
  blue: "#cfe8f7",
  green: "#d5f0d1",
  orange: "#ffddc0",
  lavender: "#e4dcf7",
};

export const DEFAULT_COLOR_NAME = "yellow";
export const DEFAULT_BACKGROUND = NAMED_COLORS[DEFAULT_COLOR_NAME];

/** WCAG AA for normal text. */
export const MIN_CONTRAST = 4.5;

const DARK_FOREGROUND = "#1f2430";
const LIGHT_FOREGROUND = "#ffffff";
const LINK_ON_LIGHT = "#1d4ed8";
const LINK_ON_DARK = "#93c5fd";

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

export type NodeAppearance = { backgroundColor: string };

export type DerivedColors = {
  background: string;
  foreground: string;
  mutedForeground: string;
  border: string;
  link: string;
  focus: string;
};

function rgb(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

function toHex(channels: [number, number, number]): string {
  return (
    "#" +
    channels
      .map((c) => Math.max(0, Math.min(255, Math.round(c))).toString(16).padStart(2, "0"))
      .join("")
  );
}

function luminance(hex: string): number {
  const lin = (channel: number) => {
    const s = channel / 255;
    return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const [r, g, b] = rgb(hex);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** WCAG contrast ratio between two `#RRGGBB` colors. */
export function contrastRatio(hexA: string, hexB: string): number {
  const la = luminance(hexA);
  const lb = luminance(hexB);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

function bestForeground(background: string): { foreground: string; ratio: number } {
  const dark = contrastRatio(background, DARK_FOREGROUND);
  const light = contrastRatio(background, LIGHT_FOREGROUND);
  return dark >= light
    ? { foreground: DARK_FOREGROUND, ratio: dark }
    : { foreground: LIGHT_FOREGROUND, ratio: light };
}

/**
 * Normalize one requested background to a lowercase `#RRGGBB`, or return the
 * refusal reason. Mirrors the backend: palette names (case-insensitive) or
 * six-digit hex only; whitespace, shorthand, alpha, CSS expressions, and
 * AA-unreachable colors are refused.
 */
export function normalizeBackground(
  value: unknown,
): { ok: true; value: string } | { ok: false; reason: string } {
  if (typeof value !== "string" || !value) {
    return {
      ok: false,
      reason: `Pick a palette color (${Object.keys(NAMED_COLORS).sort().join(", ")}) or a six-digit #RRGGBB hex.`,
    };
  }
  if (/\s/.test(value)) {
    return { ok: false, reason: "The color must not contain whitespace." };
  }
  const named = NAMED_COLORS[value.toLowerCase()];
  if (named !== undefined) return { ok: true, value: named };
  if (!HEX_RE.test(value)) {
    return {
      ok: false,
      reason:
        "Not a palette name or six-digit #RRGGBB hex (shorthand hex, alpha, and CSS expressions are not supported).",
    };
  }
  const normalized = value.toLowerCase();
  const { ratio } = bestForeground(normalized);
  if (ratio < MIN_CONTRAST) {
    return {
      ok: false,
      reason: `That color can't show readable text (best contrast ${ratio.toFixed(2)}:1, needs ${MIN_CONTRAST}:1) — pick a lighter or darker color.`,
    };
  }
  return { ok: true, value: normalized };
}

/**
 * Render-path tolerance (the ONLY quiet fallback): a stored value that is
 * missing or no longer valid renders as the default yellow.
 */
export function resolveBackground(stored: unknown): string {
  const result = normalizeBackground(stored);
  return result.ok ? result.value : DEFAULT_BACKGROUND;
}

function shade(hex: string, factor: number): string {
  const [r, g, b] = rgb(hex);
  if (factor <= 1) return toHex([r * factor, g * factor, b * factor]);
  const t = Math.min(1, factor - 1);
  return toHex([r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t]);
}

/**
 * Foreground, muted text, border, link, and focus colors for one background —
 * every pair AA-safe by construction (mirrors the backend derivation).
 * Computed at render time, never persisted.
 */
export function derivedColors(background: unknown): DerivedColors {
  const bg = resolveBackground(background);
  const { foreground } = bestForeground(bg);
  const darkInk = foreground === DARK_FOREGROUND;
  let link = darkInk ? LINK_ON_LIGHT : LINK_ON_DARK;
  if (contrastRatio(bg, link) < MIN_CONTRAST) link = foreground;
  const [fr, fg, fb] = rgb(foreground);
  const [br, bgc, bb] = rgb(bg);
  let muted = foreground;
  for (const mix of [0.25, 0.15, 0]) {
    const candidate = toHex([
      fr + (br - fr) * mix,
      fg + (bgc - fg) * mix,
      fb + (bb - fb) * mix,
    ]);
    if (contrastRatio(bg, candidate) >= MIN_CONTRAST) {
      muted = candidate;
      break;
    }
  }
  return {
    background: bg,
    foreground,
    mutedForeground: muted,
    border: shade(bg, darkInk ? 0.82 : 1.35),
    link,
    focus: foreground,
  };
}
