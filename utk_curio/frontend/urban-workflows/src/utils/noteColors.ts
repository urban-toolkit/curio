/**
 * A Note's colors: its background, the ink of its text and the color of its
 * links, by the backend's node-appearance rule
 * (`backend/app/packages/domain/node_appearance.py`), through which an agent's
 * note is saved. The palette, the inks, the links and the contrast are
 * `contracts/noteColors.json`, which that rule reads too; a value the rule
 * would refuse (not a palette name or a six-digit hex, or a color no ink can
 * be read on) draws as the default yellow, as there.
 */
import noteColorsFile from "../contracts/noteColors.json";

/** The colors a note's appearance can name, and the color each stands for. */
export const NOTE_COLORS = noteColorsFile.colors;

/** A palette color's name. */
export type NoteColorName = keyof typeof NOTE_COLORS;

/** The color of a note that names none, or names one that cannot be read. */
const DEFAULT_NOTE_COLOR = NOTE_COLORS[noteColorsFile.defaultColor as NoteColorName];

/** A note's text takes the ink that reads better on its color. */
const NOTE_INKS = noteColorsFile.inks;

/** A link's color under dark ink and under light ink, when it reads; else the ink. */
const NOTE_LINKS = noteColorsFile.links;

/** The contrast an ink must reach on a note's color; no ink reaching it refuses the color. */
const NOTE_MIN_CONTRAST = noteColorsFile.minContrast;

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
    return NOTE_COLORS[name as NoteColorName];
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
