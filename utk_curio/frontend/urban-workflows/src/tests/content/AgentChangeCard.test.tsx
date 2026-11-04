import React from "react";
import { subscribeApiSettingsRequests } from "../../components/apiSettings/apiSettingsRequest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AgentChangeCard } from "../../components/agents/content/AgentChangeCard";
import type { PlanNodeReviewState } from "../../components/agents/content/AgentReviewCard";
import type { AgentChangePart } from "../../services/agents";

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
  it("says what the change did and offers Undo, never Apply or Dismiss", () => {
    render(<AgentChangeCard part={change()} onUndo={jest.fn()} />);
    expect(screen.getByRole("group", { name: "Change: Replaced the content of the Python node · n1" })).toBeInTheDocument();
    expect(screen.getByText("Python · n1")).toBeInTheDocument();
    expect(screen.getByText("print(2)")).toBeInTheDocument();
    expect(screen.getByText("code")).toBeInTheDocument();
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
    ["content", "code"],
    ["settings", "settings"],
    ["node", "new node"],
    ["plan", "plan"],
  ])("a %s change's header names its kind as %s", (kind, label) => {
    render(<AgentChangeCard part={change({ kind, preview: "", plan: undefined })} />);
    expect(screen.getByText(label)).toBeInTheDocument();
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
    render(<AgentChangeCard part={settings(lines)} onUndo={jest.fn()} />);
    expect(screen.getByText("Changed the settings of the Data Pool node · Picked photos")).toBeInTheDocument();
    for (const line of lines) expect(screen.getAllByText(line)).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
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

describe("AgentChangeCard: a new node (dev/118, dev/119: what Solve does with it)", () => {
  const source = { kind: "external", label: "x", refs: [{ kind: "external", value: "https://a.org", verification: { status: "verified" } }] };
  const created = (overrides: Partial<AgentChangePart>) =>
    change({
      tool: "node.create",
      kind: "node",
      summary: "Created a new Data Loading node",
      lines: ["Load · curio.builtin/data-loading", "node n9"],
      ...overrides,
    });

  it("the roster's executable flag decides what the card says Solve does", () => {
    const { unmount } = render(
      <AgentChangeCard part={created({ nodeType: "some.pkg/custom-python@1", executable: true, source })} />,
    );
    expect(screen.getByText("Solve runs it in the sandbox and fixes errors before its code is trusted.")).toBeInTheDocument();
    unmount();
    const second = render(
      <AgentChangeCard part={created({ nodeType: "curio.builtin/spatial-join@1", executable: false, source })} />,
    );
    expect(
      screen.getByText(/has no code to run: Solve writes it, the browser or its own service renders it; it is never called verified/),
    ).toBeInTheDocument();
    second.unmount();
    // A card from before the flag, on a kind the registry has never seen:
    // the card says nothing rather than guessing.
    render(<AgentChangeCard part={created({ nodeType: "ghost.pkg/unknown@1", source })} />);
    expect(screen.queryByText(/Solve runs it in the sandbox/)).toBeNull();
    expect(screen.queryByText(/has no code to run/)).toBeNull();
  });

  it("a node that opens no source says nothing of Solve", () => {
    render(<AgentChangeCard part={created({ nodeType: "x", executable: true })} />);
    expect(screen.queryByText(/Solve runs it/)).toBeNull();
  });
});

describe("AgentChangeCard: dev/114 (DEC-072) the Source block", () => {
  const withSource = (source: AgentChangePart["source"]) =>
    change({ tool: "node.create", kind: "node", summary: "Created a new Data Loading node", source });

  it("names a Data Catalog source by title, format and id", () => {
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
    const block = screen.getByRole("group", { name: "Data source" });
    expect(block).toHaveTextContent("Source · Data Catalog");
    expect(block).toHaveTextContent("Census ACS 5-year (parquet) · imported.acs@1");
  });

  it("shows an external URL with the runtime's verification chip", () => {
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
    const block = screen.getByRole("group", { name: "Data source" });
    expect(block).toHaveTextContent("Source · External source");
    expect(block).toHaveTextContent("https://api.noaa.gov/climate");
    expect(screen.getByText("Verified ✓")).toBeInTheDocument();
  });

  it("says a credential-gated endpoint is gated and a user path is unchecked", () => {
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
    const block = screen.getByRole("group", { name: "Data source" });
    expect(block).toHaveTextContent("Source · Several sources");
    expect(block).toHaveTextContent("https://api.x.gov/v1 · credential-gated");
    expect(block).toHaveTextContent("data/tracts.geojson (not checked by Curio)");
  });

  it("labels synthetic data as generated in the node", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "synthetic", label: "Synthetic · generated in the node, no external source",
                           refs: [{ kind: "synthetic" }] })}
      />,
    );
    expect(screen.getByRole("group", { name: "Data source" })).toHaveTextContent("Source · Synthetic data");
    expect(screen.getByText(/generated in the node, no external source/)).toBeInTheDocument();
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
    const block = screen.getByRole("group", { name: "Data source" });
    expect(block).toHaveTextContent("Source · Several sources");
    expect(block).toHaveTextContent("Tracts (csv) · tracts");
    expect(block).toHaveTextContent("np.random.randint (made up in the node, as the user asked)");
    expect(block).not.toHaveTextContent("no external source");
  });

  it("names the values the user typed that the code added to the node's own", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "user-values", label: "User-provided values · 'J', 'K', 60, 33",
                           refs: [{ kind: "user-values", value: "'J', 'K', 60, 33" }] })}
      />,
    );
    const block = screen.getByRole("group", { name: "Data source" });
    expect(block).toHaveTextContent("Source · User-provided values");
    expect(block).toHaveTextContent("'J', 'K', 60, 33 (typed in the chat)");
  });

  it("renders no Source block when the change carries none", () => {
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

  it("a secret ref reads as a connection key by name: never a value (dev/116)", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "mixed", label: "External · … · Connection key · census", refs: [
          { kind: "external", value: "https://api.census.gov/data", verification: { status: "verified", httpStatus: 200 } },
          { kind: "secret", value: 'curio_secret("census")', name: "census", host: "api.census.gov", delivery: "query:key" },
        ] })}
      />,
    );
    const block = screen.getByRole("group", { name: "Data source" });
    expect(block).toHaveTextContent("Connection key · census · api.census.gov");
    expect(block).not.toHaveTextContent("query:key");
  });

  it("a credential-gated external ref shows the saved-key hint (dev/116)", () => {
    render(
      <AgentChangeCard
        part={withSource({ kind: "external", label: "x", refs: [
          { kind: "external", value: "https://api.census.gov/data", requirement: "credential-gated",
            hint: "a connection key 'census' is saved for this host: use api_key = curio_secret(\"census\")",
            verification: { status: "unreachable", httpStatus: 401 } },
        ] })}
      />,
    );
    expect(screen.getByRole("group", { name: "Data source" })).toHaveTextContent(/credential-gated \(a connection key 'census' is saved/);
  });
});

