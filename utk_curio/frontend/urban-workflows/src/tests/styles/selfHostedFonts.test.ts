import fs from "fs";
import path from "path";

/**
 * The app must not fetch fonts from a third party at page load.
 *
 * Rubik used to arrive from fonts.googleapis.com via a <link> in index.html,
 * which made the TYPEFACE depend on a CDN being reachable when the page
 * loaded. Two ways that bit, both seen:
 *
 * - The e2e screenshot baselines. A capture taken while the fetch had not
 *   landed renders in a system fallback, so it disagrees with every later run
 *   for a reason no diff percentage explains.
 * - The e2e suite's wall clock. The harness waits up to WEBFONT_TIMEOUT_MS
 *   (15s) per capture for document.fonts to settle, and that wait is swallowed
 *   rather than raised. With the CDN unreachable every capture paid the full
 *   15s silently, which is what pushed test_package_metadata_roundtrip_e2e
 *   past its 120s response budget twice on one branch.
 *
 * The fix was to vendor the exact woff2 files Google served and declare them
 * locally, so this test pins both halves: no remote font URL anywhere under
 * src/, and every @font-face src in fonts.css resolving to a file that is
 * actually in the repo. A declaration pointing at a missing file fails the
 * same way the CDN did, just without the network.
 */

const SRC = path.resolve(__dirname, "../..");
const FONTS_CSS = path.join(SRC, "styles", "fonts.css");

const EXTENSIONS = new Set([".css", ".ts", ".tsx", ".html"]);
const SKIP_DIRS = new Set(["node_modules", "dist", "assets"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      walk(path.join(dir, entry.name), out);
    } else if (EXTENSIONS.has(path.extname(entry.name))) {
      out.push(path.join(dir, entry.name));
    }
  }
  return out;
}

describe("fonts are self-hosted", () => {
  it("no source file fetches a font from a remote host", () => {
    // Matches a real URL, not prose: the comment in fonts.css names
    // fonts.googleapis.com to explain why it is gone, and that must stay legal.
    const REMOTE_FONT_URL =
      /(?:href|src|url\()\s*=?\s*["'(]?\s*https?:\/\/fonts\.(?:googleapis|gstatic)\.com/i;

    const offenders = walk(SRC)
      .filter((file) => REMOTE_FONT_URL.test(fs.readFileSync(file, "utf8")))
      .map((file) => path.relative(SRC, file));

    expect(offenders).toEqual([]);
  });

  it("every @font-face points at a woff2 that exists in the repo", () => {
    const css = fs.readFileSync(FONTS_CSS, "utf8");
    const urls = [...css.matchAll(/src:\s*url\(['"]?([^'")]+)['"]?\)/g)].map(
      (match) => match[1],
    );

    // Guards the guard: if fonts.css is ever emptied or renamed, an empty list
    // would otherwise pass this test silently.
    expect(urls.length).toBeGreaterThan(0);

    const missing = urls.filter(
      (url) => !fs.existsSync(path.resolve(path.dirname(FONTS_CSS), url)),
    );

    expect(missing).toEqual([]);
  });

  it("declares Rubik at the three weights the app asks for", () => {
    const css = fs.readFileSync(FONTS_CSS, "utf8");
    const weights = new Set(
      [...css.matchAll(/font-weight:\s*(\d+)/g)].map((match) => match[1]),
    );

    // styles.tsx, curioTokens.css and the auth/menu components all ask for
    // Rubik; 300/400/600 are the weights the old CDN request carried.
    expect([...weights].sort()).toEqual(["300", "400", "600"]);
  });
});
