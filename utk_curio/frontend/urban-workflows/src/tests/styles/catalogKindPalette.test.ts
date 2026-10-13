import fs from "fs";
import path from "path";

import { CATALOG_KIND_META } from "../../components/catalog/CatalogKindVisuals";
import { declaredValue } from "../_support/cssRules";

/**
 * The catalog kinds whose cards all wear one colour: a Discovery source, a
 * model and a scenario.
 *
 * Each kind has three colours: a fill, for its cards' strip and selected
 * border, with a white label on the strip; a tint; and the text that sits on
 * the tint, for its kind icon. `token` and `contrast` are the ones
 * confirmDialogButtons.test.ts uses.
 */
const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");
const TOKENS = read("styles/curioTokens.css");
const KIND_ICONS = read("components/catalog/CatalogKindVisuals.module.css");

const KINDS = ["source", "model", "scenario"] as const;

function token(name: string): string {
  const match = TOKENS.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!match) throw new Error(`no ${name} in curioTokens.css`);
  return match[1];
}

/** WCAG 2 contrast ratio of two #rrggbb colours. */
function contrast(a: string, b: string): number {
  const luminance = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe.each(KINDS)("the %s kind colours", (kind) => {
  it("are declared: a fill, a tint and the text on the tint", () => {
    for (const part of ["fg", "bg", "on-tint"]) {
      expect(token(`--curio-kind-${kind}-${part}`)).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it("hold the white strip label on the fill", () => {
    // A margin over AA's 4.5:1: the label is small capitals in 92% white.
    expect(contrast("#ffffff", token(`--curio-kind-${kind}-fg`))).toBeGreaterThanOrEqual(5.0);
  });

  it("hold the kind icon's glyph on the tint", () => {
    expect(
      contrast(token(`--curio-kind-${kind}-on-tint`), token(`--curio-kind-${kind}-bg`)),
    ).toBeGreaterThanOrEqual(4.5);
  });
});

describe("the kind icon", () => {
  it.each(["model", "scenario"])("of a %s wears its kind's tint", (kind) => {
    expect(declaredValue(KIND_ICONS, `.kindIcon_${kind}`, "background")).toBe(
      `var(--curio-kind-${kind}-bg)`,
    );
    expect(declaredValue(KIND_ICONS, `.kindIcon_${kind}`, "color")).toBe(
      `var(--curio-kind-${kind}-on-tint)`,
    );
  });

  it("of a source wears the source tint, under the class its kind key names", () => {
    // CatalogKindIcon's class is `kindIcon_<kind>`, and a source's kind key is
    // `source`: a rule under any name that is not a kind key never applies.
    expect(Object.keys(CATALOG_KIND_META)).toContain("source");
    expect(declaredValue(KIND_ICONS, ".kindIcon_source", "background")).toBe(
      "var(--curio-kind-source-bg)",
    );
    expect(declaredValue(KIND_ICONS, ".kindIcon_source", "color")).toBe(
      "var(--curio-kind-source-on-tint)",
    );

    const rules = KIND_ICONS.replace(/\/\*[\s\S]*?\*\//g, "");
    const named: string[] = [];
    const kindClass = /\.kindIcon_([A-Za-z0-9]+)/g;
    let match: RegExpExecArray | null;
    while ((match = kindClass.exec(rules)) !== null) named.push(match[1]);
    expect(named.filter((key) => !(key in CATALOG_KIND_META))).toEqual([]);
  });
});
