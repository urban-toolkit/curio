import React from "react";
import { subscribeApiSettingsRequests } from "../../components/apiSettings/apiSettingsRequest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { faCircle } from "@fortawesome/free-solid-svg-icons";

import { AgentChangeCard } from "../../components/agents/content/AgentChangeCard";
import type { PlanNodeReviewState } from "../../components/agents/content/AgentReviewCard";
import { PREVIEW_LINES } from "../../components/agents/content/reviewCard/CodePreview";
import { registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";
import type { AgentChangePart } from "../../services/agents";

/** A template the registry knows, as a new node's card names its kind. */
const PYTHON = "curio.builtin/python-computation@1";
beforeAll(() => {
  registerNode({
    id: PYTHON,
    category: "computation",
    label: "Python Computation",
    icon: faCircle,
    inputPorts: [],
    outputPorts: [],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
  } as unknown as NodeDescriptor);
});

/** A change an agent made, as its turn's card carries it (`changes.card`). */
const change = (overrides: Partial<AgentChangePart> = {}): AgentChangePart => ({
  type: "change",
  changeId: "c1",
  tool: "node.content.write",
  kind: "content",
  summary: "Replaced the content of the Python node · n1",
  preview: "print(2)",
  status: "applied",
  lines: ["Python · n1"],
  nodeId: "n1",
  ...overrides,
});

describe("AgentChangeCard (an agent's change, landed, with its Undo)", () => {
  it("says what the change did, to its node by the name its header shows, and offers Undo, never Apply or Dismiss", () => {
    render(<AgentChangeCard part={change()} nodeName="Load parks" onUndo={jest.fn()} />);
    // Its accessible name keeps the change's own summary, which the agents read.
    const card = screen.getByRole("group", { name: "Change: Replaced the content of the Python node · n1" });
    expect(within(card).getByText("Replaced the code of Load parks")).toBeInTheDocument();
    // Its line named the node again: the title names it.
    expect(screen.queryByText("Python · n1")).toBeNull();
    expect(screen.getByText("print(2)")).toBeInTheDocument();
    // Its title says what it is: no chip names its kind.
    expect(screen.queryByText("code")).toBeNull();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
  });

  it("the code renders model output inert (REQ-SEC-002)", () => {
    const hostile = change({ preview: '<script>window.__changePwned = true;</script>' });
    const { container } = render(<AgentChangeCard part={hostile} onUndo={jest.fn()} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("<script>");
    expect((window as unknown as { __changePwned?: boolean }).__changePwned).toBeUndefined();
  });

  it("Undo routes the change's id through the callback and shows the busy state", async () => {
    let release: () => void = () => undefined;
    const onUndo = jest.fn().mockImplementation(
      () => new Promise<void>((r) => {
        release = r;
      }),
    );
    render(<AgentChangeCard part={change()} onUndo={onUndo} />);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalledWith("c1");
    expect(screen.getByRole("button", { name: "Undoing…" })).toBeDisabled();
    release();
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo" })).not.toBeDisabled());
  });

  it("a refused Undo says who changed it after, and that nothing was undone", async () => {
    const onUndo = jest.fn().mockRejectedValue(new Error("Ana changed this node after; nothing was undone."));
    render(<AgentChangeCard part={change()} onUndo={onUndo} />);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Ana changed this node after; nothing was undone."),
    );
    // The change stands: its Undo is still there.
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("an undone change renders inert, saying so", () => {
    const { container } = render(<AgentChangeCard part={change({ status: "undone" })} onUndo={jest.fn()} />);
    expect(container.querySelector("button")).toBeNull();
    expect(screen.getByText("Undone")).toBeInTheDocument();
  });

  it("without an Undo callback the card offers none (a read-only chat)", () => {
    const { container } = render(<AgentChangeCard part={change()} />);
    expect(container.querySelector("button")).toBeNull();
  });

  it.each([
    ["content", change({ kind: "content" }), "Load parks", "Replaced the code of Load parks", "code"],
    [
      "settings",
      change({ kind: "settings", tool: "node.settings.write", summary: "Changed the settings of the Data Pool node" }),
      "Pools",
      "Changed the settings of Pools",
      "settings",
    ],
    [
      "new node",
      change({ kind: "node", tool: "node.create", summary: "Created a new Python Computation node", nodeType: PYTHON }),
      "Python Computation",
      "Added a Python Computation node",
      "new node",
    ],
    [
      "new node with a title",
      change({ kind: "node", tool: "node.create", summary: "Created a new Python Computation node · Load parks", nodeType: PYTHON }),
      "Load parks",
      "Added Load parks, a Python Computation node",
      "new node",
    ],
  ])("a %s change's title says what it did, and no chip names its kind", (_kind, part, nodeName, title, chip) => {
    render(<AgentChangeCard part={{ ...part, preview: "" }} nodeName={nodeName} />);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.queryByText(chip)).toBeNull();
  });

  it("names its node by the change's own words once the node is not on the canvas", () => {
    const { unmount } = render(<AgentChangeCard part={change()} nodeName={null} />);
    expect(screen.getByText("Replaced the content of the Python node · n1")).toBeInTheDocument();
    unmount();
    // A new node taken back by its Undo still says its kind.
    render(
      <AgentChangeCard
        part={change({ kind: "node", tool: "node.create", summary: "Created a new Python Computation node", nodeType: PYTHON, status: "undone" })}
        nodeName={null}
      />,
    );
    expect(screen.getByText("Added a Python Computation node")).toBeInTheDocument();
    expect(screen.getByText("Undone")).toBeInTheDocument();
  });

  it("shows a long code's first lines, and all of it on Show all", () => {
    const code = Array.from({ length: 20 }, (_, i) => `line_${i + 1} = ${i + 1}`).join("\n");
    render(<AgentChangeCard part={change({ preview: code })} />);
    expect(screen.getByText(new RegExp(`line_${PREVIEW_LINES} = `))).toBeInTheDocument();
    expect(screen.queryByText(/line_20 = 20/)).toBeNull();
    const all = screen.getByRole("button", { name: "Show all 20 lines" });
    expect(all).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(all);
    expect(screen.getByText(/line_20 = 20/)).toBeInTheDocument();
    const less = screen.getByRole("button", { name: "Show less" });
    expect(less).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(less);
    expect(screen.queryByText(/line_20 = 20/)).toBeNull();
  });

  it("shows short code whole, with no Show all", () => {
    const code = Array.from({ length: PREVIEW_LINES + 1 }, (_, i) => `v${i} = ${i}`).join("\n");
    render(<AgentChangeCard part={change({ preview: code })} />);
    expect(screen.getByText(new RegExp(`v${PREVIEW_LINES} = ${PREVIEW_LINES}`))).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Show all/ })).toBeNull();
  });
});

