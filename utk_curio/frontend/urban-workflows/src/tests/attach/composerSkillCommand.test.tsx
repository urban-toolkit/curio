import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * `/` in an agent's chat lists the skills its next run lists.
 *
 * A message that starts with `/` opens the list, read each time it opens:
 * typing narrows it, the arrows move through it, and Enter, Tab or a click
 * puts `/<name>` in the message instead of sending it. Escape closes the list
 * and never the chat behind it. Sent, the message keeps `/<name>`: the server
 * hands that skill to the run with it.
 */

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { Composer } from "../../components/agents/attach/chat/Composer";
import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import type { AgentAttachment, RunSkill } from "../../services/agents";

const SKILLS: RunSkill[] = [
  { name: "map-edits", description: "Use this skill to write a Map Editor node's edits.", held: false },
  { name: "widgets", description: "Use this skill when a node declares a widget.", held: true },
  { name: "provenance", description: "Use this skill to read a node's history.", held: false },
];

function Harness({ loadSkills, onSend }: { loadSkills?: () => Promise<RunSkill[]>; onSend: (text: string) => void }) {
  const [value, setValue] = React.useState("");
  const ref = React.useRef<HTMLTextAreaElement | null>(null);
  return (
    <Composer
      value={value}
      onChange={setValue}
      onSend={() => onSend(value)}
      busy={false}
      textareaRef={ref}
      loadSkills={loadSkills}
    />
  );
}

const box = () => screen.getByRole("textbox", { name: "Message this agent" }) as HTMLTextAreaElement;
const type = (text: string) => fireEvent.change(box(), { target: { value: text } });
const options = () =>
  within(screen.getByRole("listbox", { name: "Skills" }))
    .queryAllByRole("option")
    .map((option) => option.querySelector("span")?.textContent);

async function openWithSlash(loadSkills = jest.fn(() => Promise.resolve(SKILLS)), onSend = jest.fn()) {
  render(<Harness loadSkills={loadSkills} onSend={onSend} />);
  type("/");
  await waitFor(() => expect(options()).toHaveLength(3));
  return { loadSkills, onSend };
}

describe("the / list", () => {
  it("opens on a leading slash with the run's skills, read when it opens", async () => {
    const { loadSkills } = await openWithSlash();
    expect(loadSkills).toHaveBeenCalledTimes(1);
    expect(options()).toEqual(["/map-edits", "/widgets · in this chat", "/provenance"]);
    expect(box()).toHaveAttribute("aria-expanded", "true");
  });

  it("narrows as the name is typed, names first", async () => {
    await openWithSlash();
    type("/pro");
    expect(options()).toEqual(["/provenance"]);
    type("/edit");
    expect(options()).toEqual(["/map-edits"]);
    type("/nothing");
    expect(screen.getByText("No skill matches /nothing.")).toBeInTheDocument();
  });

  it("Enter puts the chosen skill in the message and sends nothing; the next Enter sends", async () => {
    const { onSend } = await openWithSlash();
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect(box().value).toBe("/provenance ");
    expect(screen.queryByRole("listbox")).toBeNull();
    type("/provenance what changed here?");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("/provenance what changed here?");
  });

  it("Tab and a click choose too, keeping the rest of the message", async () => {
    await openWithSlash();
    type("/wid remove the two towers");
    // The caret is at the end, past the first word: the list is shut.
    expect(screen.queryByRole("listbox")).toBeNull();
    // The caret moves back into the first word, as an arrow key would put it.
    box().setSelectionRange(3, 3);
    fireEvent.keyUp(box(), { key: "ArrowLeft" });
    await waitFor(() => expect(options()).toEqual(["/widgets · in this chat"]));
    fireEvent.keyDown(box(), { key: "Tab" });
    expect(box().value).toBe("/widgets remove the two towers");
    expect(screen.queryByRole("listbox")).toBeNull();

    type("/m");
    await waitFor(() => expect(options()).toEqual(["/map-edits"]));
    fireEvent.mouseDown(screen.getByRole("option", { name: /map-edits/ }));
    expect(box().value).toBe("/map-edits ");
  });

  it("Escape closes the list, and only a second Escape reaches the window", async () => {
    await openWithSlash();
    const onWindowKey = jest.fn();
    window.addEventListener("keydown", onWindowKey);
    try {
      fireEvent.keyDown(box(), { key: "Escape" });
      expect(screen.queryByRole("listbox")).toBeNull();
      expect(onWindowKey).not.toHaveBeenCalled();
      fireEvent.keyDown(box(), { key: "Escape" });
      expect(onWindowKey).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("keydown", onWindowKey);
    }
  });

  it("is never offered without the chat's skills, nor for a message that starts otherwise", async () => {
    const { unmount } = render(<Harness onSend={jest.fn()} />);
    type("/");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box()).not.toHaveAttribute("aria-expanded");
    unmount();
    const loadSkills = jest.fn(() => Promise.resolve(SKILLS));
    render(<Harness loadSkills={loadSkills} onSend={jest.fn()} />);
    type("use /widgets here");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(loadSkills).not.toHaveBeenCalled();
    // The same composer offers the list once the message starts with the slash.
    type("/widgets here");
    box().setSelectionRange(2, 2);
    fireEvent.keyUp(box(), { key: "ArrowLeft" });
    await waitFor(() => expect(options()).toEqual(["/widgets · in this chat"]));
    expect(loadSkills).toHaveBeenCalledTimes(1);
  });

  it("says so when the agent lists no skills, or they could not be read", async () => {
    const { unmount } = render(<Harness loadSkills={() => Promise.resolve([])} onSend={jest.fn()} />);
    type("/");
    expect(await screen.findByText("This agent lists no skills.")).toBeInTheDocument();
    unmount();
    render(<Harness loadSkills={() => Promise.reject(new Error("offline"))} onSend={jest.fn()} />);
    type("/");
    expect(await screen.findByText("Could not read this agent's skills.")).toBeInTheDocument();
  });
});

describe("in the chat panel", () => {
  const attachment: AgentAttachment = {
    attachmentId: "a1",
    coord: "agent.curio.node-builder@1",
    target: { kind: "canvas" },
    sessionId: "s1",
    revision: 1,
    name: "Node Builder",
    category: "node",
    hooks: ["canvas"],
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
  };

  it("Escape on the list keeps the chat open, and sending keeps /<name> in the message", async () => {
    const onClose = jest.fn();
    const onSend = jest.fn(() => Promise.resolve());
    const loadSkills = jest.fn(() => Promise.resolve(SKILLS));
    render(
      <MemoryRouter>
        <AgentChatPanel attachment={attachment} turns={[]} onSend={onSend} onClose={onClose} loadSkills={loadSkills} />
      </MemoryRouter>,
    );
    type("/");
    await waitFor(() => expect(options()).toHaveLength(3));
    fireEvent.keyDown(box(), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByRole("listbox")).toBeNull();

    type("/map-edits make the river buffer 50 m");
    await act(async () => {
      fireEvent.keyDown(box(), { key: "Enter" });
    });
    expect(onSend).toHaveBeenCalledWith("/map-edits make the river buffer 50 m");
  });
});
