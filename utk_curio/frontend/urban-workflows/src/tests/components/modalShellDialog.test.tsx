import React from "react";
import { render, screen } from "@testing-library/react";
import ModalShell from "../../components/ModalShell";

/**
 * Modals are dialogs.
 *
 * The catalog drawers have carried `role="dialog"` + `aria-modal` + a name from
 * the start, and the whole e2e suite locates them that way. The modals built on
 * ModalShell carried none of it, so every one of them - including the panel
 * that holds the user's API key - was an unlabeled group to a screen reader,
 * and tests had nothing to target but raw headings.
 *
 * Naming comes in two shapes because the consumers do: most render an `<h2>`
 * and pass its id as `titleId`; three have no usable heading (GenericDialog's
 * children are arbitrary, TrillProvenanceWindow titles with a `<p>`, and
 * DatasetDetailModal's title belongs to a panel shared with a page route) and
 * pass a literal `label` instead.
 */
describe("ModalShell is announced as a dialog", () => {
  it("exposes the dialog role and marks itself modal", () => {
    render(
      <ModalShell onClose={jest.fn()} label="Example">
        <p>body</p>
      </ModalShell>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("takes its name from the consumer's heading via titleId", () => {
    render(
      <ModalShell onClose={jest.fn()} titleId="example-title">
        <h2 id="example-title">Node settings</h2>
      </ModalShell>,
    );
    expect(screen.getByRole("dialog", { name: "Node settings" })).toBeInTheDocument();
  });

  it("falls back to an explicit label when there is no heading to point at", () => {
    render(
      <ModalShell onClose={jest.fn()} label="Dataset details">
        <p>no heading here</p>
      </ModalShell>,
    );
    expect(screen.getByRole("dialog", { name: "Dataset details" })).toBeInTheDocument();
  });

  it("prefers the heading over the label when both are supplied", () => {
    // titleId wins, so a stale `label` on a consumer that later grew a heading
    // cannot quietly shadow the real title.
    render(
      <ModalShell onClose={jest.fn()} titleId="real-title" label="ignored">
        <h2 id="real-title">The real one</h2>
      </ModalShell>,
    );
    expect(screen.getByRole("dialog", { name: "The real one" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "ignored" })).toBeNull();
  });

  it("does not nest a second dialog inside itself", () => {
    // AgentImportModal used to put its own role="dialog" + aria-label on the
    // body div inside the shell. Once the shell carried the role too, a
    // by-name query matched two elements and threw.
    render(
      <ModalShell onClose={jest.fn()} titleId="import-title">
        <div>
          <h2 id="import-title">Import agent package</h2>
        </div>
      </ModalShell>,
    );
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
