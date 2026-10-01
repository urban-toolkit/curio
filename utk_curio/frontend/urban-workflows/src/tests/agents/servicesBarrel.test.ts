/**
 * The agents service layer is reachable from its barrel (memo dev/142, F1):
 * every module under `services/agents` (types included) contributes each of its
 * exports to `services/agents/index.ts`, so consumers import from one path.
 * And the layer is the ONLY place the agents surfaces reach transport from
 * (F5): components render, providers compose, and both talk to the backend
 * through `services/agents` alone. The rules live in `tests/_support/layerRules.ts`
 * (dev/143 F1), shared with the packages layer.
 */
import * as path from "path";

import * as barrel from "../../services/agents";
import { missingFromBarrel, renderingOffenders, transportOffenders } from "../_support/layerRules";

const SRC = path.join(__dirname, "..", "..");
const AGENTS = {
  root: path.join(SRC, "services", "agents"),
  barrel,
  src: SRC,
  /** The agents surfaces: every file here renders or composes; none may fetch. */
  surfaces: [
    path.join(SRC, "components", "agents"),
    path.join(SRC, "components", "menus", "nodes", "agentsPalette"),
    path.join(SRC, "pages", "agents"),
    path.join(SRC, "providers", "agents"),
  ],
};

describe("services/agents barrel", () => {
  it("re-exports every runtime export of every module", () => {
    expect(missingFromBarrel(AGENTS)).toEqual([]);
  });

  it("renders nothing and imports no component (the layer owns transport, hooks over it, and pure logic)", () => {
    // React hooks are allowed — `services/datasetCatalog/datasetCatalogHooks.ts`
    // is the precedent — but no module here renders or reaches into components.
    expect(renderingOffenders(AGENTS)).toEqual([]);
  });

  it("is the only transport the agents surfaces use (no apiFetch, backendUrl, fetch or EventSource under components/pages/providers)", () => {
    expect(transportOffenders(AGENTS)).toEqual([]);
  });
});
