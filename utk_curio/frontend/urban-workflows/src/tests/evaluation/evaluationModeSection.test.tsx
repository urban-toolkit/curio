import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

/**
 * dev/123 — Settings → Evaluation mode, in its five states.
 *
 * The state the owner asked for by name is the blocked one: a model configured
 * by `curio.py start --llm-model` must read as configured, because a panel
 * that only looked at the account row would tell an operator who passed the
 * flag that they had configured nothing.
 */

const READY = {
  configured: true,
  reason: "",
  source: "account" as const,
  provider: { apiType: "openai_compatible", baseUrlHost: "sage200.example.edu", model: "gemma4" },
  account: { apiType: "openai_compatible", baseUrlHost: "sage200.example.edu", model: "gemma4", hasApiKey: true },
  deployment: { apiType: "", baseUrlHost: "", model: "", hasApiKey: false },
};

const FIXTURE = {
  fixtureId: "02-vega-lite-spatial-density",
  prompt: "Using the Chicago green roofs inventory and the boundary polygons…",
  context: null,
  tier: "T0",
  needs: [] as string[],
  split: "train",
  reviewStatus: "pending-owner-review" as const,
  reviewedBy: null,
  reviewedAt: null,
  source: "docs/examples/02-vega-lite-spatial-density.json",
  required: { datasets: ["data.cityofchicago.green-roofs"], packages: [] as string[] },
  expectedNodes: 8,
  expectedEdges: 6,
  skip: [] as { when: string; reason: string }[],
};

const RUN = {
  runId: "eval-20260909T171200Z-4f2a",
  fixtureId: FIXTURE.fixtureId,
  provider: READY.provider,
  digests: { fixtureSha256: "a".repeat(64) },
  projectId: "project-1",
  attachmentId: "att-1",
  phase: "done" as const,
  reviewStatus: "pending-owner-review",
  startedAt: "2026-09-09T17:12:00+00:00",
  finishedAt: "2026-09-09T17:14:00+00:00",
  latencyMs: 120000,
  usage: { inputTokens: 5120, outputTokens: 980 },
  score: {
    total: 0.83,
    dimensions: { templates: 1.0, topology: 0.62, dependencies: 1.0, intents: null, execution: 0.75 },
    weights: { templates: 0.25 },
    categories: ["topology"],
    cappedByFabrication: false,
    notes: [] as string[],
  },
  comparison: {},
  failures: [] as { phase: string; detail: string }[],
  applied: [{ tool: "dataflow.plan.write", target: "", status: "applied" }],
  pending: [] as { tool: string; target: string; reason: string }[],
  events: [] as { at: string; kind: string }[],
  cancelRequested: false,
  error: null,
  terminal: true,
};

let mockReadiness: Record<string, unknown> = { ...READY };
let mockFixtures: Record<string, unknown>[] = [{ ...FIXTURE }];
let mockRuns: { runs: Record<string, unknown>[]; inFlight: string | null } = {
  runs: [],
  inFlight: null,
};
const mockStart = jest.fn();
const mockCancel = jest.fn();
const mockReview = jest.fn();

jest.mock("../../api/evaluationApi", () => {
  const actual = jest.requireActual("../../api/evaluationApi");
  return {
    PHASE_LABEL: actual.PHASE_LABEL,
    evaluationApi: {
      readiness: jest.fn(() => Promise.resolve(mockReadiness)),
      fixtures: jest.fn(() => Promise.resolve({ fixtures: mockFixtures })),
      list: jest.fn(() => Promise.resolve(mockRuns)),
      start: (...args: unknown[]) => mockStart(...args),
      status: jest.fn(() => Promise.resolve(mockRuns.runs[0])),
      cancel: (...args: unknown[]) => mockCancel(...args),
      review: (...args: unknown[]) => mockReview(...args),
    },
  };
});

import { EvaluationModeSection } from "../../components/evaluation/EvaluationModeSection";

const openSection = async () => {
  const view = render(<EvaluationModeSection />);
  const details = view.container.querySelector("details") as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle", { bubbles: true }));
  return view;
};

beforeEach(() => {
  jest.clearAllMocks();
  mockReadiness = { ...READY };
  mockFixtures = [{ ...FIXTURE }];
  mockRuns = { runs: [], inFlight: null };
});

