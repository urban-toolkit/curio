/**
 * dev/117: the editor's credential-literal detector — the TypeScript twin of
 * the backend's. The FIXTURES below are asserted, string for string, by
 * `utk_curio/backend/tests/test_agents/test_source_grounding.py::TestConnectionKeys::
 * test_shared_fixtures_with_the_editor_detector` — change both or neither.
 */
import {
  MAX_FINDINGS,
  credentialLiterals,
  findingsKey,
  firstHostInCode,
} from "../../../services/connectionKeys/credentialLiterals";

const VALUE = "AbCdEf0123456789xyzXYZ-_";

/** [code, expected names] — shared with the backend test. */
export const POSITIVE_FIXTURES: Array<[string, string[]]> = [
  [`api_key = "${VALUE}"`, ["api_key"]],
  [`params = {"get": "NAME", "key": "${VALUE}"}`, ["key"]],
  [`headers = {"Authorization": "Bearer ${VALUE}"}`, ["Authorization"]],
  [`r = requests.get(u, token="${VALUE}")`, ["token"]],
  [`ACCESS_TOKEN = '${VALUE}'`, ["ACCESS_TOKEN"]],
];

/** Code that must NOT be a finding on either side. */
export const NEGATIVE_FIXTURES: string[] = [
  `key = "https://api.census.gov/data/2022/acs/acs5"`, // a URL is a source
  `key = "/data/exports/census_tracts_2022_final.csv"`, // a path is a source
  `key = "census_tracts_2022_final_export.csv"`, // a data file
  `dataset = "imported.census-acs@1"`, // not a credential name, and '@' is outside the value charset
  `api_key = curio_secret("census")`, // the sanctioned form
  `api_key = os.environ["CENSUS_KEY"]`, // not a literal
  `key = "short"`, // under the length bound
  `monkey = "${VALUE}"`, // the name must start a token
  `params = {"get": "NAME,B19013_001E,B01003_001E"}`, // a long value under a non-credential name
];

describe("credentialLiterals (dev/117)", () => {
  it("finds the shared positive fixtures by name and line, never returning the value", () => {
    for (const [code, names] of POSITIVE_FIXTURES) {
      const found = credentialLiterals(code, "python");
      expect(found.map((f) => f.name)).toEqual(names);
      expect(found.every((f) => f.line === 1)).toBe(true);
      expect(JSON.stringify(found)).not.toContain(VALUE);
    }
  });

  it("ignores the shared negative fixtures", () => {
    for (const code of NEGATIVE_FIXTURES) {
      expect(credentialLiterals(code, "python")).toEqual([]);
    }
  });

  it("reports the line of each finding and the JavaScript shapes", () => {
    const py = `import requests\n\napi_key = "${VALUE}"\nurl = "https://x.org"\nheaders = {"X-Api-Key": "${VALUE}"}`;
    expect(credentialLiterals(py, "python")).toEqual([
      { name: "api_key", line: 3 },
      { name: "X-Api-Key", line: 5 },
    ]);
    const js = `const token = "${VALUE}";\nconst cfg = { apiKey: '${VALUE}' };\nlet monkey = "${VALUE}";`;
    expect(credentialLiterals(js, "javascript")).toEqual([
      { name: "token", line: 1 },
      { name: "apiKey", line: 2 },
    ]);
  });

  it("is bounded and never crashes on odd input", () => {
    const many = Array.from({ length: 20 }, (_, i) => `key${i > 0 ? "" : ""} = "${VALUE}${i}"`).join("\n");
    expect(credentialLiterals(many, "python")).toHaveLength(MAX_FINDINGS);
    expect(credentialLiterals("", "python")).toEqual([]);
    expect(credentialLiterals(undefined, "python")).toEqual([]);
    expect(credentialLiterals(42 as unknown as string, "python")).toEqual([]);
    expect(credentialLiterals(`key = "${VALUE}`, "python")).toEqual([]); // unterminated: no match
  });

  it("findingsKey is stable and changes when a finding moves", () => {
    const a = credentialLiterals(`api_key = "${VALUE}"`, "python");
    const b = credentialLiterals(`\napi_key = "${VALUE}"`, "python");
    expect(findingsKey(a)).toBe("api_key@1");
    expect(findingsKey(b)).toBe("api_key@2");
    expect(findingsKey([])).toBe("");
  });

  it("firstHostInCode is the bare hostname of the first http(s) literal", () => {
    expect(firstHostInCode(`url = "https://api.census.gov/data/2022?x=1"\nother = "https://b.org"`)).toBe("api.census.gov");
    expect(firstHostInCode(`u = "http://user@Host.Example:8443/path"`)).toBe("host.example");
    expect(firstHostInCode("no urls here")).toBeNull();
    expect(firstHostInCode(null)).toBeNull();
  });
});
