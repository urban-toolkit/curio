/**
 * Import half of NotebookConvertor (#235).
 *
 * `NotebookConvertor.test.ts` covers the export direction and says so in its
 * own docstring; `notebookToTrill` had no coverage at all. The reported bug is
 * what these cases pin: a notebook whose setup lives in several small import
 * cells imported as a wall of disconnected, identically-named nodes, because
 * an import cell can carry no edges by construction and every node was left
 * untitled.
 */
jest.mock("uuid", () => {
  let calls = 0;
  return { v4: () => `id-${++calls}` };
});

import { mergeImportCells, notebookToTrill, SETUP_NODE_TITLE } from "../NotebookConvertor";
import { NodeType } from "../constants";

type Analysis = {
  defined?: string[];
  used?: string[];
  last_var?: string | null;
  altair_spec?: Record<string, unknown> | null;
  is_import_only?: boolean;
};

function notebook(...sources: string[]) {
  return {
    cells: sources.map((source) => ({
      cell_type: "code",
      source,
      metadata: {},
      outputs: [],
      execution_count: null,
    })),
    metadata: {},
    nbformat: 4,
    nbformat_minor: 5,
  } as unknown as Record<string, unknown>;
}

/** Stand in for POST /api/analyzeNotebook. */
function stubAnalyzer(analysis: Analysis[], edges: Array<[number, number]> = []) {
  (global as any).fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      edges: edges.map(([source, target]) => ({ source, target })),
      analysis: analysis.map((a) => ({
        defined: a.defined ?? [],
        used: a.used ?? [],
        last_var: a.last_var ?? null,
        altair_spec: a.altair_spec ?? null,
        is_import_only: a.is_import_only ?? false,
      })),
    }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
  delete (global as any).fetch;
});

describe("mergeImportCells", () => {
  it("deduplicates repeated imports and keeps first-seen order", () => {
    // Notebooks really do re-import pandas in three separate setup cells.
    expect(
      mergeImportCells([
        "import pandas as pd\nimport numpy as np",
        "import pandas as pd\nfrom sklearn.cluster import KMeans",
      ]),
    ).toBe(
      "import pandas as pd\nimport numpy as np\nfrom sklearn.cluster import KMeans",
    );
  });

  it("drops the blank lines that used to separate cells", () => {
    expect(mergeImportCells(["import os\n\n", "\nimport sys"])).toBe(
      "import os\nimport sys",
    );
  });

  it("keeps comments", () => {
    expect(mergeImportCells(["# geo stack\nimport geopandas as gpd"])).toBe(
      "# geo stack\nimport geopandas as gpd",
    );
  });
});

