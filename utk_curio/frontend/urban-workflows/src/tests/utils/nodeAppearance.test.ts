/**
 * dev/89 commit 8 — the frontend node-appearance utility, the
 * constant-for-constant mirror of the backend's node_appearance.py: palette
 * mapping, hex normalization, refusals, legacy fallback, AA-safe derivations.
 */

import {
  DEFAULT_BACKGROUND,
  MIN_CONTRAST,
  NAMED_COLORS,
  contrastRatio,
  derivedColors,
  normalizeBackground,
  resolveBackground,
} from "../../utils/nodeAppearance";

describe("nodeAppearance", () => {
  it("mirrors the backend palette exactly (one truth per layer)", () => {
    // These hexes MUST match utk_curio/backend/app/packages/node_appearance.py
    // — a drifted constant breaks the round-trip contract.
    expect(NAMED_COLORS).toEqual({
      yellow: "#fef3c0",
      pink: "#fbd3e0",
      blue: "#cfe8f7",
      green: "#d5f0d1",
      orange: "#ffddc0",
      lavender: "#e4dcf7",
    });
    expect(DEFAULT_BACKGROUND).toBe("#fef3c0");
  });

  it("normalizes palette names case-insensitively and hex to lowercase", () => {
    expect(normalizeBackground("PINK")).toEqual({ ok: true, value: "#fbd3e0" });
    expect(normalizeBackground("#AABBCC")).toEqual({ ok: true, value: "#aabbcc" });
  });

  it.each([
    "#abc", "#aabbccdd", "rgb(1,2,3)", "linear-gradient(red, blue)",
    "url(x)", "red", " #aabbcc", "#aab bcc", "", undefined, 42,
  ])("refuses %p", (bad) => {
    expect(normalizeBackground(bad as never).ok).toBe(false);
  });

  it("refuses AA-unreachable backgrounds with the contrast reason", () => {
    const result = normalizeBackground("#777777");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("readable text");
  });

  it("resolveBackground falls back quietly for legacy junk only", () => {
    expect(resolveBackground(undefined)).toBe(DEFAULT_BACKGROUND);
    expect(resolveBackground("#777777")).toBe(DEFAULT_BACKGROUND);
    expect(resolveBackground("green")).toBe(NAMED_COLORS.green);
  });

  it.each([...Object.keys(NAMED_COLORS), "#336699", "#1a1a2e"])(
    "derives AA-safe colors for %s",
    (value) => {
      const d = derivedColors(value);
      expect(contrastRatio(d.background, d.foreground)).toBeGreaterThanOrEqual(MIN_CONTRAST);
      expect(contrastRatio(d.background, d.mutedForeground)).toBeGreaterThanOrEqual(MIN_CONTRAST);
      expect(contrastRatio(d.background, d.link)).toBeGreaterThanOrEqual(MIN_CONTRAST);
    },
  );

  it("dark backgrounds get light ink; light backgrounds get dark ink + light link", () => {
    expect(derivedColors("#1a1a2e").foreground).toBe("#ffffff");
    const light = derivedColors("yellow");
    expect(light.foreground).toBe("#1f2430");
    expect(light.link).toBe("#1d4ed8");
  });

  it("contrastRatio matches the WCAG anchors", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 1);
    expect(contrastRatio("#ffffff", "#ffffff")).toBeCloseTo(1, 2);
  });
});
