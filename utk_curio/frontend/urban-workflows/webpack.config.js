const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const Dotenv = require("dotenv-webpack");

// The `utk` file dependency bundles `require("vega-lite")`; without aliases, webpack can
// resolve that package from `utk-ts/node_modules`, which may be incomplete. Pin the Vega/D3
// stack to this app's node_modules so hoisted transitive deps (vega-util, d3-format, …) always resolve.
const nm = (...segments) => path.join(__dirname, "node_modules", ...segments);

module.exports = {
  entry: "./src/index.tsx",
  output: {
    filename: "bundle.js",
    path: path.resolve(__dirname, "dist"),
  },
  resolve: {
    extensions: [".tsx", ".ts", ".js"],
    modules: [path.resolve(__dirname, 'src'), 'node_modules'],
    alias: {
      vega: nm("vega"),
      "vega-lite": nm("vega-lite"),
      "vega-util": nm("vega-util"),
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
      {
        test: /\.module\.css$/,
        use: [
          "style-loader",
          {
            loader: "css-loader",
            options: {
              modules: true,
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
    }),
  ],
};
