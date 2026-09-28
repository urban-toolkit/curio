import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

/**
 * dev/122 — Settings → Model training, in its three states and no fourth.
 *
 * The state that matters most is Unavailable: an endpoint with no tuning
 * surface must produce one sentence in its own words and NO controls. A
 * disabled Start button would be the cosmetic panel dev/121 refused to ship.
 */

const READY_CAPABILITY = {
  supported: true,
  reason: "This endpoint answers its fine-tuning routes.",
  baseModels: ["gpt-tunable"],
  surface: "openai_compatible_v1",
  probedAt: "2026-09-09T12:00:00+00:00",
  source: "live",
  seenAt: null,
  provider: { apiType: "openai_compatible", baseUrlHost: "api.example.com" },
};

const READY_PREVIEW = {
  dataset: {
    split: "train",
    rows: 9,
    bytes: 41234,
    sha256: "a".repeat(64),
    fixtureIds: ["01-vega-lite-chained-transforms"],
    excluded: [{ fixtureId: "07-autark-gpu-shader", reason: "interaction-edge" }],
    instructionSha256: "b".repeat(64),
    rosterDigest: "c".repeat(64),
  },
  consent: {
    destinationHost: "api.example.com",
    rows: 9,
    bytes: 41234,
    rowsDigest: "a".repeat(64),
    fixtureIds: ["01-vega-lite-chained-transforms"],
    licences: [
      { fixtureId: "01-vega-lite-chained-transforms", licence: "MIT (this repository)" },
    ],
    excluded: [{ fixtureId: "07-autark-gpu-shader", reason: "interaction-edge" }],
    note:
      "Each row carries the prompt, the expected graph shape and the plan text plus dataset and package IDENTIFIERS.",
    sentence: "Sends 9 rows (40 KB) to api.example.com.",
  },
  provider: { apiType: "openai_compatible", baseUrlHost: "api.example.com" },
};

let mockCapability: Record<string, unknown> = { ...READY_CAPABILITY };
let mockPreview: Record<string, unknown> | Error = { ...READY_PREVIEW };
let mockJobs: { jobs: Record<string, unknown>[]; inFlight: string | null } = {
  jobs: [],
  inFlight: null,
};

const mockStart = jest.fn();
const mockActivate = jest.fn();
const mockRollback = jest.fn();
const mockCancel = jest.fn();

jest.mock("../../api/trainingApi", () => ({
  trainingApi: {
    capability: jest.fn(() => Promise.resolve(mockCapability)),
    preview: jest.fn(() =>
      mockPreview instanceof Error
        ? Promise.reject(mockPreview)
        : Promise.resolve(mockPreview),
    ),
    list: jest.fn(() => Promise.resolve(mockJobs)),
    start: (...args: unknown[]) => mockStart(...args),
    status: jest.fn(() => Promise.resolve(mockJobs.jobs[0])),
    cancel: (...args: unknown[]) => mockCancel(...args),
    activate: (...args: unknown[]) => mockActivate(...args),
    rollback: (...args: unknown[]) => mockRollback(...args),
  },
}));

import { ModelTrainingSection } from "../../components/training/ModelTrainingSection";

const openSection = async () => {
  const view = render(<ModelTrainingSection />);
  // jsdom does not fire `toggle` from a summary click, so drive the disclosure
  // the way a browser would.
  const details = view.container.querySelector("details") as HTMLDetailsElement;
  details.open = true;
  fireEvent(details, new Event("toggle", { bubbles: true }));
  return view;
};

const succeededJob = (over: Record<string, unknown> = {}) => ({
  jobId: "train-20260909T120000Z-abcdef01",
  provider: { apiType: "openai_compatible", baseUrlHost: "api.example.com" },
  dataset: READY_PREVIEW.dataset,
  consent: {},
  providerJobId: "ftjob-1",
  status: "succeeded",
  rawStatus: "succeeded",
  statusReadAt: "2026-09-09T12:30:00+00:00",
  trainedModel: "ft:gpt-tunable:curio-plans:abc",
  usage: { trainedTokens: 4321 },
  cost: null,
  evaluation: null,
  activation: { activatedAt: null, previousModel: null, rolledBackAt: null },
  events: [],
  createdAt: "2026-09-09T12:00:00+00:00",
  error: null,
  submitted: true,
  consentedOnly: false,
  ...over,
});

beforeEach(() => {
  jest.clearAllMocks();
  mockCapability = { ...READY_CAPABILITY };
  mockPreview = { ...READY_PREVIEW };
  mockJobs = { jobs: [], inFlight: null };
});

