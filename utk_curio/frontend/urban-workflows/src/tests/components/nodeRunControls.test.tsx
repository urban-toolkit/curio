/**
 * A node's run controls: Play, the Save output toggle and the run status.
 *
 * One component draws each of them in a node's header, on the canvas and in a
 * notebook cell alike: Play first, before the title; the status at the right;
 * the toggle among the node's tools. There is no bottom row any more.
 */
import React from "react";
import { fireEvent, render } from "@testing-library/react";

import { NodeRunControls, type NodeRunControlsProps } from "../../components/nodes/NodeRunControls";

function props(over: Partial<NodeRunControlsProps> = {}): Omit<NodeRunControlsProps, "part"> {
  return {
    nodeId: "n1",
    disablePlay: false,
    isLoading: false,
    output: { code: "success", content: "" },
    showSaveToggle: true,
    saveOutput: false,
    onSaveOutputChange: jest.fn(),
    onPlay: jest.fn(),
    ...over,
  };
}

const play = (c: HTMLElement) => c.querySelector("svg.fa-circle-play");
const toggle = (c: HTMLElement) => c.querySelector("#save-output-n1");

describe("the run controls", () => {
  test("in a node's header: Play alone at the start", () => {
    const p = props();
    const { container } = render(<NodeRunControls {...p} part="play" />);
    expect(play(container)).not.toBeNull();
    expect(toggle(container)).toBeNull();
    expect(container).not.toHaveTextContent("Done");
    fireEvent.click(play(container)!);
    expect(p.onPlay).toHaveBeenCalledTimes(1);
  });

  test("in a node's header: the status alone, and the toggle alone, with no second Play", () => {
    const status = render(<NodeRunControls {...props({ output: { code: "error", content: "x" } })} part="status" />);
    expect(play(status.container)).toBeNull();
    expect(toggle(status.container)).toBeNull();
    expect(status.container).toHaveTextContent("Error");
    status.unmount();

    const done = render(<NodeRunControls {...props()} part="status" />);
    expect(done.container).toHaveTextContent("Done");
    done.unmount();

    const save = render(<NodeRunControls {...props()} part="save" />);
    expect(play(save.container)).toBeNull();
    expect(toggle(save.container)).not.toBeNull();
    expect(save.container).not.toHaveTextContent("Done");
  });

  test("shows a spinner instead of Play while the node loads, and no Play when it has none", () => {
    const loading = render(<NodeRunControls {...props({ isLoading: true })} part="play" />);
    expect(play(loading.container)).toBeNull();
    expect(loading.container.querySelector(".spinner-border")).not.toBeNull();
    loading.unmount();

    const none = render(<NodeRunControls {...props({ disablePlay: true })} part="play" />);
    expect(play(none.container)).toBeNull();
    expect(none.container.querySelector(".spinner-border")).toBeNull();
  });

  test("flips the toggle through its callback", () => {
    const p = props();
    const { container } = render(<NodeRunControls {...p} part="save" />);
    fireEvent.click(toggle(container)!);
    expect(p.onSaveOutputChange).toHaveBeenCalledWith(true);
  });
});
