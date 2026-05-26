/**
 * Webpack config for building each first-party package's `lifecycles.js`
 * bundle.
 *
 * Each entry compiles a package's `sources/index.tsx` into a self-contained
 * UMD bundle that lands back in the package directory at
 * `scripts/lifecycles.js`. The bundle externalizes React, ReactFlow, and
 * Curio's `registerLifecycle` — they live as globals on `window` and the
 * bundle calls into them at load time. The `scripts/` subdirectory is one
 * of the package archive's allowed top-level dirs (see
 * `utk_curio/backend/app/packages/installer.py::_ALLOWED_TOP_DIRS`), so
 * the bundle survives a catalog round-trip through the archive validator.
 * See `docs/EXTENDING.md` for the conventions a package author follows to
 * plug into this build.
 *
 * Run via `npm run build:packages`. The main app build (`npm run build`)
 * chains both.
 */

const path = require("path");
const webpack = require("webpack");

// One entry per first-party package with a `sources/index.tsx`. To add a new
// one, drop a directory at `packages/<id>@<major>/sources/` and add a row
// here. Authors of THIRD-party packages would pre-build their own
// `scripts/lifecycles.js` and ship it inside the package directory — no
// entry here.
const PACKAGE_ENTRIES = [
  {
    id: "curio.streetvision@1",
    entry: path.resolve(__dirname, "../../../packages/curio.streetvision@1/sources/index.tsx"),
    outputDir: path.resolve(__dirname, "../../../packages/curio.streetvision@1/scripts"),
  },
];

// React, ReactFlow, and Curio's lifecycle-registry function are shared with
// the host page. Mapping them to `window.*` globals keeps each package
// bundle small and (crucially) reuses Curio's React instance — distinct
// React copies break the rules-of-hooks invariant and crash every hook.
const SHARED_EXTERNALS = {
  react: { commonjs: "react", commonjs2: "react", amd: "react", root: "React" },
  "react-dom": { commonjs: "react-dom", commonjs2: "react-dom", amd: "react-dom", root: "ReactDOM" },
  reactflow: { commonjs: "reactflow", commonjs2: "reactflow", amd: "reactflow", root: "ReactFlow" },
};

module.exports = PACKAGE_ENTRIES.map(({ id, entry, outputDir }) => ({
  name: id,
  entry,
  output: {
    path: outputDir,
    filename: "lifecycles.js",
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
    // relative paths (used by streetvision lifecycle files for the
    // `NodeLifecycleHook` type import — erased at runtime).
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
  plugins: [
    // Package sources commonly read ``process.env.BACKEND_URL`` (mirroring
    // the main app's convention). The browser has no ``process`` global, so
    // without this DefinePlugin the bundle throws ``process is not defined``
    // the moment the lifecycle script evaluates. We bake in only what
    // packages legitimately need — BACKEND_URL — rather than the whole
    // ``process.env`` object.
    new webpack.DefinePlugin({
      "process.env.BACKEND_URL": JSON.stringify(process.env.BACKEND_URL || ""),
    }),
  ],
  mode: process.env.NODE_ENV === "production" ? "production" : "development",
  devtool: "source-map",
}));