describe("AgentChangeCard: a settings change names the node and says each change in the node's own words", () => {
  // The lines are the backend's (agents/domain/node_settings.describe_change
  // and widget_grammar.describe_value), each in its node's words.
  const settings = (settingLines: string[]) =>
    change({
      tool: "node.settings.write",
      kind: "settings",
      summary: "Changed the settings of the Data Pool node · Picked photos",
      preview: settingLines.join("\n"),
      settingLines,
      lines: ["Picked photos", ...settingLines],
      nodeId: "pool",
    });

  it("the header names the node, each change is a line of its own, and there is no code", () => {
    const lines = ["Conflict inside visualization: Overwrite", "Conflict between visualizations: Merge (AND)"];
    render(<AgentChangeCard part={settings(lines)} nodeName="Picked photos" onUndo={jest.fn()} />);
    expect(screen.getByText("Changed the settings of Picked photos")).toBeInTheDocument();
    for (const line of lines) expect(screen.getAllByText(line)).toHaveLength(1);
    // The line that named the node is the title's.
    expect(screen.queryByText("Picked photos")).toBeNull();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("a card from before the settings' own lines says them from its lines, without the node's", () => {
    const part = { ...settings(["Combine: max"]), settingLines: undefined };
    render(<AgentChangeCard part={part} nodeName="Picked photos" />);
    expect(screen.getAllByText("Combine: max")).toHaveLength(1);
    expect(screen.queryByText("Picked photos")).toBeNull();
  });

  it.each([
    ["a view's image column", "Image column: overlay_url"],
    ["every image column", "Image column: all"],
    ["a join's operation", "operation within"],
    ["a widget's value, by its label", "Combine: max"],
  ])("%s reads as its node says it, once", (_what, line) => {
    render(<AgentChangeCard part={settings([line])} />);
    expect(screen.getAllByText(line)).toHaveLength(1);
  });
});

describe("AgentChangeCard: a new node", () => {
  const source = { kind: "external", label: "x", refs: [{ kind: "external", value: "https://a.org", verification: { status: "verified" } }] };
  const created = (overrides: Partial<AgentChangePart>) =>
    change({
      tool: "node.create",
      kind: "node",
      summary: "Created a new Data Loading node",
      lines: ["Load · curio.builtin/data-loading", "node n9"],
      ...overrides,
    });

  it("says nothing of what Solve does with it: the guide does", () => {
    for (const executable of [true, false]) {
      const { unmount } = render(<AgentChangeCard part={created({ nodeType: "some.pkg/custom-python@1", executable, source })} />);
      expect(screen.queryByText(/Solve runs it in the sandbox/)).toBeNull();
      expect(screen.queryByText(/has no code to run/)).toBeNull();
      unmount();
    }
  });

  it("its kind and its id are run details", () => {
    const { unmount } = render(<AgentChangeCard part={created({})} />);
    expect(screen.queryByText("Load · curio.builtin/data-loading")).toBeNull();
    expect(screen.queryByText("node n9")).toBeNull();
    unmount();
    render(<AgentChangeCard part={created({})} runDetails />);
    expect(screen.getByText("Load · curio.builtin/data-loading")).toHaveAttribute("data-curio-run-details");
    expect(screen.getByText("node n9")).toHaveAttribute("data-curio-run-details");
  });
});

describe("AgentChangeCard: dev/114 (DEC-072) the source, on one line", () => {
  const withSource = (source: AgentChangePart["source"]) =>
    change({ tool: "node.create", kind: "node", summary: "Created a new Data Loading node", source });
  const line = () => screen.getByRole("group", { name: "Data source" });

  it("names a Data Catalog source by its title, its format and id on the line's tooltip", () => {
    render(
      <AgentChangeCard
        part={withSource({
          kind: "catalog",
          label: "Data Catalog · Census ACS 5-year (parquet)",
          refs: [{ kind: "catalog", value: 'curio_data_path("imported.acs@1")',
                   datasetId: "imported.acs@1", title: "Census ACS 5-year", format: "parquet" }],
        })}
      />,
    );
    expect(line()).toHaveTextContent(/^Source: Census ACS 5-year, Data Catalog$/);
    expect(line()).toHaveAttribute("data-tooltip", "Census ACS 5-year (parquet) · imported.acs@1");
  });

  it("an external URL the runtime verified needs no chip", () => {
    render(
      <AgentChangeCard
        part={withSource({
          kind: "external",
          label: "External · https://api.noaa.gov/climate · verified",
          refs: [{ kind: "external", value: "https://api.noaa.gov/climate",
                   verification: { status: "verified", httpStatus: 200 } }],
        })}
      />,
    );
    expect(line()).toHaveTextContent(/^Source: https:\/\/api\.noaa\.gov\/climate, External source$/);
    expect(screen.queryByText("Verified ✓")).toBeNull();
  });

  it("an external source that may not work keeps its chip, and says a credential-gated endpoint and an unchecked path on its tooltip", () => {
    render(
      <AgentChangeCard
        part={withSource({
          kind: "mixed",
          label: "…",
          refs: [
            { kind: "external", value: "https://api.x.gov/v1", requirement: "credential-gated",
              verification: { status: "unreachable", httpStatus: 401 } },
            { kind: "user-path", value: "data/tracts.geojson" },
          ],
        })}
      />,
    );
    expect(line()).toHaveTextContent("Sources: https://api.x.gov/v1, External source; data/tracts.geojson, User-provided path");
    // Whatever the probe's words, a chip that says the source may not work.
    expect(within(line()).getByText(/✗$/)).toBeInTheDocument();
    expect(line()).toHaveAttribute(
      "data-tooltip",
      "https://api.x.gov/v1 · credential-gated\ndata/tracts.geojson (not checked by Curio)",
    );
  });

  it("labels synthetic data as made up in the node", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "synthetic", label: "Synthetic · generated in the node, no external source",
                           refs: [{ kind: "synthetic" }] })}
      />,
    );
    expect(line()).toHaveTextContent(/^Source: Synthetic data$/);
    expect(line()).toHaveAttribute("data-tooltip", "generated in the node, no external source");
  });

  it("names the calls that made values up, as the user asked, beside another source", () => {
    render(
      <AgentChangeCard
        part={withSource({
          kind: "mixed",
          label: "Data Catalog · Tracts (csv) · Synthetic · np.random.randint",
          refs: [
            { kind: "catalog", title: "Tracts", format: "csv", datasetId: "tracts" },
            { kind: "synthetic", value: "np.random.randint" },
          ],
        })}
      />,
    );
    expect(line()).toHaveTextContent("Sources: Tracts, Data Catalog; np.random.randint, Synthetic data");
    expect(line()).toHaveAttribute("data-tooltip", "Tracts (csv) · tracts\nnp.random.randint (made up in the node, as the user asked)");
    expect(line()).not.toHaveTextContent("no external source");
  });

  it("names the values the user typed that the code added to the node's own", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "user-values", label: "User-provided values · 'J', 'K', 60, 33",
                           refs: [{ kind: "user-values", value: "'J', 'K', 60, 33" }] })}
      />,
    );
    expect(line()).toHaveTextContent("Source: 'J', 'K', 60, 33, User-provided values");
    expect(line()).toHaveAttribute("data-tooltip", "'J', 'K', 60, 33 (typed in the chat)");
  });

  it("renders no source when the change carries none", () => {
    render(<AgentChangeCard part={change()} />);
    expect(screen.queryByRole("group", { name: "Data source" })).toBeNull();
  });

  it("source text is model-derived data and renders inert", () => {
    const { container } = render(
      <AgentChangeCard
        part={withSource({ kind: "user-path", label: "x",
                           refs: [{ kind: "user-path", value: "<img src=x onerror=\"window.__srcPwned=1\">" }] })}
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
  });

  it("a secret ref reads as a connection key by name, its host on the tooltip: never a value (dev/116)", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "mixed", label: "External · … · Connection key · census", refs: [
          { kind: "external", value: "https://api.census.gov/data", verification: { status: "verified", httpStatus: 200 } },
          { kind: "secret", value: 'curio_secret("census")', name: "census", host: "api.census.gov", delivery: "query:key" },
        ] })}
      />,
    );
    expect(line()).toHaveTextContent("census, Connection key");
    expect(line().getAttribute("data-tooltip")).toContain("Connection key · census · api.census.gov");
    expect(line()).not.toHaveTextContent("query:key");
    expect(line().getAttribute("data-tooltip")).not.toContain("query:key");
  });

  it("a credential-gated external ref's saved-key hint is on the line's tooltip (dev/116)", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "external", label: "x", refs: [
          { kind: "external", value: "https://api.census.gov/data", requirement: "credential-gated",
            hint: "a connection key 'census' is saved for this host: use api_key = curio_secret(\"census\")",
            verification: { status: "unreachable", httpStatus: 401 } },
        ] })}
      />,
    );
    expect(line().getAttribute("data-tooltip")).toMatch(/credential-gated \(a connection key 'census' is saved/);
  });
});

