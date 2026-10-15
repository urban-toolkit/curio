/**
 * A loader of unknown type is checked once in the background, and the journal
 * answers first when it holds a run of exactly this code
 * (plans/data-loading-expressive-preview-memo.md, section 3.7).
 */
import { webcrypto } from "crypto";
import { TextEncoder as NodeTextEncoder } from "util";
import {
  journalDataTypeFor,
  normalizeCodeForDigest,
  normalizedCodeSha256,
  PROBES_PER_DATAFLOW,
  probeableCode,
  requestTypeProbe,
  resetTypeProbes,
  TYPE_PROBE_KIND,
} from "../../services/datasetCatalog/loaderTypeProbe";

jest.mock("../../utils/backendUrl", () => ({ backendUrl: () => "http://backend" }));
jest.mock("../../utils/authApi", () => ({ getToken: () => "tok" }));

beforeAll(() => {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
  if (typeof (globalThis as any).TextEncoder === "undefined") {
    (globalThis as any).TextEncoder = NodeTextEncoder;
  }
});

// Digests computed by the backend's own `runtime_journal.normalized_code_sha256`
// (textwrap.dedent + strip + SHA-256): the browser must reach the same ones.
const PYTHON_DIGESTS: [string, string, string][] = [
  ['df = pd.read_csv("a.csv")\nreturn df', 'df = pd.read_csv("a.csv")\nreturn df', "272ac6d5c49b7e0984bf050fc45fcece92df8fceb3bbf32741c5968b9d74d46b"],
  ['    df = pd.read_csv("a.csv")\n    return df\n', 'df = pd.read_csv("a.csv")\nreturn df', "272ac6d5c49b7e0984bf050fc45fcece92df8fceb3bbf32741c5968b9d74d46b"],
  ["  x = 1\n\n    y = 2\n  \n", "x = 1\n\n  y = 2", "be20961f139d7ef27c763fd61364157359a3597d943ea18ef031f0060edcff0c"],
  ["\tz = 1\n\tif z:\n\t\treturn z\n", "z = 1\nif z:\n\treturn z", "424603dcfc09c6c4645d6182a2f0d2b15ef00a16a74bce421db9c71ac4fc7419"],
  ["   \n  ", "", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
];

describe("the code digest matches the journal's", () => {
  it.each(PYTHON_DIGESTS)("%j", async (code, normalized, digest) => {
    expect(normalizeCodeForDigest(code)).toBe(normalized);
    await expect(normalizedCodeSha256(code)).resolves.toBe(digest);
  });

  it("is the same for the code Play sends, which is indented for the sandbox", async () => {
    const code = 'df = pd.read_csv("a.csv")\nreturn df';
    const sent = code.split("\n").map((l) => `    ${l}\n`).join("");
    await expect(normalizedCodeSha256(sent)).resolves.toBe(await normalizedCodeSha256(code));
  });
});

type FetchCall = { url: string; init?: RequestInit };

function mockFetch(reply: (call: FetchCall) => unknown | Promise<unknown>) {
  const calls: FetchCall[] = [];
  (globalThis as any).fetch = jest.fn(async (url: string, init?: RequestInit) => {
    const call = { url, init };
    calls.push(call);
    const body = await reply(call);
    return { ok: true, json: async () => body } as Response;
  });
  return calls;
}

describe("the journal", () => {
  const code = 'df = pd.read_csv("a.csv")\nreturn df';
  const digest = "272ac6d5c49b7e0984bf050fc45fcece92df8fceb3bbf32741c5968b9d74d46b";

  it("answers with a successful run of this exact code", async () => {
    mockFetch(() => ({ run: { status: "ok", output: { dataType: "dataframe" }, executedCodeSha256: digest } }));
    await expect(journalDataTypeFor("p1", "n1", code)).resolves.toBe("dataframe");
  });

  it("ignores a run of other code, and a failed run", async () => {
    mockFetch(() => ({ run: { status: "ok", output: { dataType: "dataframe" }, executedCodeSha256: "0".repeat(64) } }));
    await expect(journalDataTypeFor("p1", "n1", code)).resolves.toBeNull();
    mockFetch(() => ({ run: { status: "error", output: { dataType: "" }, executedCodeSha256: digest } }));
    await expect(journalDataTypeFor("p1", "n1", code)).resolves.toBeNull();
  });

  it("answers nothing without a record or a project", async () => {
    mockFetch(() => ({ run: null }));
    await expect(journalDataTypeFor("p1", "n1", code)).resolves.toBeNull();
    await expect(journalDataTypeFor("", "n1", code)).resolves.toBeNull();
  });
});

describe("the background run", () => {
  beforeEach(() => resetTypeProbes());

  const request = (nodeId: string, code = "x = build()\nreturn x", dataflowId = "p1") => ({
    dataflowId,
    nodeId,
    nodeType: "curio.builtin/data-loading",
    code,
  });

  it("runs the node's code as Play sends it, saving nothing, marked as a type probe", async () => {
    const calls = mockFetch(() => ({ output: { path: "artifact-1", dataType: "geodataframe" } }));
    await expect(requestTypeProbe(request("n1"))).resolves.toBe("geodataframe");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://backend/processPythonCode");
    const body = JSON.parse(String(calls[0].init?.body));
    expect(body).toMatchObject({
      nodeId: "n1",
      dataflowId: "p1",
      saveOutputDataset: false,
      purpose: TYPE_PROBE_KIND,
      code: "    x = build()\n    return x\n",
    });
  });

  it("answers null for a run that produced no output", async () => {
    mockFetch(() => ({ output: { path: "", dataType: "str" } }));
    await expect(requestTypeProbe(request("n1"))).resolves.toBeNull();
  });

  it("never runs the same code twice in a session", async () => {
    const calls = mockFetch(() => ({ output: { path: "a", dataType: "raster" } }));
    await requestTypeProbe(request("n1"));
    await expect(requestTypeProbe(request("n1"))).resolves.toBe("raster");
    expect(calls).toHaveLength(1);
  });

  it("runs one at a time", async () => {
    let inFlight = 0;
    let most = 0;
    mockFetch(async () => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight -= 1;
      return { output: { path: "a", dataType: "dataframe" } };
    });
    await Promise.all([requestTypeProbe(request("n1")), requestTypeProbe(request("n2")), requestTypeProbe(request("n3"))]);
    expect(most).toBe(1);
  });

  it(`runs at most ${PROBES_PER_DATAFLOW} per dataflow`, async () => {
    const calls = mockFetch(() => ({ output: { path: "a", dataType: "dataframe" } }));
    const asks = Array.from({ length: PROBES_PER_DATAFLOW + 3 }, (_, i) => requestTypeProbe(request(`n${i}`)));
    const answers = await Promise.all(asks);
    expect(calls).toHaveLength(PROBES_PER_DATAFLOW);
    expect(answers.filter((a) => a === null)).toHaveLength(3);
  });

  it("drops a probe cancelled before its answer", async () => {
    mockFetch(async () => {
      await new Promise((r) => setTimeout(r, 5));
      return { output: { path: "a", dataType: "dataframe" } };
    });
    const controller = new AbortController();
    const answer = requestTypeProbe(request("n1"), controller.signal);
    controller.abort();
    await expect(answer).resolves.toBeNull();
  });

  it("does not run code whose widget or input references need resolving first", async () => {
    const calls = mockFetch(() => ({ output: { path: "a", dataType: "dataframe" } }));
    expect(probeableCode('df = pd.read_csv([!! path !!])')).toBe(false);
    await expect(requestTypeProbe(request("n1", 'df = pd.read_csv([!! path !!])'))).resolves.toBeNull();
    expect(calls).toHaveLength(0);
  });
});