describe("AgentChangeCard: dev/67-7 the validation block of code that landed", () => {
  const validated = (verdict: string, evidence = {}) =>
    change({ validation: { verdict, rounds: verdict === "pass" ? 1 : 3, evidence } });

  it("renders PASS with the output type", () => {
    render(<AgentChangeCard part={validated("pass", { outputDataType: "dataframe" })} onUndo={jest.fn()} />);
    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.getByText(/output: dataframe/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("renders FAIL with the traceback", () => {
    render(<AgentChangeCard part={validated("fail", { kind: "execution-error", stderrTail: "Traceback: KeyError" })} />);
    expect(screen.getByText("FAIL")).toBeInTheDocument();
    expect(screen.getByText("Traceback: KeyError")).toBeInTheDocument();
  });

  it("names an upstream blocker instead of blaming the node", () => {
    render(<AgentChangeCard part={validated("fail", { kind: "upstream-blocker", blockerLabel: "Load CSV" })} />);
    expect(screen.getByText(/Upstream node Load CSV failed/)).toBeInTheDocument();
  });

  it("changes without validation render no block", () => {
    render(<AgentChangeCard part={change()} />);
    expect(screen.queryByText("PASS")).toBeNull();
  });
});

describe("AgentChangeCard: dev/115 the verification attempt trail", () => {
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
    const summary = screen.getByText("Verification · 2 attempts");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    const list = screen.getByRole("list", { name: "Verification attempts" });
    expect(list).toHaveTextContent("Round 1 · fail · execution-error · the node's current code");
    expect(list).toHaveTextContent("Round 2 · pass ✓");
    expect(list).toHaveTextContent("output: dataframe · 4.1 s");
    expect(list).toHaveTextContent("400 Client Error");
    // The code on the card is the code that ran, and it landed: Undo puts back the code before.
    expect(screen.getByRole("button", { name: "Undo" })).not.toBeDisabled();
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
    expect(screen.queryByText(/Verification · /)).toBeNull();
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

describe("AgentChangeCard: dev/52 a landed plan", () => {
  const plan = planChange({
    goal: "heat analysis",
    nodes: [
      { ref: "a", nodeType: "curio.builtin/data-loading", title: "Load", intent: "load it", expects: "in: none · out: dataframe" },
      { ref: "b", nodeType: "curio.builtin/computation-analysis", title: "Analyze", intent: "crunch it" },
    ],
    edgeCount: 1,
    edges: [{ from: "a", to: "b", toHandle: "in_0", fromLabel: "Load", toLabel: "Analyze" }],
  });

  it("states its goal and what it added, lists its nodes and names its connections", () => {
    render(<AgentChangeCard part={plan} planNodeState={{ appliedRefs: ["a", "b"] }} onUndo={jest.fn()} />);
    expect(screen.getByText("heat analysis")).toBeInTheDocument();
    expect(screen.getByText("+2 nodes · +1 connection")).toBeInTheDocument();
    // Rows, not the raw preview: no generated code surface on plans.
    expect(screen.queryByText(/should not render/)).toBeNull();
    expect(screen.getByText("in: none · out: dataframe")).toBeInTheDocument();
    expect(screen.getByText("crunch it")).toBeInTheDocument();
    // The whole pair shows on hover too, handle included (#511).
    expect(screen.getByText("Load → Analyze [in_0]")).toHaveAttribute("data-tooltip", "Load → Analyze [in_0]");
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("nothing is applied or edited row by row: no Apply, no goal box, no Connect", () => {
    render(<AgentChangeCard part={plan} planNodeState={{ appliedRefs: ["a", "b"] }} />);
    expect(screen.queryByRole("button", { name: /^Create node/ })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Connect/ })).toBeNull();
  });

  it("an undone plan offers no row actions and no Undo", () => {
    render(
      <AgentChangeCard part={{ ...plan, status: "undone" }} planNodeState={{ appliedRefs: ["a", "b"] }}
        onSolvePlanNode={jest.fn()} onRunPlanNode={jest.fn()} onUndo={jest.fn()} />,
    );
    expect(screen.getByText("Undone")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("AgentChangeCard: dev/59 a plan that removed nodes (DEC-049.2)", () => {
  const revision = planChange({
    goal: "replace the loader",
    nodes: [{ ref: "a", nodeType: "curio.builtin/computation-analysis", title: "API Fetch", intent: "fetch" }],
    edgeCount: 1,
    removals: [
      { id: "old-loader", label: "Load CSV", nodeType: "curio.builtin/computation-analysis", contentChars: 10 },
      { id: "scratch", label: "Scratch", contentChars: 0, pinned: true },
    ],
    cascadeCount: 1,
  });

  it("names every victim with a content flag and the cascade, and the tile that left the dashboard", () => {
    render(<AgentChangeCard part={revision} onUndo={jest.fn()} />);
    const section = screen.getByRole("group", { name: "Nodes and connections this plan removed" });
    expect(section).toHaveTextContent("Removed 2 nodes (and 1 connected edge)");
    expect(section).toHaveTextContent("Load CSV · curio.builtin/computation-analysis (contained 10 chars of content");
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
    expect(screen.getByText("Metric Distribution ⇄ Time Data Pool · interaction")).toBeInTheDocument();
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

  it("rows name their dependencies", () => {
    renderRows({ appliedRefs: ["a", "b"] });
    expect(screen.getByText("needs: Load")).toBeInTheDocument();
  });

  it("Solve gates on solved dependencies, with the blocker named", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "created", b: "created" } });
    const solveB = screen.getByRole("button", { name: "Solve node Analyze" });
    expect(solveB).toBeDisabled();
    expect(solveB).toHaveAttribute("data-tooltip", "needs 'Load' solved first");
    // The first node has no upstream: it can be solved now.
    expect(screen.getByRole("button", { name: "Solve node Load" })).toBeEnabled();
  });

  it("Solve enables once upstream is approved, and targets the ref", async () => {
    const onSolve = jest.fn().mockResolvedValue(undefined);
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "approved", b: "created" } }, { onSolve });
    const solveB = screen.getByRole("button", { name: "Solve node Analyze" });
    expect(solveB).toBeEnabled();
    fireEvent.click(solveB);
    await waitFor(() => expect(onSolve).toHaveBeenCalledWith("b"));
    // Upstream approved rows show Run, not Solve.
    expect(screen.queryByRole("button", { name: "Solve node Load" })).toBeNull();
    expect(screen.getByText("Solved ✓")).toBeInTheDocument();
  });

  it("a validated upstream (its code landed) is enough for the next node's Solve", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "validated", b: "created" } });
    expect(screen.getByRole("button", { name: "Solve node Analyze" })).toBeEnabled();
    expect(screen.getByText("Validated ✓")).toBeInTheDocument();
  });

  it("a failed row offers Solve again", () => {
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "failed", b: "created" } });
    expect(screen.getByText("Failed: Solve retries")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Solve node Load" })).toBeEnabled();
  });

  it("Run appears on validated and approved rows and targets the ref", async () => {
    const onRun = jest.fn().mockResolvedValue(undefined);
    renderRows({ appliedRefs: ["a", "b"], nodeStates: { a: "validated", b: "approved" } }, { onRun });
    fireEvent.click(screen.getByRole("button", { name: "Run through node Analyze" }));
    await waitFor(() => expect(onRun).toHaveBeenCalledWith("b"));
    expect(screen.getByRole("button", { name: "Run through node Load" })).toBeInTheDocument();
  });

  it("a card whose plan the attachment no longer holds shows its rows without actions", () => {
    render(<AgentChangeCard part={progressive} onSolvePlanNode={jest.fn()} onRunPlanNode={jest.fn()} />);
    expect(screen.getByText("Load")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Solve node|Run through node/ })).toBeNull();
  });
});

