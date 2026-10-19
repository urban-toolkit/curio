/**
 * Webpack config for building each first-party package's behavior bundle.
 *
 * Each entry compiles a package's `sources/index.tsx` into a self-contained
 * UMD bundle that lands back in the package directory, at the path its
 * manifest's `behaviorScript` names (`scripts/behaviors.js`). The bundle
 * externalizes React, ReactFlow, and Curio's `registerBehavior`: they live as
 * globals on `window` and the bundle calls into them at load time. The
 * `scripts/` subdirectory is one of the package archive's allowed top-level
 * dirs (see `utk_curio/backend/app/packages/repositories/archive.py::_ALLOWED_TOP_DIRS`),
 * so the bundle survives a catalog round-trip through the archive validator.
 * See `docs/EXTENDING.md` for the conventions a package author follows to
 * plug into this build.
 *
 * Run via `npm run build:packages`. The main app build (`npm run build`)
 * chains both.
 */

const path = require("path");
const { packageEntries } = require("./webpack/packageEntries");

// One entry per package under `packages/` whose manifest declares a
// `behaviorScript` and that holds `sources/index.tsx`, read off the manifests
// (webpack/packageEntries.js). A package built outside this repository ships
// its bundle already built, with no `sources/index.tsx`.
const PACKAGE_ENTRIES = packageEntries(path.resolve(__dirname, "../../../packages"));

// React, ReactFlow, and Curio's behavior-registry function are shared with
// the host page. Mapping them to `window.*` globals keeps each package
// bundle small and (crucially) reuses Curio's React instance — distinct
// React copies break the rules-of-hooks invariant and crash every hook.
const SHARED_EXTERNALS = {
  react: { commonjs: "react", commonjs2: "react", amd: "react", root: "React" },
  "react-dom": { commonjs: "react-dom", commonjs2: "react-dom", amd: "react-dom", root: "ReactDOM" },
  reactflow: { commonjs: "reactflow", commonjs2: "reactflow", amd: "reactflow", root: "ReactFlow" },
};

module.exports = PACKAGE_ENTRIES.map(({ id, entry, outputDir, filename }) => ({
  name: id,
  entry,
  output: {
    path: outputDir,
    filename,
    library: {
      // UMD lets the same bundle run as a global side-effect script
      // (the loader path we use today) or be re-bundled by a future
      // catalog-uploaded path that fetches the file with `import()`.
      type: "umd",
      name: id.replace(/[@.]/g, "_"),
    },
    globalObject: "this",
  },
  externals: SHARED_EXTERNALS,
  cache: {
    type: "filesystem",
    buildDependencies: { config: [__filename] },
  },
  resolve: {
    extensions: [".tsx", ".ts", ".js"],
    // Lets the package's sources import from Curio's own src tree via
    // relative paths (a behavior file's `NodeBehaviorHook` type import,
    // erased at runtime).
    modules: [path.resolve(__dirname, "node_modules")],
  },
  module: {
    rules: [
      {
        test: /\.(ts|tsx)$/,
        exclude: /node_modules/,
        use: {
          loader: "babel-loader",
          options: {
            // Package sources live OUTSIDE this directory tree, so babel's
            // default lookup misses the .babelrc here. Pin the presets
            // inline so TSX/TS files in `packages/*/sources/` compile with
            // the same plugins as the main app, regardless of cwd.
            babelrc: false,
            configFile: false,
            presets: [
              "@babel/preset-env",
              "@babel/preset-react",
              "@babel/preset-typescript",
            ],
          },
        },
      },
    ],
  },
  mode: process.env.NODE_ENV === "production" ? "production" : "development",
  devtool: "source-map",
}));