describe("the closed section", () => {
  it("adds nothing to the accessibility tree until it is opened", () => {
    render(<ModelTrainingSection />);
    expect(screen.getByText("Model training")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

describe("the Unavailable state", () => {
  it("says why in the endpoint's own words and offers no controls", async () => {
    mockCapability = {
      ...READY_CAPABILITY,
      supported: false,
      reason:
        "This endpoint serves chat but not fine-tuning (404 from its fine-tuning route).",
      baseModels: [],
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/serves chat but not fine-tuning/)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Start training")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("labels a replayed answer with the date it was true", async () => {
    mockCapability = {
      ...READY_CAPABILITY,
      supported: false,
      reason: "Could not ask this endpoint about fine-tuning: offline.",
      source: "remembered",
      seenAt: "2026-09-01T10:00:00+00:00",
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/Last asked 2026-09-01/)).toBeInTheDocument(),
    );
    expect(screen.getByText("Ask again")).toBeInTheDocument();
  });
});

describe("the Ready state", () => {
  it("names what would be sent, where, and what is excluded", async () => {
    await openSection();
    await waitFor(() => expect(screen.getByText(/Sends 9 rows/)).toBeInTheDocument());
    expect(screen.getByText(/IDENTIFIERS/)).toBeInTheDocument();
    expect(
      screen.getByText(/07-autark-gpu-shader — not included: interaction-edge/),
    ).toBeInTheDocument();
  });

  it("keeps Start disabled until the consent box is ticked", async () => {
    await openSection();
    const start = await screen.findByText("Start training");
    expect(start).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(start).not.toBeDisabled();
  });

  it("sends the digest it was shown, and the confirmation", async () => {
    mockStart.mockResolvedValue(succeededJob({ status: "queued" }));
    await openSection();
    const start = await screen.findByText("Start training");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(start);
    await waitFor(() =>
      expect(mockStart).toHaveBeenCalledWith({
        baseModel: "gpt-tunable",
        rowsDigest: "a".repeat(64),
        confirmed: true,
      }),
    );
  });

  it("asks for a base model when the endpoint advertised none", async () => {
    mockCapability = { ...READY_CAPABILITY, baseModels: [] };
    await openSection();
    await waitFor(() =>
      expect(
        screen.getByText(/did not say which models it can tune, so type one/),
      ).toBeInTheDocument(),
    );
  });

  it("says so when nothing is approved yet, instead of offering an empty upload", async () => {
    mockPreview = new Error(
      "nothing to export: every fixture in this split is still awaiting review",
    );
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/awaiting review/)).toBeInTheDocument(),
    );
    expect(screen.queryByText("Start training")).toBeNull();
  });
});

describe("a job that exists", () => {
  it("shows the status with when it was read, and no spinner theatre", async () => {
    mockJobs = {
      jobs: [succeededJob({ status: "queued", rawStatus: "validating_files" })],
      inFlight: "train-20260909T120000Z-abcdef01",
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/queued \(validating_files\)/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/read 2026-09-09T12:30:00/)).toBeInTheDocument();
    expect(screen.getByText("Refresh")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("offers no Activate until the gate is satisfied, and says what is missing", async () => {
    mockJobs = {
      jobs: [
        succeededJob({
          gate: {
            satisfied: false,
            reason:
              "no evaluation exists for this model. Run the held-out evaluation first",
          },
        }),
      ],
      inFlight: null,
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/Not evaluated yet/)).toBeInTheDocument(),
    );
    expect(screen.getByText("Use this model")).toBeDisabled();
    expect(
      screen.getByText(/Available once this model has been evaluated/),
    ).toBeInTheDocument();
  });

  it("enables Activate once an evaluation exists, and reports its numbers", async () => {
    mockJobs = {
      jobs: [
        succeededJob({
          gate: {
            satisfied: true,
            meanScore: 0.94,
            split: "heldout",
            note:
              "Curio does not decide whether they are good enough — that is your call.",
          },
        }),
      ],
      inFlight: null,
    };
    mockActivate.mockResolvedValue(
      succeededJob({
        activation: {
          activatedAt: "2026-09-09T13:00:00+00:00",
          previousModel: "gpt-4o-mini",
          rolledBackAt: null,
        },
      }),
    );
    await openSection();
    const activate = await screen.findByText("Use this model");
    expect(activate).not.toBeDisabled();
    expect(screen.getByText(/mean score 0\.94/)).toBeInTheDocument();
    expect(screen.getByText(/that is your call/)).toBeInTheDocument();
    fireEvent.click(activate);
    await waitFor(() =>
      expect(mockActivate).toHaveBeenCalledWith("train-20260909T120000Z-abcdef01"),
    );
    await waitFor(() =>
      expect(screen.getByText("Go back to the previous model")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Restores gpt-4o-mini/)).toBeInTheDocument();
  });

  it("reports trained tokens as the provider gave them and invents no cost", async () => {
    mockJobs = { jobs: [succeededJob()], inFlight: null };
    await openSection();
    await waitFor(() =>
      expect(
        screen.getByText(/4321 trained tokens, as the provider reported them/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/no price table, so no cost is shown/)).toBeInTheDocument();
  });

  it("says when consent was given and nothing was sent", async () => {
    mockJobs = {
      jobs: [
        succeededJob({
          status: "failed",
          submitted: false,
          consentedOnly: true,
          trainedModel: null,
          usage: { trainedTokens: null },
          error: "the upload failed",
        }),
      ],
      inFlight: null,
    };
    await openSection();
    await waitFor(() =>
      expect(screen.getByText(/consented, nothing was sent/)).toBeInTheDocument(),
    );
  });
});
