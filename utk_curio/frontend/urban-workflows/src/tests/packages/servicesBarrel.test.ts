/**
 * The packages service layer keeps the same shape as the agents layer (memo dev/143,
 * §3.4 and §7): every module under `services/packages` contributes its exports to the
 * barrel; the layer renders nothing and imports no component; the node-catalog surfaces
 * reach transport only through it; and — the fourth rule, what makes the dev/91 "light
 * module" property hold for the whole layer — nothing here imports `registry/` at
 * runtime (rule 5: the registry consumes the layer, never the reverse; `import type`
 * is erased and allowed).
 */
import * as path from "path";

import * as barrel from "../../services/packages";
import {
  missingFromBarrel,
  registryImportOffenders,
  renderingOffenders,
  transportOffenders,
} from "../_support/layerRules";

const SRC = path.join(__dirname, "..", "..");
const PACKAGES = {
  root: path.join(SRC, "services", "packages"),
  barrel,
  src: SRC,
  /** The node-catalog surfaces (memo §3.4 rule 1): every file here renders or composes; none may fetch. */
  surfaces: [
    path.join(SRC, "components", "packages"),
    path.join(SRC, "components", "menus", "nodes", "toolsMenuPackagePalette"),
    path.join(SRC, "components", "menus", "libraries"),
    path.join(SRC, "pages", "catalog"),
    path.join(SRC, "providers", "packages"),
  ],
};

describe("services/packages barrel", () => {
  it("re-exports every runtime export of every module", () => {
    expect(missingFromBarrel(PACKAGES)).toEqual([]);
  });

  it("renders nothing and imports no component", () => {
    expect(renderingOffenders(PACKAGES)).toEqual([]);
  });

  it("is the only transport the node-catalog surfaces use", () => {
    expect(transportOffenders(PACKAGES)).toEqual([]);
  });

  it("never imports the node-kind registry at runtime", () => {
    expect(registryImportOffenders(PACKAGES)).toEqual([]);
  });
});
