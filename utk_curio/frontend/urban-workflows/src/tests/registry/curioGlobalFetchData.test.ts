/**
 * A package's node reads an output the way the canvas does: the main bundle
 * publishes the canvas's own reader, `fetchData` (`services/api.ts`), on
 * `window.curio`. While a dataflow is open it reads on that dataflow's output
 * route (`services/dataflowReads.ts`), which reads an output the dataflow saved
 * from its owner's Data Catalog under any sign-in; with none open, on `/get`.
 *
 * The registry's side-effect imports (built-in behaviors, icons, grammar
 * adapters) are stubbed: only the `window.curio` it publishes is under test.
 */
jest.mock("../../registry/builtinBehaviors", () => ({}));
jest.mock("../../registry/iconRegistry", () => ({}));
jest.mock("../../adapters/vegaLiteAdapter", () => ({}));
jest.mock("../../adapters/autkGrammarAdapter", () => ({}));

import "../../registry";
import { fetchData } from "../../services/api";
import { setOpenDataflow } from "../../services/dataflowReads";

const originalFetch = global.fetch;
let asked: string[] = [];

const FRAME = { dataType: "dataframe", data: { population: [2746, 8804, 12] } };

function answer(body: unknown, headers: Record<string, string> = { "Content-Type": "application/json" }) {
    return {
        ok: true,
        status: 200,
        headers: { get: (name: string) => headers[name] ?? null, forEach: () => {} },
        json: async () => body,
        arrayBuffer: async () => new ArrayBuffer(4),
    };
}

/** What the main bundle published for package bundles. */
function curio(): any {
    return (window as any).curio;
}

beforeEach(() => {
    setOpenDataflow(null);
    asked = [];
    global.fetch = jest.fn(async (url: string) => {
        asked.push(String(url));
        return answer(FRAME);
    }) as unknown as typeof fetch;
});

afterEach(() => {
    global.fetch = originalFetch;
    setOpenDataflow(null);
});

test("packages get the reader the canvas reads outputs with", () => {
    expect(typeof curio()?.fetchData).toBe("function");
    expect(curio().fetchData).toBe(fetchData);
});

test("while a dataflow is open, a package reads an output on that dataflow's route", async () => {
    setOpenDataflow("df-1");

    const read = await curio().fetchData("art-1");

    expect(read).toEqual(FRAME);
    // Arrow, then JSON, both on the dataflow's route.
    expect(asked).toHaveLength(2);
    for (const url of asked) {
        expect(url).toContain("/api/projects/df-1/outputs/get?fileName=art-1");
    }
});

test("with no dataflow open, a package reads an output on /get", async () => {
    const read = await curio().fetchData("art-1");

    expect(read).toEqual(FRAME);
    expect(asked).toHaveLength(2);
    for (const url of asked) {
        expect(url).not.toContain("/api/projects/");
        expect(url).toContain("/get?fileName=art-1");
    }
});
