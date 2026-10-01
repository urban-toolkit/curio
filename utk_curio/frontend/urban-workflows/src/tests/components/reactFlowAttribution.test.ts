import fs from "fs";
import path from "path";

/**
 * No canvas draws React Flow's attribution (#509).
 *
 * The main canvas left it on, in the bottom-right corner the version badge is
 * fixed to, so the two strings overlapped on every canvas screen. The other
 * three canvases already hid it. Read from the source, so a new canvas has to
 * say the same.
 */
const SRC = path.resolve(__dirname, "../..");

function sources(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "tests" ? [] : sources(full);
    return /\.tsx$/.test(entry.name) ? [full] : [];
  });
}

/**
 * The props of each `<ReactFlow ...>` opening tag in a file: from the tag to
 * the `>` or `/>` on a line of its own at the tag's indentation. Props carry
 * comments with arrows in them, so the first `>` is not the end.
 */
function reactFlowTags(text: string): string[] {
  const tags: string[] = [];
  const open = /^([ \t]*)<ReactFlow(?=\s)/gm;
  let match: RegExpExecArray | null;
  while ((match = open.exec(text))) {
    const close = new RegExp(`^${match[1]}/?>`, "m");
    const rest = text.slice(match.index);
    const end = rest.search(close);
    tags.push(end === -1 ? rest : rest.slice(0, end));
  }
  return tags;
}

const canvases = sources(SRC)
  .map((file) => ({ file: path.relative(SRC, file), tags: reactFlowTags(fs.readFileSync(file, "utf8")) }))
  .filter(({ tags }) => tags.length > 0);

test("finds the canvases, the main one among them", () => {
  expect(canvases.map(({ file }) => file)).toEqual(
    expect.arrayContaining([path.join("components", "MainCanvas.tsx")]),
  );
  expect(canvases.length).toBeGreaterThanOrEqual(4);
});

test.each(canvases.map(({ file, tags }) => [file, tags] as const))(
  "%s hides the attribution",
  (_file, tags) => {
    for (const tag of tags) {
      expect(tag).toMatch(/proOptions=\{\{\s*hideAttribution:\s*true\s*\}\}/);
    }
  },
);
