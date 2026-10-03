import fs from "fs";
import path from "path";

/**
 * The canvas and the dashboard wear the same top bar as the section pages,
 * GlobalPageHeader, rather than bars of their own. The canvas's own bar had no
 * API Settings and no Monitor, and hid every catalog under a menu.
 *
 * One consequence is checked here too: the bar hosts the one
 * ConnectionKeysModalHost on a page. The canvas used to mount a second one in
 * the agent dock, so with both, one "add a key" request would open two modals.
 *
 * Source-read: UpMenu and the dashboard need the whole provider stack to
 * render. The rendered bar is checked in globalPageHeader.test.tsx and
 * dashboardPage.test.tsx, and on the canvas by test_canvas_header_e2e.py.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** Every .tsx under src, tests excluded. */
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

describe("the canvas and the dashboard", () => {
  it.each(["components/menus/top/UpMenu.tsx", "pages/dashboard/DashboardTopBar.tsx"])(
    "%s renders the shared GlobalPageHeader",
    (file) => {
      expect(read(file)).toMatch(/<GlobalPageHeader\b/);
    },
  );

  it("no longer build a bar of their own", () => {
    expect(fs.existsSync(path.join(SRC, "components/login/UserMenu.tsx"))).toBe(false);
    const css = read("components/menus/top/UpMenu.module.css");
    expect(css).not.toContain(".menuBar");
    expect(css).not.toContain(".dropDownRow");
  });
});

describe("the API Settings request host", () => {
  it("is mounted by the shared header and by nothing else", () => {
    const mounts = sourceFiles(SRC)
      .filter((file) => /<ConnectionKeysModalHost\b/.test(fs.readFileSync(file, "utf8")))
      .map((file) => path.relative(SRC, file));
    expect(mounts).toEqual(["components/layout/GlobalPageHeader.tsx"]);
  });
});
