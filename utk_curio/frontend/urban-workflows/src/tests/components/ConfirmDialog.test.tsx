import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import ConfirmDialog from "../../components/ConfirmDialog";
import PromptDialog from "../../components/PromptDialog";
import { modalStackDepth } from "../../components/ModalShell";

/**
 * The two dialogs that replaced `window.confirm` / `window.prompt` (#197).
 *
 * Both are built on ModalShell, so the portal, the backdrop, the topmost-only
 * Escape and the `modalStackDepth()` registration come from there and are
 * covered by `modalShellDialog.test.tsx`. What is asserted here is the part
 * these two add: the copy survives the move off the native dialogs, cancelling
 * really cancels, and `busy` holds the dialog still while an action runs.
 */

function dialog(): HTMLElement {
  const el = document.body.querySelector('[data-curio-modal-shell="true"]');
  if (!el) throw new Error("dialog not found (ModalShell uses a portal)");
  return el as HTMLElement;
}

function backdrop(): HTMLElement {
  const el = document.body.querySelector('[class*="backdrop"]');
  if (!el) throw new Error("backdrop not found");
  return el as HTMLElement;
}

describe("ConfirmDialog", () => {
  test("renders the title, the body and both buttons", () => {
    render(
      <ConfirmDialog
        title="Remove node-explainer?"
        body="Remove node-explainer (agent.node-explainer@1.0.0) from this dataflow?"
        confirmLabel="Remove"
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
      />,
    );

    expect(screen.getByText("Remove node-explainer?")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Remove node-explainer (agent.node-explainer@1.0.0) from this dataflow?",
      ),
    ).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  test("a blank line in the body becomes a second paragraph", () => {
    // The native calls carried their structure as `\n\n`, and the #177 delete
    // warning depends on that second paragraph reading as its own sentence.
    render(
      <ConfirmDialog
        title="Delete Two?"
        body={
          "Delete Two from your Data Catalog?\n\n" +
          "It is used in 3 dataflows (consumed by 2 nodes); its references there will be removed."
        }
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
      />,
    );

    const paragraphs = dialog().querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveTextContent("Delete Two from your Data Catalog?");
    expect(paragraphs[1]).toHaveTextContent("used in 3 dataflows");
    expect(paragraphs[1]).toHaveTextContent("consumed by 2 nodes");
  });

  test("a ReactNode body renders as given, so a call site can list dependencies", () => {
    render(
      <ConfirmDialog
        title="Add Dataflow Builder?"
        body={
          <>
            <p>Add Dataflow Builder to this dataflow?</p>
            <ul>
              <li>Node Content Builder (not installed)</li>
            </ul>
          </>
        }
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
      />,
    );

    expect(screen.getByText("Node Content Builder (not installed)")).toBeInTheDocument();
    expect(dialog().querySelector("li")).not.toBeNull();
  });

  test("confirm and cancel each call only their own handler", () => {
    const onConfirm = jest.fn();
    const onCancel = jest.fn();
    const { rerender } = render(
      <ConfirmDialog title="T" confirmLabel="Go" onConfirm={onConfirm} onCancel={onCancel} />,
    );

    fireEvent.click(within(dialog()).getByRole("button", { name: "Go" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();

    rerender(
      <ConfirmDialog title="T" confirmLabel="Go" onConfirm={onConfirm} onCancel={onCancel} />,
    );
    fireEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  test("Escape and the backdrop both cancel", () => {
    const onCancel = jest.fn();
    render(<ConfirmDialog title="T" onConfirm={jest.fn()} onCancel={onCancel} />);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);

    fireEvent.click(backdrop());
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  test("a destructive dialog focuses Cancel, so a stray Enter deletes nothing", () => {
    render(
      <ConfirmDialog
        title="Delete forever?"
        destructive
        confirmLabel="Delete forever"
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
      />,
    );

    expect(document.activeElement).toBe(
      within(dialog()).getByRole("button", { name: "Cancel" }),
    );
  });

  test("a non-destructive dialog focuses the confirm button", () => {
    render(
      <ConfirmDialog
        title="Add it?"
        confirmLabel="Add to project"
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
      />,
    );

    expect(document.activeElement).toBe(
      within(dialog()).getByRole("button", { name: "Add to project" }),
    );
  });

  test("busy disables both buttons and makes Escape inert", () => {
    const onCancel = jest.fn();
    render(<ConfirmDialog title="T" busy onConfirm={jest.fn()} onCancel={onCancel} />);

    const buttons = within(dialog()).getAllByRole("button");
    // The close X included: nothing in the dialog commits a second action
    // while the first is in flight.
    expect(within(dialog()).getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(buttons.some((b) => b.textContent === "Working…")).toBe(true);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  test("registers on the modal stack so the drawers' Escape listeners stand down", () => {
    // NodeCatalogDrawer / AgentCatalogDrawerProvider / AgentChatPanel all guard
    // with `if (modalStackDepth() > 0) return;`. A confirmation that did not
    // register would close the whole drawer behind it on Escape.
    const { unmount } = render(
      <ConfirmDialog title="T" onConfirm={jest.fn()} onCancel={jest.fn()} />,
    );
    expect(modalStackDepth()).toBe(1);
    unmount();
    expect(modalStackDepth()).toBe(0);
  });
});

describe("PromptDialog", () => {
  test("opens with the current value and returns the edited one", () => {
    const onConfirm = jest.fn();
    render(
      <PromptDialog
        title="Rename dataflow"
        fieldLabel="Name"
        initialValue="My flow"
        confirmLabel="Rename"
        onConfirm={onConfirm}
        onCancel={jest.fn()}
      />,
    );

    const input = screen.getByLabelText("Name") as HTMLInputElement;
    expect(input.value).toBe("My flow");
    expect(document.activeElement).toBe(input);

    fireEvent.change(input, { target: { value: "Renamed flow" } });
    fireEvent.click(within(dialog()).getByRole("button", { name: "Rename" }));

    expect(onConfirm).toHaveBeenCalledWith("Renamed flow");
  });

  test("Enter submits, the way the native prompt did", () => {
    const onConfirm = jest.fn();
    render(
      <PromptDialog
        title="Rename dataflow"
        fieldLabel="Name"
        initialValue="A"
        onConfirm={onConfirm}
        onCancel={jest.fn()}
      />,
    );

    fireEvent.submit(dialog().querySelector("form")!);
    expect(onConfirm).toHaveBeenCalledWith("A");
  });

  test("an empty or whitespace-only name cannot be submitted", () => {
    const onConfirm = jest.fn();
    render(
      <PromptDialog
        title="Rename dataflow"
        fieldLabel="Name"
        initialValue="A"
        confirmLabel="Rename"
        onConfirm={onConfirm}
        onCancel={jest.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "   " } });
    expect(within(dialog()).getByRole("button", { name: "Rename" })).toBeDisabled();

    fireEvent.submit(dialog().querySelector("form")!);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  test("the value is trimmed before it is handed back", () => {
    const onConfirm = jest.fn();
    render(
      <PromptDialog
        title="Rename dataflow"
        fieldLabel="Name"
        initialValue="A"
        confirmLabel="Rename"
        onConfirm={onConfirm}
        onCancel={jest.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  Padded  " } });
    fireEvent.click(within(dialog()).getByRole("button", { name: "Rename" }));

    expect(onConfirm).toHaveBeenCalledWith("Padded");
  });

  test("cancel reports nothing back", () => {
    const onConfirm = jest.fn();
    const onCancel = jest.fn();
    render(
      <PromptDialog
        title="Rename dataflow"
        fieldLabel="Name"
        initialValue="A"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(within(dialog()).getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
