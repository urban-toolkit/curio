import {
  formatDuration,
  formatElapsed,
  formatTokenCount,
  sessionTokenTotals,
  turnStatusDisplay,
} from "../../components/agents/attach/agentRunStatus";
import type { AgentSessionTurn } from "../../api/agentsApi";

describe("formatElapsed", () => {
  it("formats m:ss with unbounded minutes", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(7_000)).toBe("0:07");
    expect(formatElapsed(83_000)).toBe("1:23");
    expect(formatElapsed(3_665_000)).toBe("61:05");
  });

  it("clamps negatives (clock skew) to zero", () => {
    expect(formatElapsed(-5_000)).toBe("0:00");
  });
});

describe("formatDuration", () => {
  it("uses seconds under a minute, m s beyond", () => {
    expect(formatDuration(900)).toBe("1s");
    expect(formatDuration(12_300)).toBe("12s");
    expect(formatDuration(60_000)).toBe("1m 00s");
    expect(formatDuration(83_000)).toBe("1m 23s");
  });
});

describe("formatTokenCount", () => {
  it("stays literal under 1000, compacts to k and M above", () => {
    expect(formatTokenCount(0)).toBe("0");
    expect(formatTokenCount(999)).toBe("999");
    expect(formatTokenCount(1000)).toBe("1.0k");
    expect(formatTokenCount(12_340)).toBe("12.3k");
    expect(formatTokenCount(1_234_000)).toBe("1.2M");
  });
});

describe("sessionTokenTotals", () => {
  const turnsWithRecords: AgentSessionTurn[] = [
    { role: "user", text: "q1" },
    {
      role: "agent",
      text: "a1",
      execution: {
        executionId: "e1",
        usage: { inputTokens: 100, outputTokens: 200 },
        status: "ok",
      },
    },
    // Pre-dev/37 turn and a null-usage run: skipped, never fabricated zeros.
    { role: "agent", text: "a2" },
    {
      role: "agent",
      text: "a3",
      execution: { executionId: "e3", usage: null, status: "ok" },
    },
    {
      role: "agent",
      text: "a4",
      execution: {
        executionId: "e4",
        usage: { inputTokens: 10, outputTokens: 20 },
        status: "ok",
      },
    },
  ];

  it("sums the persisted execution usage across turns", () => {
    expect(sessionTokenTotals(turnsWithRecords)).toEqual({
      inputTokens: 110,
      outputTokens: 220,
    });
  });

  it("adds the in-flight run's interim sums when given", () => {
    expect(
      sessionTokenTotals(turnsWithRecords, { inputTokens: 5, outputTokens: 7 }),
    ).toEqual({ inputTokens: 115, outputTokens: 227 });
  });

  it("returns null when nothing was ever reported (no fabricated 0)", () => {
    expect(sessionTokenTotals([{ role: "user", text: "q" }])).toBeNull();
    expect(sessionTokenTotals([])).toBeNull();
  });

  it("interim sums alone still count (first run of a fresh session)", () => {
    expect(sessionTokenTotals([], { inputTokens: 3, outputTokens: 4 })).toEqual({
      inputTokens: 3,
      outputTokens: 4,
    });
  });
});

describe("turnStatusDisplay (per-reply, dev/80 amendment)", () => {
  const doneTurn: AgentSessionTurn = {
    role: "agent",
    text: "a",
    execution: {
      executionId: "e1",
      usage: { inputTokens: 1, outputTokens: 2 },
      status: "ok",
      durationMs: 5000,
    },
  };

  it("an execution-carrying agent turn derives its own finished state", () => {
    expect(turnStatusDisplay(doneTurn)).toEqual({
      kind: "done",
      durationMs: 5000,
      usage: { inputTokens: 1, outputTokens: 2 },
      pendingReview: undefined,
    });
  });

  it("the review flag rides only when asked for (the newest reply)", () => {
    expect(turnStatusDisplay(doneTurn, { pendingReview: true })).toMatchObject({
      kind: "done",
      pendingReview: true,
    });
  });

  it("an error turn derives the failed state (duration from its record if any)", () => {
    expect(
      turnStatusDisplay({ role: "agent", text: "(error) boom", error: true }),
    ).toEqual({ kind: "error", durationMs: undefined });
    expect(
      turnStatusDisplay({
        role: "agent",
        text: "(error) boom",
        error: true,
        execution: { executionId: "e", usage: null, status: "error", durationMs: 800 },
      }),
    ).toEqual({ kind: "error", durationMs: 800 });
  });

  it("null-usage runs still show finished, with no fabricated tokens", () => {
    expect(
      turnStatusDisplay({
        role: "agent",
        text: "a",
        execution: { executionId: "e", usage: null, status: "ok", durationMs: 900 },
      }),
    ).toEqual({ kind: "done", durationMs: 900, usage: null, pendingReview: undefined });
  });

  it("pre-dev/37 agent turns and user turns yield null (no fabricated status)", () => {
    expect(turnStatusDisplay({ role: "agent", text: "a" })).toBeNull();
    expect(turnStatusDisplay({ role: "user", text: "q" })).toBeNull();
  });
});
