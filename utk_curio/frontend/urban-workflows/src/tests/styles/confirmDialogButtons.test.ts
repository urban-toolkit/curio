import fs from "fs";
import path from "path";

/**
 * The destructive confirm button is readable, and the dialog's buttons get the
 * weight they declare (#525).
 *
 * Source-read, as in planEdgeNames.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
const SRC = path.resolve(__dirname, "../..");
const CSS = fs.readFileSync(path.join(SRC, "components/ConfirmDialog.module.css"), "utf8");
const TOKENS = fs.readFileSync(path.join(SRC, "styles/curioTokens.css"), "utf8");

function ruleBody(selector: string): string {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return "";
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

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

describe("the destructive confirm button", () => {
  it("is filled with a colour white text can be read on", () => {
    const body = ruleBody(".destructive");
    const fill = body.match(/background:\s*var\((--[\w-]+)\)/)?.[1];
    expect(fill).toBeDefined();
    expect(body).toMatch(/color:\s*#fff;/);
    // AA for normal text; the old --curio-danger fill was 2.78:1.
    expect(contrast("#ffffff", token(fill!))).toBeGreaterThanOrEqual(4.5);
  });
});

describe("the dialog buttons' weight", () => {
  it.each([".actionButton", ".ghostButton"])(
    "%s sets its weight after `font: inherit`, which would reset it",
    (selector) => {
      const body = ruleBody(selector);
      const inherit = body.indexOf("font: inherit");
      const weight = body.indexOf("font-weight");
      expect(inherit).toBeGreaterThan(-1);
      expect(weight).toBeGreaterThan(inherit);
    },
  );
});