describe("AgentChangeCard: dev/67-7 the check of code that landed, on one line", () => {
  const validated = (verdict: string, evidence = {}) =>
    change({ validation: { verdict, rounds: verdict === "pass" ? 1 : 3, evidence } });
  const check = () => screen.getByRole("status");

  it("says the code ran in the sandbox, and what it put out", () => {
    render(<AgentChangeCard part={validated("pass", { outputDataType: "geodataframe" })} onUndo={jest.fn()} />);
    expect(check()).toHaveAccessibleName("Validation pass");
    expect(check()).toHaveTextContent(/^Ran in the sandbox: a GeoDataFrame$/);
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("says why it failed, with the traceback", () => {
    const { unmount } = render(
      <AgentChangeCard part={validated("fail", { kind: "execution-error", detail: "node 'n1' failed", stderrTail: "Traceback: KeyError" })} />,
    );
    expect(check()).toHaveAccessibleName("Validation fail");
    expect(check()).toHaveTextContent(/^node 'n1' failed \(3 rounds\)/);
    expect(screen.getByText("Traceback: KeyError")).toBeInTheDocument();
    unmount();
    // With no reason of its own, how many rounds it took.
    render(<AgentChangeCard part={validated("fail", { kind: "execution-error", stderrTail: "Traceback: KeyError" })} />);
    expect(check()).toHaveTextContent(/^Validation failed after 3 rounds/);
    expect(screen.getByText("Traceback: KeyError")).toBeInTheDocument();
  });

  it("names an upstream blocker instead of blaming the node", () => {
    render(<AgentChangeCard part={validated("fail", { kind: "upstream-blocker", blockerLabel: "Load CSV" })} />);
    expect(screen.getByText(/Upstream node Load CSV failed/)).toBeInTheDocument();
  });

  it("changes without validation render no check", () => {
    render(<AgentChangeCard part={change()} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("AgentChangeCard: dev/115 every round, under Verification", () => {
  const executed = change({
    validation: {
      verdict: "pass",
      rounds: 2,
      evidence: { kind: "executed", outputDataType: "dataframe", durationMs: 4120 },
      attempts: [
        { round: 1, verdict: "fail", kind: "execution-error", source: "current content",
          detail: "node 'n1' failed", stderrTail: "requests.exceptions.HTTPError: 400 Client Error" },
        { round: 2, verdict: "pass", kind: "executed", source: "generated", outputDataType: "dataframe", durationMs: 4120 },
      ],
    },
  });

  it("lists every round under a collapsed disclosure, errors nested", () => {
    render(<AgentChangeCard part={executed} onUndo={jest.fn()} />);
    const summary = screen.getByText("Verification: 2 rounds");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    const list = screen.getByRole("list", { name: "Verification attempts" });
    expect(list).toHaveTextContent("Round 1 · fail · execution-error · the node's current code");
    expect(list).toHaveTextContent("Round 2 · pass ✓");
    expect(list).toHaveTextContent("output: dataframe · 4.1 s");
    expect(list).toHaveTextContent("400 Client Error");
    // The code on the card is the code that ran, and it landed: Undo puts back the code before.
    expect(screen.getByRole("button", { name: "Undo" })).not.toBeDisabled();
  });

  it("says each round carries its code when every round that failed does", () => {
    const withCode = change({
      validation: {
        ...executed.validation!,
        attempts: [{ ...executed.validation!.attempts![0], code: "load()" }, executed.validation!.attempts![1]],
      },
    });
    render(<AgentChangeCard part={withCode} />);
    expect(screen.getByText("Verification: 2 rounds, each with its code")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Verification attempts" })).toHaveTextContent("The code this attempt ran");
  });

  it("a failed round names what the endpoint actually answered (dev/115 field fix)", () => {
    const withEndpoint = change({
      validation: {
        ...executed.validation!,
        attempts: [
          { ...executed.validation!.attempts![0],
            endpointEvidence: 'https://api.census.gov/data/2022/acs/acs5?get=NAME → verified 200: answered an HTML page titled "Missing Key"' },
          executed.validation!.attempts![1],
        ],
      },
    });
    render(<AgentChangeCard part={withEndpoint} />);
    const list = screen.getByRole("list", { name: "Verification attempts" });
    expect(list).toHaveTextContent('Endpoint: https://api.census.gov/data/2022/acs/acs5?get=NAME → verified 200: answered an HTML page titled "Missing Key"');
    // A passing round never carries one.
    expect(list.textContent!.match(/Endpoint:/g)).toHaveLength(1);
  });

  it("no trail renders without attempts", () => {
    render(<AgentChangeCard part={change({ validation: { verdict: "pass", rounds: 1 } })} />);
    expect(screen.queryByText(/^Verification/)).toBeNull();
  });

  it("a failed attempt with a missing-key remedy offers Add key for the host, which asks for the settings form (dev/116)", () => {
    const seen: unknown[] = [];
    const off = subscribeApiSettingsRequests((f) => seen.push(f));
    const failed = change({
      validation: { verdict: "pass", rounds: 3, attempts: [
        { round: 1, verdict: "fail", kind: "execution-error", detail: "node failed", stderrTail: "JSONDecodeError" },
        { round: 2, verdict: "fail", kind: "source-missing", detail: "the content builder declined: The Census API requires an API key",
          remedy: { kind: "connection-key", host: "api.census.gov", suggestedName: "census" } },
        { round: 3, verdict: "pass", kind: "executed", outputDataType: "dataframe" },
      ] },
    });
    render(<AgentChangeCard part={failed} />);
    fireEvent.click(screen.getByRole("button", { name: "Add key for api.census.gov" }));
    expect(seen).toEqual([{ section: "connection-keys", host: "api.census.gov", suggestedName: "census" }]);
    off();
  });

  it("a use-connection-key remedy is a sentence, not a button (dev/116)", () => {
    const failed = change({
      validation: { verdict: "pass", rounds: 2, attempts: [
        { round: 1, verdict: "fail", kind: "source-missing", detail: "declined",
          remedy: { kind: "use-connection-key", host: "api.census.gov", name: "census" } },
        { round: 2, verdict: "pass", kind: "executed" },
      ] },
    });
    render(<AgentChangeCard part={failed} />);
    expect(screen.queryByRole("button", { name: /Add key/ })).toBeNull();
    expect(screen.getByText(/A connection key "census" is saved for api.census.gov. Solve again/)).toBeInTheDocument();
  });

  it("a not-executable attempt and a reused upstream are said in words (dev/118)", () => {
    render(
      <AgentChangeCard
        part={change({ validation: { verdict: "pass", rounds: 2, attempts: [
          { round: 1, verdict: "fail", kind: "execution-error", detail: "boom", reusedNodes: ["load"] },
          { round: 2, verdict: "pass", kind: "executed", outputDataType: "dataframe", reusedNodes: ["load"], reuseRetried: true },
        ] } })}
      />,
    );
    const list = screen.getByRole("list", { name: "Verification attempts" });
    expect(list).toHaveTextContent("Round 1 · fail · execution-error");
    expect(list.textContent!.match(/reused 1 upstream result/g)).toHaveLength(2);
    expect(list).toHaveTextContent("(re-run whole once)");
    render(
      <AgentChangeCard
        part={change({ changeId: "c2", validation: { verdict: "not-executable", rounds: 1, attempts: [
          { round: 1, verdict: "not-executable", kind: "not-executable", detail: "vis-vega has no code the sandbox could run" },
        ] } })}
      />,
    );
    expect(screen.getAllByRole("list", { name: "Verification attempts" })[1]).toHaveTextContent(
      "Round 1 · not executable: no code to run, nothing ran",
    );
  });
});

/** A plan the agent landed, as its turn's card carries it. */
const planChange = (plan: AgentChangePart["plan"], overrides: Partial<AgentChangePart> = {}) =>
  change({
    tool: "dataflow.plan.write",
    kind: "plan",
    planId: "plan-1",
    nodeId: undefined,
    summary: "Plan · 2 nodes, 1 edges",
    preview: "should not render: a plan's nodes are rows",
    lines: ["+2 nodes · +1 connection", "2 pending for Build & validate or Solve"],
    plan,
    ...overrides,
  });

/** Opens a plan card's Details. */
const openDetails = () => {
  fireEvent.click(screen.getByRole("button", { name: "Details" }));
  return screen.getByRole("group", { name: "Plan details" });
};

describe("AgentChangeCard: dev/52 a landed plan", () => {
  const plan = planChange({
    goal: "heat analysis",
    nodes: [
      { ref: "a", nodeType: "curio.builtin/data-loading", title: "Load", intent: "load it", expects: "in: none · out: dataframe" },
      { ref: "b", nodeType: "curio.builtin/python-computation", title: "Analyze", intent: "crunch it" },
    ],
    edgeCount: 1,
    edges: [{ from: "a", to: "b", toHandle: "in_0", fromLabel: "Load", toLabel: "Analyze" }],
  });

  it("is titled in Curio's words, lists its nodes with what each does, and keeps the rest in its Details", () => {
    render(<AgentChangeCard part={plan} planNodeState={{ appliedRefs: ["a", "b"] }} onUndo={jest.fn()} />);
    expect(screen.getByText("Plan: 2 nodes, 1 connection")).toBeInTheDocument();
    // No chip names its kind, and its counts are not lines of the card.
    expect(screen.queryByText("plan")).toBeNull();
    expect(screen.queryByText("+2 nodes · +1 connection")).toBeNull();
    expect(screen.getByText("load it")).toBeInTheDocument();
    expect(screen.getByText("crunch it")).toBeInTheDocument();
    // Rows, not the raw preview: no generated code surface on plans.
    expect(screen.queryByText(/should not render/)).toBeNull();
    // What each node reads and writes, and the connections, are its Details'.
    expect(screen.queryByText("in: none · out: dataframe")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const details = openDetails();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", details.id);
    expect(within(details).getByText("heat analysis")).toBeInTheDocument();
    expect(within(details).getByText("in: none · out: dataframe")).toBeInTheDocument();
    // The whole pair shows on hover too, handle included (#511).
    expect(within(details).getByText("Load → Analyze [in_0]")).toHaveAttribute("data-tooltip", "Load → Analyze [in_0]");
    expect(screen.getByRole("button", { name: "Undo" })).toHaveAttribute("data-tooltip", "Takes the plan back");
  });

  it("its Details say its checks and agents in a person's words, where a card from before them says what the agents read", () => {
    const { unmount } = render(
      <AgentChangeCard
        part={{ ...plan, checks: ["Checks: no cycles. Node Builder on 2 nodes, Dataset Finder on Load."] }}
        planNodeState={{ appliedRefs: ["a", "b"] }}
      />,
    );
    let details = openDetails();
    expect(within(details).getByText("Checks: no cycles. Node Builder on 2 nodes, Dataset Finder on Load.")).toBeInTheDocument();
    expect(within(details).queryByText("+2 nodes · +1 connection")).toBeNull();
    unmount();
    render(<AgentChangeCard part={plan} planNodeState={{ appliedRefs: ["a", "b"] }} />);
    details = openDetails();
    expect(within(details).getByText("+2 nodes · +1 connection")).toBeInTheDocument();
  });

  it("nothing is applied or edited row by row: no Apply, no goal box, no Connect", () => {
    render(<AgentChangeCard part={plan} planNodeState={{ appliedRefs: ["a", "b"] }} />);
    openDetails();
    expect(screen.queryByRole("button", { name: /^Create node/ })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Connect/ })).toBeNull();
  });

  it("an undone plan offers no row actions and no Undo, only its Details", () => {
    render(
      <AgentChangeCard part={{ ...plan, status: "undone" }} planNodeState={{ appliedRefs: ["a", "b"] }}
        onSolvePlanNode={jest.fn()} onRunPlanNode={jest.fn()} onUndo={jest.fn()} />,
    );
    expect(screen.getByText("Undone")).toBeInTheDocument();
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual(["Details"]);
  });

  it("its Undo says it takes back the goal the plan set", () => {
    render(<AgentChangeCard part={{ ...plan, goalSet: "heat analysis" }} planNodeState={{ appliedRefs: ["a", "b"] }} onUndo={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Undo" })).toHaveAttribute(
      "data-tooltip",
      "Takes the plan back, and the goal it set",
    );
  });

  it("what a plan left undone stays in view", () => {
    render(
      <AgentChangeCard
        part={{ ...plan, leftUndone: "Left undone: 1 connection, since Load was removed" }}
        planNodeState={{ appliedRefs: ["a", "b"] }}
      />,
    );
    expect(screen.getByText("Left undone: 1 connection, since Load was removed")).toBeInTheDocument();
  });

  it("a card stored before it kept what was left undone apart says it from its lines, in view", () => {
    // Such a card held it only among the lines the agents read, before the
    // Topology verdict.
    render(
      <AgentChangeCard
        part={{
          ...plan,
          lines: [
            "+2 nodes · +1 connection",
            "Left undone: 1 connection, since Load was removed",
            "Topology: connected",
          ],
        }}
        planNodeState={{ appliedRefs: ["a", "b"] }}
      />,
    );
    // On the card's face, with Details closed.
    expect(screen.queryByRole("group", { name: "Plan details" })).toBeNull();
    expect(screen.getByText("Left undone: 1 connection, since Load was removed")).toBeInTheDocument();
  });
});

describe("AgentChangeCard: dev/59 a plan that removed nodes (DEC-049.2)", () => {
  const revision = planChange({
    goal: "replace the loader",
    nodes: [{ ref: "a", nodeType: "curio.builtin/python-computation", title: "API Fetch", intent: "fetch" }],
    edgeCount: 1,
    removals: [
      { id: "old-loader", label: "Load CSV", nodeType: "curio.builtin/python-computation", contentChars: 10 },
      { id: "scratch", label: "Scratch", contentChars: 0, pinned: true },
    ],
    cascadeCount: 1,
  });

  it("names every victim with a content flag and the cascade, and the tile that left the dashboard, in view", () => {
    render(<AgentChangeCard part={revision} onUndo={jest.fn()} />);
    const section = screen.getByRole("group", { name: "Nodes and connections this plan removed" });
    expect(section).toHaveTextContent("Removed 2 nodes (and 1 connected edge)");
    expect(section).toHaveTextContent("Load CSV · curio.builtin/python-computation (contained 10 chars of content");
    expect(section).toHaveTextContent("Scratch · dashboard tile (empty)");
    expect(section).toHaveTextContent("1 of them was a dashboard tile, which left the dashboard.");
  });

  it("names removed CONNECTIONS too, with the interaction kind (dev/112)", () => {
    const edgeOnly = planChange({
      goal: "convert the feedback edge",
      nodes: [],
      edgeCount: 1,
      edges: [{ from: "vis", to: "pool", kind: "interaction", fromLabel: "Metric Distribution", toLabel: "Time Data Pool" }],
      removedEdges: [{ id: "e5", fromLabel: "Metric Distribution", toLabel: "Pool Input Merge" }],
    });
    render(<AgentChangeCard part={edgeOnly} />);
    const section = screen.getByRole("group", { name: "Nodes and connections this plan removed" });
    expect(section).toHaveTextContent("Removed 1 connection");
    expect(section).toHaveTextContent("Metric Distribution → Pool Input Merge");
    expect(within(openDetails()).getByText("Metric Distribution ⇄ Time Data Pool · interaction")).toBeInTheDocument();
  });

  // An interaction edge on a view's dot (`fromView`, `toView`) names the view
  // after its node, as a selection tag on a view does ("Node · heights").
  it("names the view an interaction edge links at each end that names one", () => {
    const viewEdges = planChange({
      goal: "link the views",
      nodes: [],
      edgeCount: 2,
      edges: [
        { from: "chart", to: "views", kind: "interaction", toView: "heights", fromLabel: "Heights chart", toLabel: "Two views" },
        { from: "views", to: "pool", kind: "interaction", fromView: "city", fromLabel: "Two views", toLabel: "Pool" },
      ],
    });
    render(<AgentChangeCard part={viewEdges} />);
    const details = openDetails();
    expect(within(details).getByText("Heights chart ⇄ Two views · heights · interaction")).toBeInTheDocument();
    expect(within(details).getByText("Two views · city ⇄ Pool · interaction")).toBeInTheDocument();
  });

  it("additive plans render no Removed section", () => {
    const additive = { ...revision, plan: { ...revision.plan!, removals: undefined, cascadeCount: undefined } };
    render(<AgentChangeCard part={additive} />);
    expect(screen.queryByRole("group", { name: "Nodes and connections this plan removed" })).toBeNull();
  });
});

describe("AgentChangeCard: dev/71 a landed plan's rows: Solve then Run", () => {
  const progressive = planChange({
    goal: "g",
    nodes: [
      { ref: "a", nodeType: "t", title: "Load", intent: "load" },
      { ref: "b", nodeType: "t", title: "Analyze", intent: "crunch" },
    ],
    edgeCount: 1,
    edges: [{ from: "a", to: "b", fromLabel: "Load", toLabel: "Analyze" }],
  });

  const renderRows = (
    state: PlanNodeReviewState,
    handlers: { onSolve?: jest.Mock; onRun?: jest.Mock } = {},
  ) =>
    render(
      <AgentChangeCard
        part={progressive}
        onSolvePlanNode={handlers.onSolve ?? jest.fn()}
        onRunPlanNode={handlers.onRun ?? jest.fn()}
        planNodeState={state}
      />,
    );

  /** A row of the card, by its node's ref. */
  const row = (ref: string) => document.querySelector<HTMLElement>(`[data-curio-plan-row="${ref}"]`)!;

  it("a row that waits upstream says after which node, and no row lists what it needs", () => {
    renderRows({ appliedRefs: ["a", "b"] });
    expect(within(row("b")).getByText("after Load")).toBeInTheDocument();
    expect(screen.queryByText("needs: Load")).toBeNull();
  });

  it("Solve shows only where it can run: the node after an unbuilt one waits, saying after which", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "created", b: "created" } });
    expect(screen.queryByRole("button", { name: "Solve node Analyze" })).toBeNull();
    expect(within(row("b")).getByText("after Load")).toBeInTheDocument();
    // The first node has no upstream: it can be solved now.
    expect(screen.getByRole("button", { name: "Solve node Load" })).toBeEnabled();
  });

  it("Solve comes once upstream is built, and targets the ref; a built row shows the tick of the check it holds", async () => {
    const onSolve = jest.fn().mockResolvedValue(undefined);
    renderRows(
      { appliedRefs: ["a", "b"], nodeStates: { a: "approved", b: "created" }, nodeChecks: { a: "ran" } },
      { onSolve },
    );
    const solveB = screen.getByRole("button", { name: "Solve node Analyze" });
    expect(solveB).toBeEnabled();
    fireEvent.click(solveB);
    // The ref, and the row's listener for how far a download has come.
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith("b", expect.any(Function)));
    // An upstream row that is built shows its tick, not Solve.
    expect(screen.queryByRole("button", { name: "Solve node Load" })).toBeNull();
    const tick = within(row("a")).getByRole("img", { name: "Solved" });
    expect(tick).toHaveAttribute("data-tooltip", "Solved: its code ran in the sandbox");
    expect(within(row("a")).queryByText("Not checked")).toBeNull();
  });

  it("a validated upstream (its code landed) is enough for the next node's Solve, and claims no check it does not hold", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "validated", b: "created" } });
    expect(screen.getByRole("button", { name: "Solve node Analyze" })).toBeEnabled();
    expect(within(row("a")).queryByRole("img")).toBeNull();
    expect(within(row("a")).getByText("Not checked")).toBeInTheDocument();
  });

  // Never claim a check that did not run: a row the ledger holds no check
  // for (its template's code landed with the plan, an agent wrote it in its
  // chat, or its code changed after its check) says so, whatever its kind.
  it.each([
    ["approved", "curio.builtin/python-computation"],
    ["validated", "curio.vega-lite/bars"],
    ["approved", "t"],
  ])("a %s row of %s with no check shows no tick, and says no check ran on its code", (state, nodeType) => {
    render(
      <AgentChangeCard
        part={planChange({ ...progressive.plan!, nodes: progressive.plan!.nodes.map((n) => ({ ...n, nodeType })) })}
        onSolvePlanNode={jest.fn()}
        onRunPlanNode={jest.fn()}
        planNodeState={{ appliedRefs: ["a", "b"], nodeStates: { a: state, b: "created" } }}
      />,
    );
    expect(within(row("a")).queryByRole("img")).toBeNull();
    expect(within(row("a")).getByText("Not checked")).toHaveAttribute(
      "data-tooltip",
      "No check ran on the code it holds now",
    );
    // Built all the same: it offers Run, not Solve.
    expect(screen.getByRole("button", { name: "Run through node Load" })).toBeInTheDocument();
  });

  it.each([
    ["ran", "Solved", "Solved: its code ran in the sandbox"],
    ["valid", "Valid", "Valid: its document was checked against its grammar"],
    ["written", "Written", "Written: it has no code to run, and renders in the browser"],
  ])("a row whose ledger holds the check %s shows its tick, %s", (check, name, says) => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "validated", b: "created" }, nodeChecks: { a: check } });
    expect(within(row("a")).getByRole("img", { name })).toHaveAttribute("data-tooltip", says);
    expect(within(row("a")).queryByText("Not checked")).toBeNull();
  });

  it("a check the row cannot name is no claim", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "approved", b: "created" }, nodeChecks: { a: "guessed" } });
    expect(within(row("a")).queryByRole("img")).toBeNull();
    expect(within(row("a")).getByText("Not checked")).toBeInTheDocument();
  });

  // A batch's Solve builds a row by its run alone: its record says created
  // still, and the row reads built all the same, as the plan line counts it.
  it.each([
    ["verified", "Solved"],
    ["valid", "Valid"],
    ["written", "Written"],
  ])("a row a batch built, its run %s and its record still created, reads as built with the tick of that run", (run, name) => {
    renderRows({ appliedRefs: ["a", "b"], nodeIds: { a: "na", b: "nb" }, nodeStates: { a: "created", b: "created" }, runs: { na: run } });
    expect(within(row("a")).getByRole("img", { name })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run through node Load" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Solve node Load" })).toBeNull();
    // The node it feeds can be solved now.
    expect(screen.getByRole("button", { name: "Solve node Analyze" })).toBeEnabled();
  });

  it("a row a batch built, its run solved and no check kept, reads as built and claims no check", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeIds: { a: "na", b: "nb" }, nodeStates: { a: "created", b: "created" }, runs: { na: "solved" } });
    expect(within(row("a")).queryByRole("img")).toBeNull();
    expect(within(row("a")).getByText("Not checked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run through node Load" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve node Analyze" })).toBeEnabled();
  });

  it("a failed row says so, why on a line of its own, and offers Solve again", () => {
    renderRows({
      appliedRefs: ["a", "b"],
      nodeIds: { a: "na", b: "nb" },
      nodeStates: { a: "failed", b: "created" },
      failures: { na: "Validation failed and nothing was written" },
    });
    expect(within(row("a")).getByText("Failed")).toBeInTheDocument();
    expect(within(row("a")).getByText("Validation failed and nothing was written")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve node Load" })).toBeEnabled();
  });

  it("a row awaiting the person's pick says Needs a source, and offers no Solve: the pick goes on by itself", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "awaiting-source", b: "created" } });
    expect(within(row("a")).getByText("Needs a source")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Solve node Load" })).toBeNull();
    // The node it feeds waits for it, which is named.
    expect(screen.queryByRole("button", { name: "Solve node Analyze" })).toBeNull();
    expect(within(row("b")).getByText("after Load")).toBeInTheDocument();
  });

  it("a row the batch says waits for the person's pick says Needs a source, and offers no Solve", () => {
    renderRows({
      appliedRefs: ["a", "b"],
      nodeIds: { a: "na", b: "nb" },
      nodeStates: { a: "created", b: "created" },
      waitsForPick: ["na"],
    });
    expect(within(row("a")).getByText("Needs a source")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Solve node Load" })).toBeNull();
  });

  it("each row that waits for the person's pick goes to its own sources, its tooltip saying where", () => {
    // Two loaders, each waiting for its pick: one whose card this chat holds,
    // one whose card only its Dataset Finder's chat holds.
    const twoLoaders = planChange({
      goal: "g",
      nodes: [
        { ref: "a", nodeType: "t", title: "Load parks", intent: "load parks" },
        { ref: "b", nodeType: "t", title: "Load trees", intent: "load trees" },
      ],
      edgeCount: 0,
      edges: [],
    });
    const shown: string[] = [];
    const hints: Record<string, string> = {
      na: "Goes to its sources in this chat. Your pick builds it, and the plan goes on.",
      nb: "Opens the chat of its Dataset Finder, which holds its sources. Your pick builds it, and the plan goes on.",
    };
    render(
      <AgentChangeCard
        part={twoLoaders}
        onSolvePlanNode={jest.fn()}
        planNodeState={{
          appliedRefs: ["a", "b"],
          nodeIds: { a: "na", b: "nb" },
          nodeStates: { a: "awaiting-source", b: "awaiting-source" },
        }}
        sourcesOf={(nodeId) => ({ show: () => shown.push(nodeId), hint: hints[nodeId] })}
      />,
    );
    const parks = within(row("a")).getByRole("button", { name: "Needs a source: show the sources of Load parks" });
    const trees = within(row("b")).getByRole("button", { name: "Needs a source: show the sources of Load trees" });
    expect(parks).toHaveTextContent(/^Needs a source$/);
    expect(parks).toHaveAttribute("data-tooltip", hints.na);
    expect(trees).toHaveAttribute("data-tooltip", hints.nb);
    fireEvent.click(trees);
    fireEvent.click(parks);
    expect(shown).toEqual(["nb", "na"]);
    // Still no Solve: the pick goes on by itself.
    expect(screen.queryByRole("button", { name: /^Solve node/ })).toBeNull();
  });

  it("a waiting row with nowhere to go says Needs a source as a word, not a button", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeIds: { a: "na", b: "nb" }, nodeStates: { a: "awaiting-source", b: "created" } });
    expect(within(row("a")).getByText("Needs a source").tagName).toBe("SPAN");
    expect(within(row("a")).queryByRole("button", { name: /Needs a source/ })).toBeNull();
  });

  it.each([
    ["awaiting-download", "Downloading its source"],
    ["awaiting-install", "Needs its dataset installed"],
  ])("a row whose source is %s says so, not that it needs a source, and keeps Solve", (state, words) => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: state, b: "created" } });
    expect(screen.getByText(words)).toBeInTheDocument();
    expect(screen.queryByText("Needs a source")).toBeNull();
    expect(screen.getByRole("button", { name: "Solve node Load" })).toBeEnabled();
  });

  it("Run appears on validated and approved rows and targets the ref", async () => {
    const onRun = jest.fn().mockResolvedValue(undefined);
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "validated", b: "approved" } }, { onRun });
    fireEvent.click(screen.getByRole("button", { name: "Run through node Analyze" }));
    // The ref, and the row's listener for how far a download has come.
    await waitFor(() => expect(onRun).toHaveBeenCalledWith("b", expect.any(Function)));
    expect(screen.getByRole("button", { name: "Run through node Load" })).toBeInTheDocument();
  });

  // A build is a stream over the plan: a row's Solve started while it runs
  // would build the same node beside it.
  it("while a build runs on the plan, no row's Solve is offered, and the node it builds reads Building", () => {
    renderRows({
      appliedRefs: ["a", "b"],
      nodeIds: { a: "na", b: "nb" },
      nodeStates: { a: "created", b: "created" },
      buildRunning: true,
      buildRef: "a",
      buildActivity: "generating content (round 1)",
    });
    expect(screen.queryByRole("button", { name: /^Solve node/ })).toBeNull();
    const building = within(row("a")).getByText("Building…");
    expect(building).toHaveAttribute("data-tooltip", "Generating content (round 1)");
    // The row it waits on is at work: it says nothing until the run ends.
    expect(row("b")).toHaveAttribute("data-curio-row-view", "none");
    expect(within(row("b")).queryByText(/^after /)).toBeNull();
  });

  it.each([
    ["solving", "Solving it"],
    ["generating", "Writing its code"],
    ["verifying", "Running it in the sandbox"],
    ["fixing", "The run failed: fixing it"],
  ])("while a batch Solve runs, no row's Solve is offered; the node it works on reads Building, its step %s on its tooltip", (run, said) => {
    renderRows({
      appliedRefs: ["a", "b"],
      nodeIds: { a: "na", b: "nb" },
      nodeStates: { a: "approved", b: "created" },
      batchRunning: true,
      runs: { na: "solved", nb: run },
    });
    expect(screen.queryByRole("button", { name: /^Solve node/ })).toBeNull();
    expect(within(row("b")).getByText("Building…")).toHaveAttribute("data-tooltip", said);
  });

  it("a written row says its node has no code to run, on its tick", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeIds: { a: "na", b: "nb" }, runs: { na: "written", nb: "pending" } });
    expect(within(row("a")).getByRole("img", { name: "Written" })).toHaveAttribute(
      "data-tooltip",
      "Written: it has no code to run, and renders in the browser",
    );
  });

  it("a notice that is no failure is a quiet line on its row", () => {
    renderRows({
      appliedRefs: ["a", "b"],
      nodeIds: { a: "na", b: "nb" },
      notices: { na: "pending: the batch's time budget (45 min) was spent; Retry continues from here" },
    });
    expect(within(row("a")).getByText(/time budget/)).toBeInTheDocument();
    expect(within(row("b")).queryByText(/time budget/)).toBeNull();
    // It is no failure: the row does not say Failed.
    expect(within(row("a")).queryByText("Failed")).toBeNull();
  });

  it("a row the plan could not place says Not placed", () => {
    renderRows({ appliedRefs: ["a"] });
    expect(within(row("b")).getByText("Not placed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Solve node Analyze" })).toBeNull();
  });

  it("a card whose plan the attachment no longer holds shows its rows without actions", () => {
    render(<AgentChangeCard part={progressive} onSolvePlanNode={jest.fn()} onRunPlanNode={jest.fn()} />);
    expect(screen.getByText("Load")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Solve node|Run through node/ })).toBeNull();
  });
});