describe("the closed section", () => {
  it("adds nothing to the accessibility tree until it is opened", () => {
    render(<EvaluationModeSection />);
    expect(screen.getByText("Evaluation mode")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});

describe("the blocked state", () => {
  it("says there is nothing to evaluate and names the fix", async () => {
    mockReadiness = {
      ...READY,
      configured: false,
      source: "none",
      reason: "No LLM provider is configured for this account.",
      provider: { apiType: "", baseUrlHost: "", model: "" },
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/No model is configured/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/--llm-model/)).toBeInTheDocument();
    expect(screen.queryByText("Run evaluation")).toBeNull();
  });

  it("treats a model from the start command as configured, and says so", async () => {
    mockReadiness = {
      ...READY,
      source: "deployment",
      account: { apiType: "", baseUrlHost: "", model: "", hasApiKey: false },
      deployment: {
        apiType: "openai_compatible",
        baseUrlHost: "sage200.example.edu",
        model: "gemma4",
        hasApiKey: true,
      },
    };
    await openSection();
    await waitFor(() =>
      expect(
        screen.getByText(/Configured by this deployment's start command/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("gemma4")).toBeInTheDocument();
    expect(await screen.findByText("Run evaluation")).toBeEnabled();
  });
});

describe("the ready state", () => {
  it("names the model, the example and the prompt that will be sent", async () => {
    await openSection();
    await waitFor(() => expect(screen.getByText("gemma4")).toBeInTheDocument());
    expect(screen.getByText(/sage200.example.edu/)).toBeInTheDocument();
    expect(screen.getByLabelText("Example to rebuild")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "The prompt that will be sent" }),
    ).toHaveTextContent("Chicago green roofs");
    expect(screen.getByText(/8 nodes, 6 edges in the reference/)).toBeInTheDocument();
  });

  it("starts a run for the selected example", async () => {
    mockStart.mockResolvedValue({ ...RUN, phase: "project", terminal: false });
    await openSection();
    fireEvent.click(await screen.findByText("Run evaluation"));
    await waitFor(() => expect(mockStart).toHaveBeenCalledWith(FIXTURE.fixtureId));
  });

  it("lets a drafted prompt be approved from the panel", async () => {
    mockReview.mockResolvedValue({
      fixtureId: FIXTURE.fixtureId,
      status: "approved",
      reviewedBy: "karla",
      reviewedAt: "2026-09-09T17:00:00+00:00",
    });
    await openSection();
    const approve = await screen.findByText("Approve this prompt");
    expect(screen.getByText(/drafted by a model and is awaiting review/)).toBeInTheDocument();
    fireEvent.click(approve);
    await waitFor(() =>
      expect(mockReview).toHaveBeenCalledWith(FIXTURE.fixtureId, "approved"),
    );
    await waitFor(() =>
      expect(screen.getByText("Approved by karla.")).toBeInTheDocument(),
    );
  });

  it("offers to withdraw an approval that is already recorded", async () => {
    mockFixtures = [{ ...FIXTURE, reviewStatus: "approved", reviewedBy: "karla" }];
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/Prompt approved by karla/)).toBeInTheDocument(),
    );
    expect(screen.getByText("Withdraw approval")).toBeInTheDocument();
    expect(screen.queryByText("Approve this prompt")).toBeNull();
  });
});

describe("a run in progress", () => {
  it("says which phase it is in, and offers Cancel", async () => {
    mockRuns = {
      runs: [{ ...RUN, phase: "prompting", terminal: false, score: null, latencyMs: 42000 }],
      inFlight: RUN.runId,
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/waiting for the model/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/42s/)).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
    expect(await screen.findByText("Run evaluation")).toBeDisabled();
  });

  it("cancels through the service", async () => {
    mockRuns = {
      runs: [{ ...RUN, phase: "solving", terminal: false, score: null }],
      inFlight: RUN.runId,
    };
    mockCancel.mockResolvedValue({ ...RUN, cancelRequested: true, terminal: false, score: null });
    await openSection();
    fireEvent.click(await screen.findByText("Cancel"));
    await waitFor(() => expect(mockCancel).toHaveBeenCalledWith(RUN.runId));
    await waitFor(() => expect(screen.getByText("Stopping…")).toBeInTheDocument());
  });
});

describe("a finished run", () => {
  it("shows the overall score, every category, and the generated project", async () => {
    mockRuns = { runs: [{ ...RUN }], inFlight: null };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText("Overall accuracy 83%")).toBeInTheDocument(),
    );
    expect(screen.getByRole("row", { name: /topology/ })).toHaveTextContent("62%");
    expect(screen.getByRole("row", { name: /intents/ })).toHaveTextContent(
      "not measured",
    );
    const link = screen.getByText("Open the generated dataflow");
    expect(link).toHaveAttribute("href", "/dataflow/project-1");
    expect(screen.getByText(/5120 in \/ 980 out tokens/)).toBeInTheDocument();
  });

  it("reports where a failed run stopped", async () => {
    mockRuns = {
      runs: [{
        ...RUN,
        phase: "failed",
        score: null,
        error: "the endpoint went away",
        failures: [{ phase: "prompting", detail: "the endpoint went away" }],
      }],
      inFlight: null,
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/Stopped in prompting/)).toBeInTheDocument(),
    );
  });

  it("names what the policy left pending", async () => {
    mockRuns = {
      runs: [{
        ...RUN,
        pending: [{
          tool: "node.create",
          target: "",
          reason: "node.create is a decision a person makes, not an unattended run",
        }],
      }],
      inFlight: null,
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/Left pending: node.create/)).toBeInTheDocument(),
    );
  });
});
