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
