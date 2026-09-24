/**
 * The classifier moved out of `autkGrammarBehavior` so the dashboard's layout
 * pass can ask what an Autark node does without importing the WebGPU renderer.
 * It decides two things now: what a data/compute node reports in its body, and
 * whether a node is a pass-through (a render spec) or a source of layers.
 */
import { classifyAutkSpec, classifyAutkSpecString } from "../../utils/autkSpecKind";
import {
  classifyAutkSpec as reExportedSpec,
  classifyAutkSpecString as reExportedString,
} from "../../adapters/node/autkGrammarBehavior";

describe("classifyAutkSpec", () => {
  test("drawing wins over loading and computing", () => {
    expect(classifyAutkSpec({ map: {}, data: [{}], compute: [{}] })).toBe("render");
    expect(classifyAutkSpec({ plot: {} })).toBe("render");
  });

  test("compute wins over data", () => {
    expect(classifyAutkSpec({ data: [{}], compute: [{ shader: "x" }] })).toBe("compute");
  });

  test("data alone is data", () => {
    expect(classifyAutkSpec({ data: [{}] })).toBe("data");
  });

  test("empty sections say nothing", () => {
    expect(classifyAutkSpec({ data: [], compute: [] })).toBe("unknown");
    expect(classifyAutkSpec(null)).toBe("unknown");
    expect(classifyAutkSpec("a string")).toBe("unknown");
  });
});

describe("classifyAutkSpecString", () => {
  test("it parses the buffer a node carries", () => {
    expect(classifyAutkSpecString('{"map": {}}')).toBe("render");
    expect(classifyAutkSpecString('{"data": [{}]}')).toBe("data");
  });

  test("anything unparseable is unknown rather than a throw", () => {
    expect(classifyAutkSpecString("{ not json")).toBe("unknown");
    expect(classifyAutkSpecString(undefined)).toBe("unknown");
    expect(classifyAutkSpecString("")).toBe("unknown");
  });
});

test("the behaviour still exports it, so existing callers are unaffected", () => {
  expect(reExportedSpec).toBe(classifyAutkSpec);
  expect(reExportedString).toBe(classifyAutkSpecString);
});