describe("AgentChangeCard: dev/72 a row's chip links to the chat that holds its code's change", () => {
  const plan = planChange({
    goal: "g",
    nodes: [{ ref: "a", nodeType: "t", title: "Load", intent: "load" }],
    edgeCount: 0,
    edges: [],
  });

  it("the chip opens the node agent's chat, named as the live list names it", () => {
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
    expect(screen.getByText("Validated ✓")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Node Builder's chat" }));
    expect(onOpenAgentChat).toHaveBeenCalledWith("att-nb");
  });

  it("a home that is gone renders no link", () => {
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
    expect(screen.queryByRole("button", { name: /chat/i })).toBeNull();
  });
});

describe("AgentChangeCard: #662 a landed plan's widgets, copies and scenarios", () => {
  const scenarioPlan = () =>
    planChange({
      goal: "compare two building heights",
      nodes: [
        { ref: "buildings", nodeType: "curio.builtin/computation-analysis", title: "Buildings", intent: "heights" },
        {
          ref: "shadows", nodeType: "curio.builtin/computation-analysis", title: "Shadows", intent: "shadow lengths",
          widgets: [{ name: "height_factor", type: "number", default: 1 }], scenario: "Real heights",
        },
        {
          ref: "shadows_tall", nodeType: "curio.builtin/computation-analysis", title: "Shadows", intent: "shadow lengths",
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

  it("names each scenario with its nodes, what a duplicate copies and the value it changes", () => {
    render(<AgentChangeCard part={scenarioPlan()} />);
    const group = screen.getByRole("group", { name: "Scenarios this plan saves" });
    expect(group).toHaveTextContent("Real heights");
    const twin = screen.getByLabelText("Scenario Twice as tall");
    expect(twin).toHaveTextContent("a copy of Real heights · Shadows · sets height_factor 2");
    expect(twin).toHaveTextContent("every building doubled");
  });

  it("a copy's row reads apart from its original's, with its widgets", () => {
    render(<AgentChangeCard part={scenarioPlan()} planNodeState={{ appliedRefs: ["buildings", "shadows", "shadows_tall"] }} />);
    expect(screen.getByText("in Twice as tall · a copy of Shadows")).toBeInTheDocument();
    expect(screen.getByText("widgets: height_factor (number, 2)")).toBeInTheDocument();
  });

  it("a saved scenario says so", () => {
    render(
      <AgentChangeCard
        part={scenarioPlan()}
        planNodeState={{ appliedRefs: ["shadows", "shadows_tall"], scenarioStates: { "0": "applied" } }}
      />,
    );
    expect(screen.getByLabelText("Scenario Real heights")).toHaveTextContent("Saved ✓");
    expect(screen.getByLabelText("Scenario Twice as tall")).not.toHaveTextContent("Saved");
  });

  it("a plan without scenarios renders no Scenarios section", () => {
    const part = scenarioPlan();
    delete part.plan!.scenarios;
    render(<AgentChangeCard part={part} />);
    expect(screen.queryByRole("group", { name: "Scenarios this plan saves" })).toBeNull();
  });
});

describe("AgentChangeCard: a landed Spatial Join, Data Pool and Simple View say their settings in their own words", () => {
  it("a join's row names the operation and the output the plan set, and no other row names one", () => {
    render(
      <AgentChangeCard
        part={planChange({
          goal: "count sidewalk labels per neighborhood",
          nodes: [
            { ref: "labels", nodeType: "curio.builtin/data-loading", title: "Labels", intent: "label points" },
            { ref: "hoods", nodeType: "curio.builtin/data-loading", title: "Neighborhoods", intent: "polygons" },
            {
              ref: "join", nodeType: "curio.builtin/spatial-join", title: "Labels per neighborhood",
              intent: "count the labels within each neighborhood",
              spatialJoin: { predicate: "within", output: "counts" },
            },
          ],
          edgeCount: 2,
        })}
        planNodeState={{ appliedRefs: ["labels", "hoods", "join"] }}
      />,
    );
    expect(screen.getByText("operation within, output counts")).toBeInTheDocument();
    expect(screen.getAllByText(/^operation /)).toHaveLength(1);
  });

  it("a pool's row names its modes as its selects do, a view's its image column, and no other row names one", () => {
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
    expect(screen.getByText("Conflict between visualizations: Merge (AND)")).toBeInTheDocument();
    expect(
      screen.getByText("Conflict inside visualization: Merge (OR); Conflict between visualizations: Merge (OR)"),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/^Conflict /)).toHaveLength(2);
    expect(screen.getByText("Image column: overlay_url")).toBeInTheDocument();
    expect(screen.getAllByText(/^Image column: /)).toHaveLength(1);
  });
});
