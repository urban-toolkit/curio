import { pendingInstallsNotYetListed } from "../../services/datasetCatalog/pendingInstallView";
import type { PendingInstall } from "../../services/datasetCatalog/datasetCatalogTypes";

const pending = (over: Partial<PendingInstall>): PendingInstall => ({
  key: "k",
  label: "L",
  startedAt: 0,
  ...over,
});

describe("pendingInstallsNotYetListed", () => {
  test("returns [] when there are no pending installs", () => {
    expect(pendingInstallsNotYetListed([], [{ id: "a" }])).toEqual([]);
  });

  test("keeps a pending install with no matching installed row", () => {
    const p = [pending({ key: "n1", producerNodeId: "n1", label: "Node 1" })];
    expect(pendingInstallsNotYetListed(p, [{ id: "other" }])).toEqual(p);
  });

  test("suppresses a pending install matched by producerNodeId", () => {
    const p = [pending({ key: "n1", producerNodeId: "n1" })];
    const installed = [{ id: "computed.n1@1", producerNodeId: "n1" }];
    expect(pendingInstallsNotYetListed(p, installed)).toEqual([]);
  });

  test("suppresses a pending install matched by datasetId", () => {
    const p = [pending({ key: "ds1", datasetId: "ds1" })];
    expect(pendingInstallsNotYetListed(p, [{ id: "ds1" }])).toEqual([]);
  });

  test("keeps unmatched entries while suppressing matched ones", () => {
    const keep = pending({ key: "n2", producerNodeId: "n2", label: "keep" });
    const drop = pending({ key: "n1", producerNodeId: "n1", label: "drop" });
    const installed = [{ id: "computed.n1@1", producerNodeId: "n1" }];
    expect(pendingInstallsNotYetListed([keep, drop], installed)).toEqual([keep]);
  });

  test("an import-style entry (no producer/datasetId) is never suppressed by listed rows", () => {
    const p = [pending({ key: "import", label: "data.csv" })];
    expect(pendingInstallsNotYetListed(p, [{ id: "anything" }])).toEqual(p);
  });
});

describe("drawerPendingInstalls (#217)", () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { drawerPendingInstalls } = require("../../services/datasetCatalog/pendingInstallView");
  const run = pending({ key: "n1", producerNodeId: "n1", label: "Python Computation" });
  const manual = pending({ key: "ds1", datasetId: "ds1", label: "Chicago" });

  test("a run's saved output replaces its placeholder", () => {
    const saved = { id: "computed.flow-1.n1@1", origin: "computed", dirName: "computed.flow-1.n1@1", producerNodeId: "n1" };
    expect(drawerPendingInstalls([run], [saved], "browse")).toEqual([]);
    expect(drawerPendingInstalls([run], [saved], "computed")).toEqual([]);
  });

  test("an unsaved live output does not stand for the run", () => {
    const live = { id: "computed.flow-1.n1@1", origin: "computed", producerNodeId: "n1" };
    expect(drawerPendingInstalls([run], [live], "browse")).toEqual([run]);
  });

  test("the In project tab shows no run placeholder, since the output never joins the project", () => {
    expect(drawerPendingInstalls([run, manual], [], "installed")).toEqual([manual]);
  });

  test("an un-installed hub row sharing the id keeps a manual install's placeholder", () => {
    const hub = { id: "ds1", origin: "hub", installed: false };
    expect(drawerPendingInstalls([manual], [hub], "browse")).toEqual([manual]);
  });
});
