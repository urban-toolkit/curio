/**
 * Step 5.6 of the agent chat plan, found by #1652's dev check: an invited
 * editor's pick on a Dataset Finder's card asks the owner to add the dataset
 * (`projects/editor_requests.py`), and her drawer's card named no loader: the
 * request carried only the node's id. The request carries the name of each
 * loader it was picked for (`nodeNames`), and the card says it above what
 * her Apply does (`requestEffect`). A request no pick made names none.
 */
import { requestEffect, type DatasetRequest } from "../../services/editorRequests";

/** A request for a dataset of the owner's own, made by a pick for a loader. */
const PICKED = {
  proposalId: "request-1",
  kind: "datasets",
  tool: "dataset.install",
  status: "pending",
  summary: "Add dataset · x8fc-8rcq.geojson",
  preview: "x8fc-8rcq.geojson · GEOJSON · from Alice's Data Catalog",
  by: { kind: "person", account: "2", name: "Bob" },
  nodeIds: ["n1"],
  nodeNames: { n1: "Library Branch Locations" },
  shared: false,
  datasetId: "imported.xefd08dde184e",
  datasetName: "x8fc-8rcq.geojson",
  format: "geojson",
  ownersOwn: true,
} as unknown as DatasetRequest;

describe("an editor's request made by a pick names the loader it is for", () => {
  it("to the owner, above what her Apply does", () => {
    expect(requestEffect(PICKED, "owner")).toBe(
      "Picked as the source of Library Branch Locations. Applying adds this dataset of your Data Catalog to this dataflow.",
    );
  });

  it("to an editor", () => {
    expect(requestEffect(PICKED, "editor")).toBe(
      "Picked as the source of Library Branch Locations. Applying adds this dataset of the Data Catalog of the dataflow's owner to this dataflow.",
    );
  });

  it("names each loader of a request asked again for another", () => {
    const again = {
      ...PICKED,
      nodeIds: ["n1", "n2", "n3"],
      nodeNames: { n1: "Library Branch Locations", n2: "Branch hours", n3: "Branch visitors" },
    } as unknown as DatasetRequest;
    expect(requestEffect(again, "owner")).toBe(
      "Picked as the source of Library Branch Locations, Branch hours and Branch visitors. " +
        "Applying adds this dataset of your Data Catalog to this dataflow.",
    );
  });

  it("names no loader for a request no pick made", () => {
    const dropped = { ...PICKED, nodeNames: undefined, ownersOwn: undefined } as unknown as DatasetRequest;
    expect(requestEffect(dropped, "owner")).toBe(
      "Applying copies this dataset into your Data Catalog and adds it to this dataflow.",
    );
  });
});
