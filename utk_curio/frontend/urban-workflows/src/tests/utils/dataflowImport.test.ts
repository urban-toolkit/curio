import {
  looksLikeJsonFile,
  parseDataflowFile,
  loadFailedMessage,
} from "../../utils/dataflowImport";

/**
 * #238: "Load dataflow" on a malformed file changed nothing and said nothing.
 *
 * The parsing lives here rather than in UpMenu so the three distinct failures
 * can be asserted without the provider stack that component needs to mount.
 * Which failure it is matters: a wrong-shaped dataflow reported as "invalid
 * JSON" sends the user looking for a syntax error in a well-formed file.
 */

describe("deciding whether to try reading a file", () => {
  it("accepts a .json the browser labelled application/json", () => {
    expect(looksLikeJsonFile({ name: "flow.json", type: "application/json" })).toBe(true);
  });

  it("accepts a .json the OS gave no type for", () => {
    // Windows reports "" whenever nothing is registered for the extension, and
    // the old `file.type === "application/json"` gate refused valid dataflows
    // there - on the very platform #238 was filed from.
    expect(looksLikeJsonFile({ name: "flow.json", type: "" })).toBe(true);
    expect(looksLikeJsonFile({ name: "FLOW.JSON", type: "text/plain" })).toBe(true);
  });

  it("still refuses something that is plainly not a dataflow file", () => {
    expect(looksLikeJsonFile({ name: "notes.txt", type: "text/plain" })).toBe(false);
    expect(looksLikeJsonFile({ name: "sheet.csv", type: "" })).toBe(false);
  });
});

describe("parsing a picked dataflow file", () => {
  it("names the syntax error rather than staying quiet", () => {
    const res = parseDataflowFile("{ this is not valid JSON }");
    expect(res.ok).toBe(false);
    if (res.ok) throw new Error("expected a failure");
    expect(res.message).toMatch(/not valid JSON/i);
    // The parser's own complaint is carried through so the user can find the
    // offending character instead of re-reading the whole file.
    expect(res.message).toMatch(/\(.+\)/);
  });

  it("distinguishes valid JSON that is not a Curio dataflow", () => {
    const res = parseDataflowFile('{"hello": "world"}');
    expect(res.ok).toBe(false);
    if (res.ok) throw new Error("expected a failure");
    expect(res.message).toMatch(/valid JSON but not a Curio dataflow/i);
    expect(res.message).not.toMatch(/not valid JSON/i);
  });

  it("rejects a bare array and a bare null, which are valid JSON", () => {
    expect(parseDataflowFile("[]").ok).toBe(false);
    expect(parseDataflowFile("null").ok).toBe(false);
  });

  it("rejects a dataflow whose nodes are not a list", () => {
    // loadTrill iterates `trill.dataflow.nodes`, so anything else throws a
    // TypeError halfway through the replay rather than failing up front.
    expect(parseDataflowFile('{"dataflow": {"nodes": {}}}').ok).toBe(false);
    expect(parseDataflowFile('{"dataflow": {}}').ok).toBe(false);
  });

  it("accepts a real dataflow and hands back the parsed spec", () => {
    const res = parseDataflowFile(
      '{"dataflow": {"name": "f", "nodes": [{"id": "n1"}], "edges": []}}',
    );
    expect(res.ok).toBe(true);
    if (!res.ok) throw new Error("expected success");
    expect(res.spec.dataflow.nodes).toHaveLength(1);
  });

  it("accepts an empty dataflow, which is a legitimate thing to save", () => {
    expect(parseDataflowFile('{"dataflow": {"nodes": [], "edges": []}}').ok).toBe(true);
  });
});

describe("reporting a replay that threw", () => {
  it("carries the reason through", () => {
    expect(loadFailedMessage(new Error("unknown node type"))).toMatch(/unknown node type/);
  });

  it("still says something when there is no reason to carry", () => {
    expect(loadFailedMessage(undefined)).toMatch(/could not be loaded/i);
  });
});
