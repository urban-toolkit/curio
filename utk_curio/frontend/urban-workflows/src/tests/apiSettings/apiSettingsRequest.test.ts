/** dev/116: the window-event bus between the cards and API Settings' one host. */
import {
  focusFromSearch,
  remedyFocus,
  requestConnectionKeys,
  settingsPath,
  subscribeApiSettingsRequests,
  tabForFocus,
  type ApiSettingsFocus,
} from "../../components/apiSettings/apiSettingsRequest";

describe("the settings page's URL for a card's request", () => {
  const cases: [ApiSettingsFocus | null, string][] = [
    [null, "/settings/keys"],
    [{ section: "agent-models", agentId: "agent.dataflow-builder" }, "/settings/agents?agent=agent.dataflow-builder"],
    [{ section: "agent-models" }, "/settings/agents"],
    [{ section: "llm-configs", configId: "c1" }, "/settings/keys?config=c1"],
    [{ section: "source-key", slot: "mapillary.token" }, "/settings/keys?service=mapillary.token"],
    [
      { section: "connection-keys", host: "api.census.gov", suggestedName: "census" },
      "/settings/keys?add=node&host=api.census.gov&name=census",
    ],
    [{ section: "connection-keys" }, "/settings/keys?add=node"],
  ];

  it.each(cases)("%j goes to %s", (focus, path) => {
    expect(settingsPath(focus)).toBe(path);
  });

  it.each(cases)("%j comes back from its URL", (focus, path) => {
    const url = new URL(path, "http://curio.test");
    const tab = url.pathname.split("/").pop() as "keys" | "agents";
    expect(tab).toBe(tabForFocus(focus));
    const back = focusFromSearch(tab, url.searchParams);
    // An agent-models focus with no agent is the tab's plain start.
    const expected = focus?.section === "agent-models" && !focus.agentId ? null : focus;
    expect(back).toEqual(
      expected?.section === "connection-keys"
        ? { section: "connection-keys", host: expected.host, suggestedName: expected.suggestedName }
        : expected,
    );
  });
});

describe("the request bus (dev/116)", () => {
  it("delivers a request to every subscriber until unsubscribed", () => {
    const seen: unknown[] = [];
    const off = subscribeApiSettingsRequests((focus) => seen.push(focus));
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
    const { suggestName, hostOf } = await import("../../components/apiSettings/apiSettingsRequest");
    expect(suggestName("https://api.census.gov/data")).toBe("census");
    expect(suggestName("api.census.gov")).toBe("census");
    expect(suggestName("data.cityofchicago.org")).toBe("cityofchicago");
    expect(suggestName("localhost")).toBe("localhost");
    expect(suggestName("")).toBe("");
    expect(hostOf("https://user@API.Census.gov:8443/data?x=1")).toBe("api.census.gov");
    expect(hostOf("api.census.gov.")).toBe("api.census.gov");
  });
});
