const path = require("path");
const fs = require("fs");
const webpack = require("webpack");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const Dotenv = require("dotenv-webpack");

// Read ENABLE_COLLAB from .env (or the process env) before Dotenv plugin
// runs, so we can branch the devServer config and BACKEND_URL substitution.
function readEnvVar(name) {
  if (process.env[name] !== undefined) return process.env[name];
  try {
    const raw = fs.readFileSync(path.resolve(__dirname, ".env"), "utf8");
    for (const line of raw.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq < 0) continue;
      if (trimmed.slice(0, eq).trim() === name) {
        return trimmed.slice(eq + 1).trim();
      }
    }
  } catch (_) {}
  return undefined;
}
const collabEnabled = String(readEnvVar("ENABLE_COLLAB")).toLowerCase() === "true";

// The `utk` file dependency bundles `require("vega-lite")`; without aliases, webpack can
// resolve that package from `utk-ts/node_modules`, which may be incomplete. Pin the Vega/D3
// stack to this app's node_modules so hoisted transitive deps (vega-util, d3-format, …) always resolve.
const nm = (...segments) => path.join(__dirname, "node_modules", ...segments);

module.exports = {
  entry: "./src/index.tsx",
  output: {
    filename: "bundle.js",
    path: path.resolve(__dirname, "dist"),
    publicPath: process.env.PUBLIC_PATH || "/",
  },
  cache: {
    type: 'filesystem',
    buildDependencies: {
      config: [__filename],
    },
  },
  devServer: {
    historyApiFallback: true,
    // ENABLE_COLLAB=true → listen on 0.0.0.0 so LAN clients can hit the dev
    // server via the host's IP. Leave default (loopback) otherwise.
    ...(collabEnabled ? { host: "0.0.0.0", allowedHosts: "all" } : {}),
    client: {
      overlay: {
        // ResizeObserver loop warnings are benign browser notifications fired when
        // a resize callback cannot deliver all updates in a single animation frame.
        // Webpack-dev-server incorrectly surfaces them as hard errors via window.onerror.
        runtimeErrors: (err) =>
          err?.message !== 'ResizeObserver loop completed with undelivered notifications.',
      },
    },
  },
  resolve: {
    extensions: [".tsx", ".ts", ".js"],
    modules: [path.resolve(__dirname, 'src'), 'node_modules'],
    alias: {
      // vega v6 packages are ESM-only with no "main" field — webpack ignores "exports"
      // when an alias targets a directory, so we point directly to the built ESM files.
      vega: nm("vega", "build", "vega.module.js"),
      "vega-lite": nm("vega-lite", "build", "index.js"),
      "vega-util": nm("vega-util", "build", "index.js"),
      "d3-format": nm("d3-format"),
    },
  },
  devtool: "source-map",
  module: {
    rules: [
      {
        test: /\.(ts|tsx)$/,
        exclude: /node_modules/,
        use: "babel-loader",
      },
      // CSS Modules (e.g., Button.module.css)
      // css-loader v7 flipped `modules.namedExport` to true by default, which
      // breaks `import styles from "./X.module.css"` (no default export).
      // Force it back to false so existing default-import usage keeps working.
      {
        test: /\.module\.css$/,
        use: [
          "style-loader",
          {
            loader: "css-loader",
            options: {
              modules: {
                namedExport: false,
                exportLocalsConvention: "as-is",
              },
            },
          },
        ],
        include: path.resolve(__dirname, "src"),
      },
      // Regular global CSS (e.g., global.css)
      {
        test: /\.css$/,
        exclude: /\.module\.css$/,
        use: ["style-loader", "css-loader"],
      },
      {
        test: /\.js$/,
        include: /node_modules\/vega/,
        resolve: { fullySpecified: false },
      },
      {
        enforce: "pre",
        test: /\.js$/,
        loader: "source-map-loader",
        exclude: [
          /node_modules\/intro\.js/,
          /node_modules/
        ],
      },
      {
        test: /\.(png|jpe?g|gif|svg)$/i,
        type: 'asset/resource',
      },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "./src/index.html",
      favicon: './src/assets/favicon.ico'
    }),
    new Dotenv({
      path: ".env",
      systemvars: true,
    }),
    // Always resolve BACKEND_URL from window.location at runtime. Baking
    // a host into the bundle means every network/IP change requires a
    // rebuild (and breaks LAN collab unless the host happens to be in
    // the bake). Treating the backend as "same host as the page, port
    // 5002" works for localhost dev, Docker, and LAN collab uniformly.
    // DefinePlugin runs after Dotenv, so this substitution wins.
    new webpack.DefinePlugin({
      "process.env.BACKEND_URL":
        "(window.location.protocol + '//' + window.location.hostname + ':5002')",
    }),
  ],
};
