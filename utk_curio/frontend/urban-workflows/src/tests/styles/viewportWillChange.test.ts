import fs from "fs";
import path from "path";
import { VIEWPORT_MOVING_CLASS } from "../../hook/useViewportMotionHint";

/**
 * No React Flow viewport is a `will-change` layer at rest (#533).
 *
 * Chrome keeps such a layer painted at the zoom it was rasterized at. The
 * canvas had the hint on all the time, so after a fit its nodes could stay a
 * scaled bitmap of an earlier zoom: soft text and edges until something
 * repainted them. The hint now comes with the class `useViewportMotionHint`
 * puts on a flow while the user pans or zooms it.
 *
 * Read from the source, so a new stylesheet has to say the same, and every flow
 * that imports MainCanvas.css has to set the class through the hook.
 */
const SRC = path.resolve(__dirname, "../..");

function sources(dir: string, pattern: RegExp): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "tests" ? [] : sources(full, pattern);
    return pattern.test(entry.name) ? [full] : [];
  });
}

/** Each rule of a stylesheet, comments removed, as a selector and a body. */
function rules(css: string): { selector: string; body: string }[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return Array.from(text.matchAll(/([^{}]+)\{([^{}]*)\}/g), (m) => ({
    selector: m[1].trim(),
    body: m[2],
  }));
}

const viewportHints = sources(SRC, /\.css$/).flatMap((file) =>
  rules(fs.readFileSync(file, "utf8"))
    .filter(({ selector, body }) =>
      selector.includes("react-flow__viewport") && /will-change:\s*(?!auto\b)[\w-]/.test(body))
    .map(({ selector }) => ({ file: path.relative(SRC, file), selector })),
);

test("finds the canvas's hint", () => {
  expect(viewportHints.map(({ file }) => file)).toContain(path.join("components", "MainCanvas.css"));
});

test.each(viewportHints.map(({ file, selector }) => [file, selector] as const))(
  "%s gives a viewport the hint only while it moves: %s",
  (_file, selector) => {
    expect(selector).toContain(`.${VIEWPORT_MOVING_CLASS}`);
  },
);

const canvasStyleUsers = sources(SRC, /\.tsx$/)
  .filter((file) => /import\s+["'][./]*(?:components\/)?MainCanvas\.css["']/.test(fs.readFileSync(file, "utf8")))
  .map((file) => path.relative(SRC, file));

test("finds the flows that use the canvas's stylesheet", () => {
  expect(canvasStyleUsers).toEqual(
    expect.arrayContaining([
      path.join("components", "MainCanvas.tsx"),
      path.join("pages", "dashboard", "DashboardPage.tsx"),
    ]),
  );
});

test.each(canvasStyleUsers)("%s sets the moving class through useViewportMotionHint", (file) => {
  const text = fs.readFileSync(path.join(SRC, file), "utf8");
  expect(text).toMatch(/useViewportMotionHint\(\)/);
  for (const prop of ["onMoveStart", "onMove", "onMoveEnd"]) {
    expect(text).toMatch(new RegExp(`${prop}=\\{\\w+\\.${prop}\\}`));
  }
});
