/**
 * A package's card dropped on the canvas from the Node Catalog drawer
 * (`usePackageCardDrop`). A package with one node makes it. A package with
 * several offers them in a menu at the drop point, Curio's one dark pop-up
 * menu (`CardContextMenu`), and the node picked is made: at once when the
 * dataflow has the package, after the drawer's Add review when it has not.
 * Escape or a click outside makes no node. A hosted guest's drop of a package
 * the dataflow has not added is refused before any menu: guests never install.
 */
import React from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { usePackageCardDrop, type PackageCardDrop } from "../../components/packages/usePackageCardDrop";
import { modalStackDepth } from "../../components/ModalShell";
import {
  guestAddRefusal,
  usePackageAddRequests,
  type PackageAddRequest,
} from "../../services/packages/packageAddRequests";
import type { PackageCardDragPayload } from "../../services/packages/packageCardDrag";

const PROBE: PackageCardDragPayload = {
  dirName: "test.wheelhouse-probe@1",
  name: "Wheelhouse Probe",
  kind: "node",
  nodes: [{ nodeType: "test.wheelhouse-probe/probe@1", label: "Wheelhouse Probe" }],
};
const FIRST = { nodeType: "test.wheelhouse-pair/first@1", label: "Pair First Probe" };
const SECOND = { nodeType: "test.wheelhouse-pair/second@1", label: "Pair Second Probe" };
const PAIR: PackageCardDragPayload = {
  dirName: "test.wheelhouse-pair@1",
  name: "Wheelhouse Pair",
  kind: "node",
  nodes: [FIRST, SECOND],
};
/** Where the node goes on the canvas, and where the card was dropped in the window. */
const POSITION = { x: 120, y: 80 };
const AT = { x: 340, y: 260 };

/** A canvas that takes card drops, as MainCanvas does. */
function canvas({ added = [] as string[], hostedGuest = false } = {}) {
  const createNode = jest.fn();
  const showToast = jest.fn();
  let drop: (dropped: PackageCardDrop) => void = () => undefined;
  function Canvas() {
    const cardDrop = usePackageCardDrop({ dataflowPackages: added, hostedGuest, createNode, showToast });
    drop = cardDrop.drop;
    return <>{cardDrop.menu}</>;
  }
  render(<Canvas />);
  return {
    createNode,
    showToast,
    drop: (card: PackageCardDragPayload) => act(() => drop({ card, position: POSITION, at: AT })),
  };
}

/** The open Node Catalog drawer: the Add requests drops send it. */
function openDrawer() {
  const requests: PackageAddRequest[] = [];
  function Drawer() {
    usePackageAddRequests((request) => {
      requests.push(request);
      return true;
    });
    return null;
  }
  render(<Drawer />);
  return requests;
}

const pairMenu = () => screen.queryByRole("menu", { name: "Wheelhouse Pair nodes" });

/** Let a task go by: what a closed menu gives back, it gives back a task later. */
const aTaskLater = () => act(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));

