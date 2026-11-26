import { askersOf, sourceCardIds, sourceCardStanding, type AgentSessionTurn } from "../../services/agents";

/**
 * A card of a node's candidates follows its Dataset Finder's record: live
 * while the record asks for its pick, Recorded where the pick was made,
 * superseded once a newer search's card is on offer, and closed, saying why,
 * once its Finder or its node is gone, no pick is needed, or the record went.
 * A card or a record from before cards had ids keeps the rule it had.
 */

const PICK = { name: "Chicago areas", sourceType: "portal" as const, url: "https://data.example.org/areas.geojson" };

describe("sourceCardStanding", () => {
  it("is live while the record offers this card and no pick of it is recorded", () => {
    const record = { status: "candidates-pending", candidates: 1, discoveryId: "d1" };
    expect(sourceCardStanding({ discoveryId: "d1", record, waitsForPick: true })).toEqual({ kind: "live" });
  });

  it("is Recorded on the card the pick was made on, and live again while its portal file waits for its import", () => {
    const record = { status: "resolved", picks: [PICK], discoveryId: "d1", pickedFrom: "d1" };
    expect(sourceCardStanding({ discoveryId: "d1", record, waitsForPick: false })).toEqual({ kind: "recorded" });
    expect(sourceCardStanding({ discoveryId: "d1", record, waitsForPick: true })).toEqual({ kind: "live" });
  });

  it("stays Recorded on the card the pick was made on once a newer card is on offer, which is live", () => {
    const record = { status: "resolved", picks: [PICK], discoveryId: "d2", pickedFrom: "d1" };
    expect(sourceCardStanding({ discoveryId: "d1", record, waitsForPick: false })).toEqual({ kind: "recorded" });
    expect(sourceCardStanding({ discoveryId: "d2", record, waitsForPick: false })).toEqual({ kind: "live" });
  });

  it("is superseded once the record offers another card, and so is a card with no id", () => {
    const record = { status: "candidates-pending", candidates: 1, discoveryId: "d2" };
    expect(sourceCardStanding({ discoveryId: "d1", record, waitsForPick: true })).toEqual({ kind: "superseded" });
    expect(sourceCardStanding({ discoveryId: null, record, waitsForPick: true })).toEqual({ kind: "superseded" });
  });

  it("is closed once its Finder or its node is gone, a skip grounds the node, or the record went", () => {
    const record = { status: "candidates-pending", candidates: 1, discoveryId: "d1" };
    expect(sourceCardStanding({ discoveryId: "d1", record, waitsForPick: true, finderPresent: false })).toEqual({
      kind: "closed",
      why: "finder-gone",
    });
    expect(
      sourceCardStanding({ discoveryId: "d1", record, waitsForPick: true, finderPresent: false, nodePresent: false }),
    ).toEqual({ kind: "closed", why: "node-gone" });
    const skipped = { status: "not-needed", skippedBecause: "/data/areas.csv" };
    expect(sourceCardStanding({ discoveryId: "d1", record: skipped, waitsForPick: false })).toEqual({
      kind: "closed",
      why: "skipped",
    });
    expect(sourceCardStanding({ discoveryId: null, record: skipped, waitsForPick: false })).toEqual({
      kind: "closed",
      why: "skipped",
    });
    expect(sourceCardStanding({ discoveryId: "d1", record: null, waitsForPick: false })).toEqual({
      kind: "closed",
      why: "no-record",
    });
  });

  it("keeps the old rule for a card and a record from before cards had ids", () => {
    expect(sourceCardStanding({ record: { status: "candidates-pending", candidates: 1 }, waitsForPick: true })).toEqual({
      kind: "live",
    });
    expect(sourceCardStanding({ record: { status: "resolved", picks: [PICK] }, waitsForPick: false })).toEqual({
      kind: "recorded",
    });
    expect(sourceCardStanding({ record: null, waitsForPick: false })).toEqual({ kind: "live" });
  });
});

describe("askersOf", () => {
  it("reads every chat that holds the card on offer, else the one that asked", () => {
    expect(askersOf({ status: "candidates-pending", askedBy: "dfb", askers: ["dfb", "nb1"] })).toEqual(["dfb", "nb1"]);
    expect(askersOf({ status: "candidates-pending", askedBy: "dfb" })).toEqual(["dfb"]);
    expect(askersOf(null)).toEqual([]);
  });
});

describe("sourceCardIds", () => {
  it("is the ids of the candidates cards a chat holds, its own Finder's and the ones it asked for", () => {
    const turns: AgentSessionTurn[] = [
      { role: "agent", text: "found", content: [{ type: "datasetCandidates", discoveryId: "d1", lanes: { external: [PICK], catalog: [] } }] },
      {
        role: "agent",
        text: "asked",
        content: [{
          type: "sourcePick", finderAttachmentId: "att-df", nodeId: "n1", nodeLabel: "Load", discoveryId: "d2",
          lanes: { external: [PICK], catalog: [] },
        }],
      },
      { role: "agent", text: "old", content: [{ type: "datasetCandidates", lanes: { external: [PICK], catalog: [] } }] },
    ];
    expect(Array.from(sourceCardIds(turns)).sort()).toEqual(["d1", "d2"]);
  });
});
