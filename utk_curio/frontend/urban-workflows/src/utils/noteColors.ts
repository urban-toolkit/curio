/**
 * A Note's colors: its background, the ink of its text and the color of its
 * links, by the backend's node-appearance rule
 * (`backend/app/packages/domain/node_appearance.py`), through which an agent's
 * note is saved. The palette and the inks come from it (`generated/noteColors`);
 * a value the rule would refuse (not a palette name or a six-digit hex, or a
 * color no ink can be read on) draws as the default yellow, as there.
 */
import {
  DEFAULT_NOTE_COLOR,
  NOTE_COLORS,
  NOTE_INKS,
  NOTE_LINKS,
  NOTE_MIN_CONTRAST,
} from "../generated/noteColors";

export interface NoteColors {
  background: string;
  foreground: string;
  link: string;
}

const HEX = /^#[0-9a-fA-F]{6}$/;

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => {
    const s = parseInt(hex.slice(at, at + 2), 16) / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** The WCAG contrast ratio of two `#rrggbb` colors. */
export function contrastRatio(a: string, b: string): number {
  const [la, lb] = [luminance(a), luminance(b)];
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** The ink that reads better on *background*, and how well. */
function bestInk(background: string): [string, number] {
  const dark = contrastRatio(background, NOTE_INKS.dark);
  const light = contrastRatio(background, NOTE_INKS.light);
  return dark >= light ? [NOTE_INKS.dark, dark] : [NOTE_INKS.light, light];
}

/** The `#rrggbb` a stored color stands for, or null where the rule refuses it. */
export function noteBackground(value: unknown): string | null {
  if (typeof value !== "string" || !value || /\s/.test(value)) return null;
  const name = value.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(NOTE_COLORS, name)) {
    return NOTE_COLORS[name as keyof typeof NOTE_COLORS];
  }
  if (!HEX.test(value)) return null;
  return bestInk(name)[1] >= NOTE_MIN_CONTRAST ? name : null;
}

/** What a note with this stored color draws in. */
export function noteColors(stored: unknown): NoteColors {
  const background = noteBackground(stored) ?? DEFAULT_NOTE_COLOR;
  const [foreground] = bestInk(background);
  const preferred = foreground === NOTE_INKS.dark ? NOTE_LINKS.onLight : NOTE_LINKS.onDark;
  const link = contrastRatio(background, preferred) >= NOTE_MIN_CONTRAST ? preferred : foreground;
  return { background, foreground, link };
}
