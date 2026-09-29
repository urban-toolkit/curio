/**
 * The structural rules a frontend service layer keeps (memo dev/142 F1/F5, shared by
 * dev/143 §7): every module's exports reach the barrel; the layer renders nothing and
 * imports no component; the surfaces over it use no transport of their own; and, for a
 * layer that must stay light, no import of the node-kind registry.
 *
 * Each suite describes its layer with a `LayerSpec` and asserts the rules it needs.
 */
import * as fs from "fs";
import * as path from "path";

export interface LayerSpec {
  /** The layer's directory (absolute). */
  root: string;
  /** The barrel module, already imported (`import * as barrel from ...`). */
  barrel: Record<string, unknown>;
  /** `src` (absolute) — surface paths are reported relative to it. */
  src: string;
  /** The surfaces over the layer: every file here renders or composes; none may fetch. */
  surfaces: string[];
  /** Import paths (as written) a layer module MAY reach under `/components/`. */
  allowedComponentImports?: RegExp;
}

export function modulesUnder(dir: string): string[] {
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((entry) => {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) return modulesUnder(full);
      return /\.tsx?$/.test(entry.name) && entry.name !== "index.ts" ? [full] : [];
    });
}

/** Every runtime export of every module under the layer is re-exported by the barrel. */
export function missingFromBarrel(spec: LayerSpec): string[] {
  const missing: string[] = [];
  for (const file of modulesUnder(spec.root)) {
    const mod = require(file) as Record<string, unknown>;
    for (const name of Object.keys(mod)) {
      if (name === "default" || name === "__esModule") continue;
      if (!(name in spec.barrel)) missing.push(`${path.relative(spec.root, file)}:${name}`);
    }
  }
  return missing;
}

/** Layer modules that render (a `.tsx`, `react-dom`) or import a component. React hooks are allowed. */
export function renderingOffenders(spec: LayerSpec): string[] {
  const offenders: string[] = [];
  for (const file of modulesUnder(spec.root)) {
    const text = fs.readFileSync(file, "utf8");
    const componentImports = [...text.matchAll(/from "([^"]*\/components\/[^"]*)"/g)].map((m) => m[1]);
    const badComponentImport = componentImports.some((p) => !(spec.allowedComponentImports?.test(p) ?? false));
    if (/\.tsx$/.test(file) || /from "react-dom"/.test(text) || badComponentImport) {
      offenders.push(path.relative(spec.root, file));
    }
  }
  return offenders;
}

/** Surface files that reach transport themselves (`utils/authApi`, `utils/backendUrl`, `fetch(`, `new EventSource(`). */
export function transportOffenders(spec: LayerSpec): string[] {
  const offenders: string[] = [];
  for (const dir of spec.surfaces) {
    if (!fs.existsSync(dir)) continue;
    const files = fs.statSync(dir).isDirectory() ? modulesUnder(dir) : [dir];
    for (const file of files) {
      const text = fs.readFileSync(file, "utf8");
      if (/utils\/authApi"|utils\/backendUrl"|(?<!\w)fetch\(|new EventSource\(/.test(text)) {
        offenders.push(path.relative(spec.src, file));
      }
    }
  }
  return offenders;
}

/** Layer modules that import the node-kind registry at runtime (`import type` is erased and allowed). */
export function registryImportOffenders(spec: LayerSpec): string[] {
  const offenders: string[] = [];
  for (const file of modulesUnder(spec.root)) {
    const text = fs.readFileSync(file, "utf8");
    const runtimeImports = [...text.matchAll(/^import (?!type\b)[^;]*from "([^"]*\/registry\/[^"]*)"/gm)];
    if (runtimeImports.length) offenders.push(path.relative(spec.root, file));
  }
  return offenders;
}
