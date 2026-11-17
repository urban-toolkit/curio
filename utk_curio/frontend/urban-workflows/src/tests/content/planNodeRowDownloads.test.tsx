/**
 * A landed plan's row: its Solve (validate-node) and its Run (run-node) of the
 * node. While one waits on a download on first use of what the node reads,
 * SAM 3's 3.4 GB of weights among them, the row says how far it has come on a
 * line of its own, as a node's Solve narrates it, and takes the line away once
 * the downloads are over or the row's run ends.
 */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { PlanNodeRow } from "../../components/agents/content/reviewCard/PlanNodeRow";

const MESSAGE = "Downloading model.safetensors, a file of the weights of model.curio.sam3: 1.21 of 3.44 GB (35%)";
const NODE = { ref: "load", nodeType: "curio.builtin/data-loading", title: "Load", intent: "load the heat data" };

/** A row's Solve or Run held open, which says its lines through what the row hands it. */
function held() {
  let say: (line: string) => void = () => undefined;
  let finish: () => void = () => undefined;
  const run = jest.fn((onLine?: (line: string) => void) => {
    say = onLine ?? (() => undefined);
    return new Promise<void>((resolve) => {
      finish = resolve;
    });
  });
  return {
    run,
    say: (line: string) => act(() => say(line)),
    finish: () => act(async () => { finish(); }),
  };
}

describe("a plan row's Solve and Run say how far a download has come", () => {
  it.each([
    ["Solve", "created", "onSolve", /Solve node Load/],
    ["Run", "validated", "onRun", /Run through node Load/],
  ])("its %s shows each line its run says, and none once the downloads are over or it ends", async (_kind, state, prop, button) => {
    const row = held();
    // The row's run, whatever the types of the code under test name.
    const runs = { [prop]: row.run } as any;
    render(<PlanNodeRow node={NODE} applied deps={[]} state={state} solvable solveBlocker={null} {...runs} />);

    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(row.run).toHaveBeenCalledTimes(1);

    row.say(MESSAGE);
    expect(screen.getByText(MESSAGE)).toBeInTheDocument();
    // The downloads over, the node runs: the line goes.
    row.say("");
    expect(screen.queryByText(MESSAGE)).toBeNull();
    // A run that ends takes its line with it.
    row.say(MESSAGE);
    await row.finish();
    expect(screen.queryByText(MESSAGE)).toBeNull();
  });
});
