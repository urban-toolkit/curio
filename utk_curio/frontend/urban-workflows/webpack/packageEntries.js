/**
 * The packages `npm run build:packages` bundles, read off their manifests.
 *
 * A package under `packages/` brings its own interface when its manifest
 * declares a `behaviorScript` and it holds the bundle's entry point,
 * `sources/index.tsx`. Its bundle is written where `behaviorScript` says,
 * inside the package. So a new package with its own interface needs no edit
 * to the build config. A package built outside this repository ships its
 * bundle already built, with no `sources/index.tsx`, and is left alone.
 */

const fs = require("fs");
const path = require("path");

const ENTRY_POINT = path.join("sources", "index.tsx");

/**
 * One entry per package folder under *packagesRoot* that declares a bundle and
 * holds its entry point, by folder name: `{id, entry, outputDir, filename}`.
 * None when the folder is missing.
 */
function packageEntries(packagesRoot) {
  if (!fs.existsSync(packagesRoot)) return [];
  return fs
    .readdirSync(packagesRoot, { withFileTypes: true })
    .filter((item) => item.isDirectory())
    .map((item) => item.name)
    .sort()
    .flatMap((name) => {
      const folder = path.resolve(packagesRoot, name);
      const manifestPath = path.join(folder, "manifest.json");
      const entry = path.join(folder, ENTRY_POINT);
      if (!fs.existsSync(manifestPath) || !fs.existsSync(entry)) return [];
      const { behaviorScript } = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
      if (typeof behaviorScript !== "string" || !behaviorScript) return [];
      const bundle = path.resolve(folder, behaviorScript);
      if (!bundle.startsWith(folder + path.sep)) {
        throw new Error(`${name}: behaviorScript "${behaviorScript}" points outside the package`);
      }
      return [{ id: name, entry, outputDir: path.dirname(bundle), filename: path.basename(bundle) }];
    });
}

module.exports = { packageEntries };
