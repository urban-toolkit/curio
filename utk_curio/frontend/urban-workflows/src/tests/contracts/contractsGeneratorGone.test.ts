/**
 * No file of the repository is, names or runs the contracts generator. The
 * constants the browser and the server share are JSON files both read
 * (src/contracts/), so nothing is generated and nobody has a step to run.
 * The checkout is read here, guides and workflows included: the backend
 * suite's image ships neither.
 */
import fs from "fs";
import path from "path";

const REPO_ROOT = path.resolve(__dirname, "../../../../../..");
/** Spelled in two pieces, so this file does not name it itself. */
const GENERATOR = ["generate", "contracts"].join("_");
/** Folders of installed, built or downloaded files, and git's own. */
const NOT_SOURCE = new Set(["node_modules", ".git", "dist", "build", "ci-report", "__pycache__", ".curio"]);
const TEXT = /\.(py|ts|tsx|js|jsx|mjs|cjs|json|md|yml|yaml|toml|cfg|ini|in|sh|txt|css|html)$|^Dockerfile$/;
/** Larger files are data, such as src/components/vega-schema.json, not code or prose. */
const MAX_BYTES = 1_000_000;

function textFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (NOT_SOURCE.has(entry.name) || entry.name.endsWith(".egg-info")) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) textFiles(full, out);
    else if (entry.isFile() && TEXT.test(entry.name) && fs.statSync(full).size <= MAX_BYTES) out.push(full);
  }
  return out;
}

test("no file of the repository is, names or runs the contracts generator", () => {
  const files = textFiles(REPO_ROOT).map((file) => path.relative(REPO_ROOT, file).split(path.sep).join("/"));
  // The read reaches the guides, the agents' map, the workflows, the image,
  // the scripts and the code, where the generator was named.
  for (const file of [
    "docs/CONTRIBUTING.md",
    "docs/EXTENDING.md",
    "docs/ARCHITECTURE.md",
    "AGENTS.md",
    "packages/curio.builtin@1/README.md",
    ".github/workflows/docker-compose.yml",
    "Dockerfile",
    "scripts/test.sh",
    "utk_curio/backend/app/agents/domain/contracts.py",
  ]) {
    expect(files).toContain(file);
  }
  const naming = files.filter(
    (file) => file.includes(GENERATOR) || fs.readFileSync(path.join(REPO_ROOT, file), "utf8").includes(GENERATOR),
  );
  expect(naming).toEqual([]);
});
