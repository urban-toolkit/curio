/**
 * dev/127: the owner's requirement, tested — "it is important to clearly
 * display all attempts to fix in the chat transcript", with "the code it
 * attempted to execute alongside the error message".
 */
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  AgentSolveAttemptsCard,
  stoppedByPhrase,
} from "../../components/agents/content/AgentSolveAttemptsCard";
import type { AgentSolveAttemptsPart } from "../../api/agentsApi";

const part = (over: Partial<AgentSolveAttemptsPart> = {}): AgentSolveAttemptsPart => ({
  type: "solveAttempts",
  nodeId: "08b108a1",
  label: "Calculate Density — Join population data to boundaries",
  attachmentId: "att-nb",
  rounds: 3,
  stoppedBy: "rounds",
  verdict: "fail",
  attempts: [
    {
      round: 1,
      verdict: "fail",
      kind: "execution-error",
      error: "KeyError: 'community_area' · at .../pandas/core/generic.py:1776 in _get_label_or_level_values",
      code: "boundaries = arg[0]\npopulation = arg[1]\nmerged = boundaries.merge(population, on='community_area')",
      durationMs: 4120,
    },
    {
      round: 2,
      verdict: "fail",
      kind: "execution-error",
      error:
        "KeyError: 'No common column found between boundaries and population datasets to perform a join.' · raised by the code's own check, not by the library",
      code: "raise KeyError('No common column found between boundaries and population datasets to perform a join.')",
      durationMs: 8677,
    },
    {
      round: 3,
      verdict: "fail",
      kind: "execution-error",
      error: "AttributeError: 'DataFrame' object has no attribute 'crs'",
      code: "merged = population.merge(boundaries, left_on='GEOID', right_on='area_numbe')\nreturn merged.to_crs(3395)",
      durationMs: 3110,
    },
  ],
  ...over,
});

describe("AgentSolveAttemptsCard (dev/127)", () => {
  it("shows every attempt, with its round, error and the code it ran", () => {
    render(<AgentSolveAttemptsCard part={part()} />);
    const card = screen.getByRole("group", {
      name: /Attempts to fix Calculate Density/,
    });
    // All three attempts, none summarized away.
    expect(within(card).getByText(/Round 1 · execution-error · 4.1 s/)).toBeInTheDocument();
    expect(within(card).getByText(/Round 2 · execution-error · 8.7 s/)).toBeInTheDocument();
    expect(within(card).getByText(/Round 3 · execution-error · 3.1 s/)).toBeInTheDocument();
    // The exception lines are whole — the report's were cut mid-token.
    expect(card).toHaveTextContent("KeyError: 'community_area'");
    expect(card).toHaveTextContent("AttributeError: 'DataFrame' object has no attribute 'crs'");
    expect(card).toHaveTextContent("raised by the code's own check");
    // And the code beside each of them.
    expect(card).toHaveTextContent("boundaries.merge(population, on='community_area')");
    expect(card).toHaveTextContent("left_on='GEOID', right_on='area_numbe'");
    expect(within(card).getAllByText("The code this attempt ran")).toHaveLength(3);
  });

  it("names how many attempts there were and what stopped the loop", () => {
    render(<AgentSolveAttemptsCard part={part()} />);
    expect(screen.getByText(/3 attempts · the attempt cap was reached/)).toBeInTheDocument();
    expect(stoppedByPhrase("budget")).toBe("this node's time budget was spent");
    expect(stoppedByPhrase("nonsense")).toBe("");
  });

  it("opens the last attempt and leaves the earlier ones collapsed", () => {
    render(<AgentSolveAttemptsCard part={part()} />);
    const rows = document.querySelectorAll("details");
    expect(rows).toHaveLength(3);
    expect((rows[0] as HTMLDetailsElement).open).toBe(false);
    expect((rows[2] as HTMLDetailsElement).open).toBe(true);
  });

  it("opens the node's own agent, naming the node", () => {
    const onOpenChat = jest.fn();
    render(<AgentSolveAttemptsCard part={part()} onOpenChat={onOpenChat} />);
    const button = screen.getByRole("button", {
      name: /Open the Node Builder for Calculate Density/,
    });
    fireEvent.click(button);
    expect(onOpenChat).toHaveBeenCalledWith("att-nb");
  });

  it("renders no action without an attachment or a way to open it", () => {
    render(<AgentSolveAttemptsCard part={part({ attachmentId: null })} onOpenChat={jest.fn()} />);
    expect(screen.queryByRole("button", { name: /Open Node Builder/ })).toBeNull();
    render(<AgentSolveAttemptsCard part={part()} />);
    expect(screen.queryByRole("button", { name: /Open Node Builder/ })).toBeNull();
  });

  it("renders a decline as prose, never as runnable code", () => {
    render(
      <AgentSolveAttemptsCard
        part={part({
          stoppedBy: "decline",
          attempts: [
            {
              round: 1,
              verdict: "fail",
              kind: "source-missing",
              error: "the content builder declined: the Census API requires an API key",
              code: "I cannot write this without an API key for api.census.gov.",
              codeIsProse: true,
            },
          ],
        })}
      />,
    );
    expect(
      screen.getByText("What the builder said instead of writing code"),
    ).toBeInTheDocument();
    expect(document.querySelector("pre")).toBeNull();
    expect(screen.getByText(/the builder declined — it needs something from you/)).toBeInTheDocument();
  });

  it("says when a field or the trail itself was truncated", () => {
    render(
      <AgentSolveAttemptsCard
        part={part({
          elided: 4,
          attempts: [
            {
              round: 5,
              verdict: "fail",
              kind: "execution-error",
              error: "ValueError: boom",
              errorTruncated: true,
              code: "x = 1",
              codeTruncated: true,
            },
          ],
        })}
      />,
    );
    expect(screen.getByText(/The code this attempt ran \(truncated\)/)).toBeInTheDocument();
    expect(screen.getByText(/4 earlier attempts not shown/)).toBeInTheDocument();
  });

  it("survives an empty trail without inventing one", () => {
    render(<AgentSolveAttemptsCard part={part({ attempts: [], rounds: 0 })} />);
    expect(screen.getByText(/0 attempts/)).toBeInTheDocument();
    expect(document.querySelectorAll("details")).toHaveLength(0);
  });
});