describe("notebookToTrill", () => {
  it("folds every import-only cell into one Setup node", async () => {
    stubAnalyzer(
      [
        { is_import_only: true },
        { is_import_only: true },
        { is_import_only: true },
        { last_var: "df" },
      ],
      [],
    );

    const { dataflow } = await notebookToTrill(
      notebook(
        "import pandas as pd",
        "import numpy as np",
        "import altair as alt",
        "df = load()",
      ),
      "http://backend",
    );

    // Four cells in, two nodes out: the three setup cells became one.
    expect(dataflow.nodes).toHaveLength(2);
    const setup = dataflow.nodes.filter((n) => n.title === SETUP_NODE_TITLE);
    expect(setup).toHaveLength(1);
    expect(setup[0].content).toBe(
      "import pandas as pd\nimport numpy as np\nimport altair as alt",
    );
    expect(setup[0].type).toBe(NodeType.COMPUTATION_ANALYSIS);
  });

  it("places the Setup node clear of the pipeline's first column", async () => {
    // It used to share column 0 with the first real stage, stacked above it.
    stubAnalyzer([{ is_import_only: true }, { last_var: "df" }], []);
    const { dataflow } = await notebookToTrill(
      notebook("import pandas as pd", "df = load()"),
      "http://backend",
    );
    const setup = dataflow.nodes.find((n) => n.title === SETUP_NODE_TITLE)!;
    const work = dataflow.nodes.find((n) => n.title !== SETUP_NODE_TITLE)!;
    expect(setup.x).toBeLessThan(work.x);
    expect(setup.y).toBeLessThan(work.y);
  });

  it("emits no Setup node when the notebook has no import-only cells", async () => {
    stubAnalyzer([{ last_var: "df" }, { last_var: "out" }], [[0, 1]]);
    const { dataflow } = await notebookToTrill(
      notebook("df = load()", "out = df.head()"),
      "http://backend",
    );
    expect(dataflow.nodes).toHaveLength(2);
    expect(dataflow.nodes.some((n) => n.title === SETUP_NODE_TITLE)).toBe(false);
  });

  it("remaps edges across the removed cells", async () => {
    // The merge shifts every later cell's index. Getting this wrong would
    // wire the graph to the wrong nodes, which is worse than the clutter.
    stubAnalyzer(
      [
        { is_import_only: true },
        { is_import_only: true },
        { last_var: "df" },
        { last_var: "out" },
      ],
      [[2, 3]],
    );

    const { dataflow } = await notebookToTrill(
      notebook(
        "import pandas as pd",
        "import numpy as np",
        "df = load()",
        "out = df.head()",
      ),
      "http://backend",
    );

    const byId = Object.fromEntries(dataflow.nodes.map((n) => [n.id, n]));
    expect(dataflow.edges).toHaveLength(1);
    expect(byId[dataflow.edges[0].source].title).toBe("df");
    expect(byId[dataflow.edges[0].target].title).toBe("out");
  });

  it("titles nodes from the variable they produce", async () => {
    // Otherwise every one renders as its template label - the "wall of
    // Python Computation" half of the report.
    stubAnalyzer([{ last_var: "trips" }, { last_var: null }], []);
    const { dataflow } = await notebookToTrill(
      notebook("trips = load()", "summarize()"),
      "http://backend",
    );
    expect(dataflow.nodes[0].title).toBe("trips");
    expect(dataflow.nodes[1].title).toBeUndefined();
  });

  it("wraps a wide level instead of stacking it forever", async () => {
    // Ten independent cells all land on level 0. As one column that is a
    // 4000px drop; wrapped, it stays roughly screen-shaped.
    stubAnalyzer(
      Array.from({ length: 10 }, (_, i) => ({ last_var: `v${i}` })),
      [],
    );
    const { dataflow } = await notebookToTrill(
      notebook(...Array.from({ length: 10 }, (_, i) => `v${i} = ${i}`)),
      "http://backend",
    );
    const maxY = Math.max(...dataflow.nodes.map((n) => n.y));
    const distinctX = new Set(dataflow.nodes.map((n) => n.x));
    expect(distinctX.size).toBeGreaterThan(1);
    expect(maxY).toBeLessThan(10 * 450);
  });

  it("keeps every cell when the backend is unreachable", async () => {
    // No analysis means nothing can be classified. Merging on a guess would
    // move code the user wrote into a node they did not.
    (global as any).fetch = jest.fn().mockRejectedValue(new Error("offline"));
    jest.spyOn(console, "warn").mockImplementation(() => {});

    const { dataflow } = await notebookToTrill(
      notebook("import pandas as pd", "df = load()", "out = df.head()"),
      "http://backend",
    );

    expect(dataflow.nodes).toHaveLength(3);
    expect(dataflow.nodes.some((n) => n.title === SETUP_NODE_TITLE)).toBe(false);
    // ...and the linear fallback still chains them.
    expect(dataflow.edges).toHaveLength(2);
  });

  it("ignores markdown cells", async () => {
    stubAnalyzer([{ last_var: "df" }], []);
    const nb = notebook("df = load()") as any;
    nb.cells.unshift({
      cell_type: "markdown",
      source: "# Title",
      metadata: {},
      outputs: [],
      execution_count: null,
    });
    const { dataflow } = await notebookToTrill(nb, "http://backend");
    expect(dataflow.nodes).toHaveLength(1);
  });
});
