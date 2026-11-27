/**
 * An editor's pick on a Dataset Finder's card of a dataset of the owner's own
 * Data Catalog asks her to add it (`projects/editor_requests.py`, the
 * `datasets` kind's `ownersOwn`). Her drawer's card says what her Apply does
 * in place of an install's line (`requestEffect`): it adds her own dataset,
 * with no copy, where an editor's own dataset is copied into her store.
 */
import { requestEffect, type DatasetRequest } from "../../services/editorRequests";

/** A request for a dataset of the owner's own, as the server keeps it. */
const HERS = {
  proposalId: "request-1",
  kind: "datasets",
  tool: "dataset.install",
  status: "pending",
  summary: "Add dataset · Library branches",
  preview: "Library branches · CSV · from Alice's Data Catalog",
  by: { kind: "person", account: "2", name: "Bob" },
  nodeIds: ["load"],
  shared: false,
  datasetId: "imported.x1",
  datasetName: "Library branches",
  format: "csv",
  ownersOwn: true,
} as DatasetRequest;

describe("an editor's request for a dataset of the owner's own Data Catalog", () => {
  it("tells the owner her Apply adds her own dataset", () => {
    expect(requestEffect(HERS, "owner")).toBe("Applying adds this dataset of your Data Catalog to this dataflow.");
  });

  it("tells an editor whose Data Catalog it comes from", () => {
    expect(requestEffect(HERS, "editor")).toBe(
      "Applying adds this dataset of the Data Catalog of the dataflow's owner to this dataflow.",
    );
  });

  it("names a collection of hers a collection", () => {
    expect(requestEffect({ ...HERS, format: "collection" } as DatasetRequest, "owner")).toBe(
      "Applying adds this collection of your Data Catalog to this dataflow.",
    );
  });

  it("still says an editor's own dataset is copied into her store", () => {
    expect(requestEffect({ ...HERS, ownersOwn: undefined } as DatasetRequest, "owner")).toBe(
      "Applying copies this dataset into your Data Catalog and adds it to this dataflow.",
    );
  });
});
