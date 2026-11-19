import fs from "fs";
import path from "path";

/**
 * Every canvas the frontend draws with React Flow, read from the source, so a
 * new one has to say what the others say: the files under `src/` (tests left
 * out) that open a `<ReactFlow ...>` tag, each with its text and its tags.
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

export type ReactFlowCanvas = {
  /** The file, from `src/`. */
  file: string;
  text: string;
  tags: string[];
};

export function reactFlowCanvases(): ReactFlowCanvas[] {
  return sources(SRC)
    .map((file) => {
      const text = fs.readFileSync(file, "utf8");
      return { file: path.relative(SRC, file), text, tags: reactFlowTags(text) };
    })
    .filter(({ tags }) => tags.length > 0);
}

/** The canvases there are: the main one and the dashboard's. */
export const CANVAS_FILES = [
  path.join("components", "MainCanvas.tsx"),
  path.join("pages", "dashboard", "DashboardPage.tsx"),
];
