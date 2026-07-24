import {
  attachmentDisplayName,
  TITLE_MAX_CHARS,
} from "../../components/agents/attach/attachmentDisplayName";

describe("attachmentDisplayName (memo dev/25)", () => {
  it("composes '<name>: <title>' when a conversation title exists", () => {
    expect(attachmentDisplayName({ name: "Chat", title: "Dataset Import Help" })).toBe(
      "Chat: Dataset Import Help",
    );
  });

  it("returns the plain template name when untitled — no trailing colon", () => {
    expect(attachmentDisplayName({ name: "Chat", title: null })).toBe("Chat");
    expect(attachmentDisplayName({ name: "Chat", title: "" })).toBe("Chat");
  });

  it("mirrors the backend title cap", () => {
    expect(TITLE_MAX_CHARS).toBe(40);
  });
});
