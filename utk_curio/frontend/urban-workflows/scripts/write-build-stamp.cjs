// Records the webpack mode `npm run build` built dist/ in, in dist/.curio-build,
// the file curio.py's launcher reads before it reuses a build
// (utk_curio/cli/frontend_build.py::_build_stamp_reason). npm runs it after
// every `npm run build` (package.json's postbuild), so a build made without
// the launcher, as the PyPI release's is, is reused too. The mode is read
// from the build script the same way _frontend_build_mode reads it.
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const build = require(path.join(root, "package.json")).scripts?.build || "";
const mode = /--mode\s+(\S+)/.exec(build);
fs.writeFileSync(path.join(root, "dist", ".curio-build"), `${mode ? mode[1] : "unknown"}\n`);
