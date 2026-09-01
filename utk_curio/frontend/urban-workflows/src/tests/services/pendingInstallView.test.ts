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