describe("AgentChangeCard: dev/72 a row's name opens the chat of its node's own agent", () => {
  const plan = planChange({
    goal: "g",
    nodes: [{ ref: "a", nodeType: "t", title: "Load", intent: "load" }],
    edgeCount: 0,
    edges: [],
  });

  it("the name opens the chat that holds its code's change, named as the live list names its agent", () => {
    const onOpenAgentChat = jest.fn();
    render(
      <AgentChangeCard
        part={plan}
        onOpenAgentChat={onOpenAgentChat}
        delegateExists={(id: string) => id === "att-nb"}
        agentNameOf={(id: string) => (id === "att-nb" ? "Node Builder" : null)}
        planNodeState={{
          appliedRefs: ["a"],
          nodeStates: { a: "validated" },
          nodeChanges: { a: { changeId: "c7", attachmentId: "att-nb" } },
        }}
      />,
    );
    const name = screen.getByRole("button", { name: "Load" });
    expect(name).toHaveAttribute("data-tooltip", "Open its Node Builder");
    fireEvent.click(name);
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-nb");
  });

  it("before its code landed, the name opens the node's own agent, from the live list", () => {
    const onOpenAgentChat = jest.fn();
    render(
      <AgentChangeCard
        part={plan}
        onOpenAgentChat={onOpenAgentChat}
        nodeChatOf={(nodeId: string) => (nodeId === "na" ? { attachmentId: "att-own", name: "My Builder" } : null)}
        planNodeState={{ appliedRefs: ["a"], nodeIds: { a: "na" }, nodeStates: { a: "created" } }}
      />,
    );
    const name = screen.getByRole("button", { name: "Load" });
    expect(name).toHaveAttribute("data-tooltip", "Open its My Builder");
    fireEvent.click(name);
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-own");
  });

  it("a home that is gone, and no agent of its own, renders the name as plain text", () => {
    render(
      <AgentChangeCard
        part={plan}
        onOpenAgentChat={jest.fn()}
        delegateExists={() => false}
        planNodeState={{
          appliedRefs: ["a"],
          nodeStates: { a: "validated" },
          nodeChanges: { a: { changeId: "c7", attachmentId: "gone" } },
        }}
      />,
    );
    expect(screen.queryByRole("button", { name: "Load" })).toBeNull();
    // A name too long for the row is cut; its tooltip says it whole.
    expect(screen.getByText("Load")).toHaveAttribute("data-tooltip", "Load");
  });
});