describe("a card of a package with one node", () => {
  it("makes its node where it was dropped, with no menu", () => {
    const { createNode, drop } = canvas({ added: [PROBE.dirName] });
    drop(PROBE);
    expect(createNode).toHaveBeenCalledTimes(1);
    expect(createNode).toHaveBeenCalledWith(PROBE.nodes[0], POSITION);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("makes it once the drawer's Add review has added the package", () => {
    const requests = openDrawer();
    const { createNode, drop } = canvas();
    drop(PROBE);
    expect(requests.map((r) => [r.dirName, r.kind])).toEqual([[PROBE.dirName, "node"]]);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(createNode).not.toHaveBeenCalled();
    act(() => requests[0].onAdded());
    expect(createNode).toHaveBeenCalledWith(PROBE.nodes[0], POSITION);
  });
});

describe("a card of a package with several nodes", () => {
  it("opens a menu of the package's nodes at the drop point, and makes none yet", () => {
    const { createNode, drop } = canvas({ added: [PAIR.dirName] });
    drop(PAIR);
    expect(pairMenu()).toHaveStyle({ position: "fixed", left: "340px", top: "260px" });
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual([
      "Pair First Probe",
      "Pair Second Probe",
    ]);
    expect(createNode).not.toHaveBeenCalled();
  });

  it("opens it over the catalog drawer the card came from", () => {
    const { drop } = canvas({ added: [PAIR.dirName] });
    drop(PAIR);
    // In <body>, out of any stacking context of the canvas, on the overlay layer.
    expect(pairMenu()!.parentElement).toBe(document.body);
    expect(pairMenu()!.style.zIndex).toBe("var(--curio-z-modal)");
  });

  it("makes the node picked where the card was dropped", async () => {
    const { createNode, drop } = canvas({ added: [PAIR.dirName] });
    drop(PAIR);
    await userEvent.click(screen.getByRole("menuitem", { name: "Pair Second Probe" }));
    expect(createNode).toHaveBeenCalledTimes(1);
    expect(createNode).toHaveBeenCalledWith(SECOND, POSITION);
    expect(pairMenu()).toBeNull();
  });

  it("makes the node picked once the drawer's Add review has added the package", async () => {
    const requests = openDrawer();
    const { createNode, drop } = canvas();
    drop(PAIR);
    // The menu comes first: nothing is asked of the drawer before a pick.
    expect(requests).toEqual([]);
    await userEvent.click(screen.getByRole("menuitem", { name: "Pair Second Probe" }));
    expect(requests.map((r) => [r.dirName, r.kind])).toEqual([[PAIR.dirName, "node"]]);
    expect(createNode).not.toHaveBeenCalled();
    act(() => requests[0].onAdded());
    expect(createNode).toHaveBeenCalledTimes(1);
    expect(createNode).toHaveBeenCalledWith(SECOND, POSITION);
  });

  it("makes no node on Escape", async () => {
    const requests = openDrawer();
    const { createNode, drop } = canvas();
    drop(PAIR);
    await userEvent.keyboard("{Escape}");
    expect(pairMenu()).toBeNull();
    expect(createNode).not.toHaveBeenCalled();
    expect(requests).toEqual([]);
  });

  it("makes no node on a click outside the menu", async () => {
    const requests = openDrawer();
    const { createNode, drop } = canvas();
    drop(PAIR);
    await userEvent.click(document.body);
    expect(pairMenu()).toBeNull();
    expect(createNode).not.toHaveBeenCalled();
    expect(requests).toEqual([]);
  });

  it("keeps Escape to itself: the drawer under it stands down while it is open", async () => {
    // The menus of the tests before this one have given their layers back.
    await aTaskLater();
    const base = modalStackDepth();
    const seenByTheDrawer: number[] = [];
    const drawerEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") seenByTheDrawer.push(modalStackDepth());
    };
    window.addEventListener("keydown", drawerEscape);
    try {
      const { drop } = canvas({ added: [PAIR.dirName] });
      drop(PAIR);
      expect(modalStackDepth()).toBe(base + 1);
      await userEvent.keyboard("{Escape}");
      expect(pairMenu()).toBeNull();
      expect(seenByTheDrawer).toEqual([base + 1]);
      // The layer is given back once that Escape is over.
      await aTaskLater();
      expect(modalStackDepth()).toBe(base);
    } finally {
      window.removeEventListener("keydown", drawerEscape);
    }
  });
});

describe("a hosted guest's drop", () => {
  it("of a package the dataflow has not added is refused before any menu", () => {
    const requests = openDrawer();
    const { createNode, showToast, drop } = canvas({ hostedGuest: true });
    drop(PAIR);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(showToast).toHaveBeenCalledWith(guestAddRefusal("Wheelhouse Pair"), "warning");
    expect(requests).toEqual([]);
    expect(createNode).not.toHaveBeenCalled();
  });

  it("of a one-node card is refused the same way", () => {
    const requests = openDrawer();
    const { createNode, showToast, drop } = canvas({ hostedGuest: true });
    drop(PROBE);
    expect(showToast).toHaveBeenCalledWith(guestAddRefusal("Wheelhouse Probe"), "warning");
    expect(requests).toEqual([]);
    expect(createNode).not.toHaveBeenCalled();
  });

  it("of a package the dataflow has opens the menu, and the node picked is made", async () => {
    const { createNode, showToast, drop } = canvas({ added: [PAIR.dirName], hostedGuest: true });
    drop(PAIR);
    await userEvent.click(screen.getByRole("menuitem", { name: "Pair First Probe" }));
    expect(createNode).toHaveBeenCalledWith(FIRST, POSITION);
    expect(showToast).not.toHaveBeenCalled();
  });
});
