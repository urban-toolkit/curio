import { agentCategoryKey } from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";

describe("agentCategoryKey", () => {
  it("maps each known manifest category to its own color key", () => {
    expect(agentCategoryKey("canvas")).toBe("canvas");
    expect(agentCategoryKey("data")).toBe("data");
    expect(agentCategoryKey("node")).toBe("node");
    expect(agentCategoryKey("evaluate")).toBe("evaluate");
    expect(agentCategoryKey("package")).toBe("package");
  });

  it("is case-insensitive", () => {
    expect(agentCategoryKey("Canvas")).toBe("canvas");
    expect(agentCategoryKey("EVALUATE")).toBe("evaluate");
  });

  it("falls back to default for absent or unknown categories", () => {
    expect(agentCategoryKey(undefined)).toBe("default");
    expect(agentCategoryKey(null)).toBe("default");
    expect(agentCategoryKey("")).toBe("default");
    expect(agentCategoryKey("mystery")).toBe("default");
  });
});