describe("AgentChangeCard: #662 a landed plan's widgets, copies and scenarios", () => {
  const scenarioPlan = () =>
    planChange({
      goal: "compare two building heights",
      nodes: [
        { ref: "buildings", nodeType: "curio.builtin/python-computation", title: "Buildings", intent: "heights" },
        {
          ref: "shadows", nodeType: "curio.builtin/python-computation", title: "Shadows", intent: "shadow lengths",
          widgets: [{ name: "height_factor", type: "number", default: 1 }], scenario: "Real heights",
        },
        {
          ref: "shadows_tall", nodeType: "curio.builtin/python-computation", title: "Shadows", intent: "shadow lengths",
          widgets: [{ name: "height_factor", type: "number", default: 1, value: 2 }],
          scenario: "Twice as tall", copyOf: "shadows",
        },
      ],
      edgeCount: 3,
      scenarios: [
        { name: "Real heights", color: "#3567c7", nodes: [{ ref: "shadows", label: "Shadows" }] },
        {
          name: "Twice as tall", color: "#e86a3c", description: "every building doubled",
          nodes: [{ ref: "shadows_tall", label: "Shadows" }], duplicateOf: "Real heights",
          values: { shadows_tall: { height_factor: 2 } },
        },
      ],
    });

  it("names each scenario with its nodes, what a duplicate copies and the value it changes, in its Details", () => {
    render(<AgentChangeCard part={scenarioPlan()} />);
    expect(screen.getByText("Plan: 3 nodes, 3 connections, 2 scenarios")).toBeInTheDocument();
    openDetails();
    const group = screen.getByRole("group", { name: "Scenarios this plan saves" });
    expect(group).toHaveTextContent("Real heights");
    const twin = screen.getByLabelText("Scenario Twice as tall");
    expect(twin).toHaveTextContent("a copy of Real heights · Shadows · sets height_factor 2");
    expect(twin).toHaveTextContent("every building doubled");
  });

  it("a copy reads apart from its original's, with its widgets, in its Details", () => {
    render(<AgentChangeCard part={scenarioPlan()} planNodeState={{ appliedRefs: ["buildings", "shadows", "shadows_tall"] }} />);
    const details = openDetails();
    expect(within(details).getByText("in Twice as tall · a copy of Shadows")).toBeInTheDocument();
    expect(within(details).getByText("widgets: height_factor (number, 2)")).toBeInTheDocument();
  });

  it("a saved scenario says so, in its Details", () => {
    render(
      <AgentChangeCard
        part={scenarioPlan()}
        planNodeState={{ appliedRefs: ["shadows", "shadows_tall"], scenarioStates: { "0": "applied" } }}
      />,
    );
    openDetails();
    expect(screen.getByLabelText("Scenario Real heights")).toHaveTextContent("Saved ✓");
    expect(screen.getByLabelText("Scenario Twice as tall")).not.toHaveTextContent("Saved");
  });

  it("a scenario the plan could not save says so on the card, in view", () => {
    render(
      <AgentChangeCard
        part={scenarioPlan()}
        planNodeState={{ appliedRefs: ["shadows", "shadows_tall"], scenarioStates: { "0": "applied", "1": "refused" } }}
      />,
    );
    expect(screen.getByText("Not saved ✗: Twice as tall")).toBeInTheDocument();
  });

  it("a plan without scenarios renders no Scenarios section", () => {
    const part = scenarioPlan();
    delete part.plan!.scenarios;
    render(<AgentChangeCard part={part} />);
    openDetails();
    expect(screen.queryByRole("group", { name: "Scenarios this plan saves" })).toBeNull();
  });
});

