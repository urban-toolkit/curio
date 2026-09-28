/** dev/116: the window-event bus between the remedy cards and the modal host. */
import {
  remedyFocus,
  requestConnectionKeys,
  subscribeConnectionKeysRequests,
} from "../../components/connectionKeys/connectionKeysRequest";

describe("connectionKeysRequest (dev/116)", () => {
  it("delivers a request to every subscriber until unsubscribed", () => {
    const seen: unknown[] = [];
    const off = subscribeConnectionKeysRequests((focus) => seen.push(focus));
    requestConnectionKeys({ host: "api.census.gov", suggestedName: "census" });
    expect(seen).toEqual([{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }]);
    off();
    requestConnectionKeys({ host: "other.gov" });
    expect(seen).toHaveLength(1);
  });

  it("remedyFocus turns only a missing-key remedy into a form focus", () => {
    expect(remedyFocus({ kind: "connection-key", host: "api.census.gov", suggestedName: "census" })).toEqual({
      host: "api.census.gov",
      suggestedName: "census",
    });
    expect(remedyFocus({ kind: "use-connection-key", host: "api.census.gov", name: "census" })).toBeNull();
    expect(remedyFocus({ kind: "connection-key" })).toBeNull();
    expect(remedyFocus(null)).toBeNull();
  });
});

describe("suggestName / hostOf (dev/117: one implementation for every caller)", () => {
  it("names a key after the host's second-level label", async () => {
    const { suggestName, hostOf } = await import("../../components/connectionKeys/connectionKeysRequest");
    expect(suggestName("https://api.census.gov/data")).toBe("census");
    expect(suggestName("api.census.gov")).toBe("census");
    expect(suggestName("data.cityofchicago.org")).toBe("cityofchicago");
    expect(suggestName("localhost")).toBe("localhost");
    expect(suggestName("")).toBe("");
    expect(hostOf("https://user@API.Census.gov:8443/data?x=1")).toBe("api.census.gov");
    expect(hostOf("api.census.gov.")).toBe("api.census.gov");
  });
});
