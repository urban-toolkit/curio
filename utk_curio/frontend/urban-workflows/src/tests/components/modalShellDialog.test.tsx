import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ModalShell, { modalStackDepth } from "../../components/ModalShell";

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
 * and pass its id as `titleId`; two have no usable heading (GenericDialog's
 * children are arbitrary, and DatasetDetailModal's title belongs to a panel
 * shared with a page route) and pass a literal `label` instead.
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

/**
 * Escape closes a dialog.
 *
 * ModalShell claimed `aria-modal="true"` while registering no keydown handler,
 * so Escape did nothing — and because the backdrop covers the viewport and takes
 * pointer events, the next click went to the backdrop and the application read
 * as frozen. A user test hit this by reflexively pressing Escape and then could
 * not open a menu at all.
 */
describe("ModalShell responds to Escape", () => {
  const press = () => fireEvent.keyDown(window, { key: "Escape" });

  it("closes on Escape", () => {
    const onClose = jest.fn();
    render(
      <ModalShell onClose={onClose} label="Example">
        <p>body</p>
      </ModalShell>,
    );
    press();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores other keys", () => {
    // The listener sits on window, where every keystroke in the app arrives, so
    // this is the cheap guard against it closing on Enter from a form inside
    // the dialog.
    const onClose = jest.fn();
    render(
      <ModalShell onClose={onClose} label="Example">
        <p>body</p>
      </ModalShell>,
    );
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("stops listening once unmounted", () => {
    const onClose = jest.fn();
    const view = render(
      <ModalShell onClose={onClose} label="Example">
        <p>body</p>
      </ModalShell>,
    );
    view.unmount();
    press();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes exactly one dialog when two are open", () => {
    // Escape must not cascade. "On top" is read from document order, because
    // every shell portals into document.body and the last node there is the one
    // painted above the rest.
    const first = jest.fn();
    const second = jest.fn();
    render(
      <>
        <ModalShell onClose={first} label="First">
          <p>a</p>
        </ModalShell>
        <ModalShell onClose={second} label="Second">
          <p>b</p>
        </ModalShell>
      </>,
    );
    press();
    expect(first.mock.calls.length + second.mock.calls.length).toBe(1);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("lets a window listener that checks the depth stand down", () => {
    // The behavioural half of `escapeDefersToModal.test.ts`. Four surfaces
    // listen for Escape on window (both catalog drawers, the agent chat panel,
    // the fork picker) and a peer registered before this one cannot be silenced
    // by it, so each asks the depth and returns. This is that guard, run for
    // real: registered first, exactly as a drawer that mounted first would be.
    const drawerClose = jest.fn();
    const onKey = () => {
      if (modalStackDepth() > 0) return;
      drawerClose();
    };
    window.addEventListener("keydown", onKey);
    try {
      const onClose = jest.fn();
      render(
        <ModalShell onClose={onClose} label="Example">
          <p>body</p>
        </ModalShell>,
      );
      press();
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(drawerClose).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("keydown", onKey);
    }
  });

  it("reports its depth so the catalog drawers can stand down", () => {
    // The Agent Catalog drawer renders API Settings and agent import inside
    // itself and listens for Escape on window. It mounted first, so the modal
    // cannot stop its handler — the drawer checks this instead.
    expect(modalStackDepth()).toBe(0);
    const view = render(
      <ModalShell onClose={jest.fn()} label="Example">
        <p>body</p>
      </ModalShell>,
    );
    expect(modalStackDepth()).toBe(1);
    view.unmount();
    expect(modalStackDepth()).toBe(0);
  });

  it("leaves a busy dialog alone", () => {
    // NodeSaveAsModal and PackageMetadataModal pass `busy ? () => {} : onClose`.
    // Routing Escape through onClose is what makes that work untouched.
    const onClose = jest.fn();
    render(
      <ModalShell onClose={() => {}} label="Busy">
        <p>saving</p>
      </ModalShell>,
    );
    press();
    expect(onClose).not.toHaveBeenCalled();
  });
});

/**
 * Tab and Shift+Tab stay in an open dialog (issue #921).
 *
 * A dialog opened from the canvas's Discovery Catalog drawer has stacked above
 * the drawer since #959, so a click no longer reaches the drawer. The keyboard
 * still did: Tab walked out of the dialog into the page behind it, where the
 * drawer's own buttons opened a second dialog over the first.
 */
describe("ModalShell keeps Tab and Shift+Tab inside", () => {
  /** A page with two controls of its own, and the dialog one of them opened. */
  function Page({ open }: { open: boolean }) {
    return (
      <>
        <button type="button">Narrow…</button>
        <button type="button">Behind</button>
        {open ? (
          <ModalShell onClose={jest.fn()} label="Download Crimes">
            <input aria-label="Name" />
            <button type="button">Download</button>
          </ModalShell>
        ) : null}
      </>
    );
  }

  const dialog = () => screen.getByRole("dialog", { name: "Download Crimes" });

  it("sends Tab from its last control round to its first", async () => {
    const user = userEvent.setup();
    render(<Page open />);
    within(dialog()).getByRole("button", { name: "Download" }).focus();
    await user.tab();
    expect(within(dialog()).getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("sends Shift+Tab from its first control round to its last", async () => {
    const user = userEvent.setup();
    render(<Page open />);
    within(dialog()).getByRole("button", { name: "Close" }).focus();
    await user.tab({ shift: true });
    expect(within(dialog()).getByRole("button", { name: "Download" })).toHaveFocus();
  });

  it("takes the focus from the page when it opens, so the first Tab is inside it", async () => {
    const user = userEvent.setup();
    const view = render(<Page open={false} />);
    screen.getByRole("button", { name: "Narrow…" }).focus();
    view.rerender(<Page open />);
    await user.tab();
    expect(dialog()).toContainElement(document.activeElement as HTMLElement);
  });

  it("holds the keyboard in the dialog on top when two are open", async () => {
    // The one under it stands down, as it does for Escape: two dialogs that
    // both held the focus would pull it back and forth between them.
    const user = userEvent.setup();
    render(
      <>
        <ModalShell onClose={jest.fn()} label="Under">
          <button type="button">Under</button>
        </ModalShell>
        <ModalShell onClose={jest.fn()} label="Over">
          <button type="button">Over</button>
        </ModalShell>
      </>,
    );
    const over = screen.getByRole("dialog", { name: "Over" });
    within(over).getByRole("button", { name: "Over" }).focus();
    await user.tab();
    expect(within(over).getByRole("button", { name: "Close" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(within(over).getByRole("button", { name: "Over" })).toHaveFocus();
  });
});
