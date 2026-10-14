/**
 * Webpack config for the Autark data compiler a run on the server uses.
 *
 * It bundles `src/adapters/node/autkDataCompileServer.ts`, with the
 * `autkDataCompile.ts` the browser compiles an Autark data section with, into
 * `dist/autk-data-compile.cjs`, a script Node runs on its own
 * (`utk_curio/common/autk_data_compiler.py`). It ships in `dist/` beside the
 * page, so a pip install has it with no TypeScript sources.
 *
 * Not minified: the compiled JavaScript embeds `loadableFeatures` as its own
 * source text (`loadableFeatures.toString()`).
 *
 * Run via `npm run build:autk-data`. The main app build (`npm run build`)
 * chains it.
 */

const path = require("path");

module.exports = {
  name: "autk-data-compile",
  target: "node",
  entry: path.resolve(__dirname, "src/adapters/node/autkDataCompileServer.ts"),
  output: {
    path: path.resolve(__dirname, "dist"),
    filename: "autk-data-compile.cjs",
  },
  resolve: {
    extensions: [".ts", ".js"],
  },
  module: {
    rules: [
      {
        test: /\.ts$/,
        exclude: /node_modules/,
        use: {
          loader: "babel-loader",
          options: {
            babelrc: false,
            configFile: false,
            presets: [
              ["@babel/preset-env", { targets: { node: "20" } }],
              "@babel/preset-typescript",
            ],
          },
        },
      },
    ],
  },
  optimization: { minimize: false },
  mode: "production",
  devtool: false,
};