describe("AgentChangeCard: a landed Spatial Join, Data Pool and Simple View say their settings in their own words", () => {
  const joinPlan = (join: Record<string, unknown>) =>
    planChange({
      goal: "count sidewalk labels per neighborhood",
      nodes: [
        { ref: "labels", nodeType: "curio.builtin/data-loading", title: "Labels", intent: "label points" },
        { ref: "hoods", nodeType: "curio.builtin/data-loading", title: "Neighborhoods", intent: "polygons" },
        {
          ref: "join", nodeType: "curio.builtin/spatial-join", title: "Labels per neighborhood",
          intent: "count the labels within each neighborhood", ...join,
        },
      ],
      edgeCount: 2,
    } as never);

  it("a join's Details name the operation and the output the plan set by name, as its widgets, and no other node's", () => {
    render(
      <AgentChangeCard
        part={joinPlan({
          widgets: [{ name: "operation", type: "choice", value: "within" }, { name: "output", type: "choice", value: "counts" }],
        })}
        planNodeState={{ appliedRefs: ["labels", "hoods", "join"] }}
      />,
    );
    openDetails();
    expect(screen.getByText('widgets: operation (choice, "within"), output (choice, "counts")')).toBeInTheDocument();
    expect(screen.getAllByText(/^widgets: /)).toHaveLength(1);
  });

  it("a card kept from when the join had a setting of its own shows no line for it", () => {
    render(
      <AgentChangeCard
        part={joinPlan({ spatialJoin: { predicate: "within", output: "counts" } })}
        planNodeState={{ appliedRefs: ["labels", "hoods", "join"] }}
      />,
    );
    expect(screen.getByText("count the labels within each neighborhood")).toBeInTheDocument();
    openDetails();
    expect(screen.queryAllByText(/^operation |output counts|^widgets: /)).toHaveLength(0);
  });

  it("a pool's Details name its modes as its selects do, a view's its image column, and no other node's", () => {
    render(
      <AgentChangeCard
        part={planChange({
          goal: "show the overlays of the photos picked in both charts",
          nodes: [
            { ref: "photos", nodeType: "curio.builtin/data-loading", title: "Photos", intent: "street photos" },
            {
              ref: "pool", nodeType: "curio.builtin/data-pool", title: "Picked photos",
              intent: "the photos picked in both charts", dataPool: { betweenCharts: "MERGE_AND" },
            },
            {
              ref: "either", nodeType: "curio.builtin/data-pool", title: "Either chart",
              intent: "the photos picked in either chart",
              dataPool: { insideChart: "MERGE_OR", betweenCharts: "MERGE_OR" },
            },
            {
              ref: "view", nodeType: "curio.builtin/vis-simple", title: "Overlays",
              intent: "the overlay of each picked photo", simpleVis: { imageColumn: "overlay_url" },
            },
          ],
          edgeCount: 3,
        })}
        planNodeState={{ appliedRefs: ["photos", "pool", "either", "view"] }}
      />,
    );
    openDetails();
    expect(screen.getByText("Conflict between visualizations: Merge (AND)")).toBeInTheDocument();
    expect(
      screen.getByText("Conflict inside visualization: Merge (OR); Conflict between visualizations: Merge (OR)"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/^Conflict /)).toHaveLength(2);
    expect(screen.getByText("Image column: overlay_url")).toBeInTheDocument();
    expect(screen.getAllByText(/^Image column: /)).toHaveLength(1);
  });
});
