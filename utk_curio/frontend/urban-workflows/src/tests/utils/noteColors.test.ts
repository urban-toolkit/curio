/**
 * A Note's colors follow the backend's node-appearance rule
 * (`packages/domain/node_appearance.py`), which an agent's notes are saved
 * through: the palette is generated from it, and a color it would refuse
 * renders as the default yellow. The expected values here are what its
 * `derived_colors` returns for the same input.
 */
import { NOTE_COLORS } from "../../generated/noteColors";
import { noteColors } from "../../utils/noteColors";

describe("a note's colors", () => {
  test("a palette name is the backend's color for it, in any case", () => {
    expect(noteColors("green").background).toBe(NOTE_COLORS.green);
    expect(noteColors("GREEN").background).toBe(NOTE_COLORS.green);
    expect(NOTE_COLORS).toEqual({
      yellow: "#fef3c0",
      pink: "#fbd3e0",
      blue: "#cfe8f7",
      green: "#d5f0d1",
      orange: "#ffddc0",
      lavender: "#e4dcf7",
    });
  });

  test("dark ink and a blue link on a light note", () => {
    expect(noteColors("green")).toEqual({ background: "#d5f0d1", foreground: "#1f2430", link: "#1d4ed8" });
  });

  test("white ink and a light link on a dark note", () => {
    expect(noteColors("#123456")).toEqual({ background: "#123456", foreground: "#ffffff", link: "#93c5fd" });
    expect(noteColors("#D5F0D1").background).toBe("#d5f0d1");
  });

  test("a link no light blue can be read on takes the ink", () => {
    expect(noteColors("#767676")).toEqual({ background: "#767676", foreground: "#ffffff", link: "#ffffff" });
  });

  test("a color the backend refuses renders as the default yellow", () => {
    // No ink reaches 4.5:1 on it (4.48:1 at best).
    expect(noteColors("#777777").background).toBe(NOTE_COLORS.yellow);
    for (const bad of [
      undefined, null, 42, "", "red; background: url(x)", "#fff", " green", "rgb(0,0,0)", "constructor", "toString",
    ]) {
      expect(noteColors(bad).background).toBe(NOTE_COLORS.yellow);
    }
  });
});
