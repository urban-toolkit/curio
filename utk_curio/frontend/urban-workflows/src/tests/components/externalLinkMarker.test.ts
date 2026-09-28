import fs from "fs";
import path from "path";

/**
 * A text link that opens a new tab says so, with "↗", and nothing else does.
 *
 * The arrow is how the app tells you a click leaves the page. It used to be
 * applied by hand, so the same portal homepage carried it on the lake source
 * page and not in the drawer beside it, a downloaded dataset's resource link
 * had none, and AI Settings used "→" for its three key links.
 *
 * Read from disk, like the other convention tests in this directory: the claim
 * is about every file, not about one rendered tree.
 */

const SRC = path.resolve(__dirname, "../..");

/** Files whose new-tab links are not text links in the app's own chrome. */
const EXEMPT: Record<string, string> = {
  // The sign-in page's branding panel: logos, and URLs that read as URLs.
  "components/AuthForm/AuthFormWrapper.tsx": "branding",
  // A menu row, with its own icon, not an inline link.
  "components/menus/top/ShareMenu.tsx": "menu row",
};

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "tests") out.push(...sourceFiles(full));
    } else if (entry.name.endsWith(".tsx")) {
      out.push(full);
    }
  }
  return out;
}

describe("external links", () => {
  const files = sourceFiles(SRC);

  test("the walk finds the app", () => {
    // A guard on the guard: a moved directory would pass vacuously.
    expect(files.length).toBeGreaterThan(100);
  });

  test("every new-tab text link ends in the arrow", () => {
    const missing: string[] = [];
    for (const file of files) {
      const rel = path.relative(SRC, file);
      if (EXEMPT[rel]) continue;
      const src = fs.readFileSync(file, "utf8");
      const anchor = /<a\b[^>]*target=["{][^>]*>([\s\S]*?)<\/a>/g;
      for (const match of src.matchAll(anchor)) {
        const body = match[1];
        if (/<img\b/.test(body)) continue;
        if (!body.includes("↗")) missing.push(`${rel}: ${body.trim().slice(0, 60)}`);
      }
    }
    expect(missing).toEqual([]);
  });

  test("the other arrow is gone", () => {
    const src = fs.readFileSync(path.join(SRC, "components/AiSettingsModal.tsx"), "utf8");
    expect(src).not.toContain("→");
  });
});
