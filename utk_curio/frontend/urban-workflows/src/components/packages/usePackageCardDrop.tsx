import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { XYPosition } from "reactflow";

import { CardContextMenu } from "../catalog/CardContextMenu";
import { holdModalStack } from "../ModalShell";
import {
  guestAddRefusal,
  packageDropAction,
  requestPackageAdd,
} from "../../services/packages/packageAddRequests";
import type { PackageCardDragPayload, PackageCardNode } from "../../services/packages/packageCardDrag";
import type { ToastVariant } from "../../providers/ToastProvider";

/**
 * A package's card dropped on the canvas from the Node Catalog drawer.
 *
 * A hosted guest's drop of a package the dataflow has not added is refused
 * first, before any menu: guests never install. Otherwise a package with one
 * node makes it, and a package with several offers them in a menu at the drop
 * point, Curio's one dark pop-up menu (`CardContextMenu`); the node picked is
 * made. Escape or a click outside makes none. A package the dataflow has not
 * added goes through the open drawer's own Add first (the review, then the
 * install of its libraries), and the node is made once it is added.
 */

/** A card's drop on the canvas. */
export interface PackageCardDrop {
  card: PackageCardDragPayload;
  /** Where the node goes, in canvas coordinates. */
  position: XYPosition;
  /** Where the card was dropped in the window, where a menu of its nodes opens. */
  at: { x: number; y: number };
}

export interface PackageCardDropOptions {
  /** The packages the open dataflow has added (its lockfile). */
  dataflowPackages: readonly string[] | null | undefined;
  hostedGuest: boolean;
  /** Make *node* at *position*. */
  createNode: (node: PackageCardNode, position: XYPosition) => void;
  showToast: (message: string, variant?: ToastVariant) => void;
}

/** A drop of a card of a package with several nodes, waiting for a pick. */
interface PendingPick extends PackageCardDrop {
  action: "create" | "add";
}

export function usePackageCardDrop({
  dataflowPackages,
  hostedGuest,
  createNode,
  showToast,
}: PackageCardDropOptions): { drop: (dropped: PackageCardDrop) => void; menu: React.ReactNode } {
  const [pending, setPending] = useState<PendingPick | null>(null);

  const make = useCallback(
    (action: PendingPick["action"], card: PackageCardDragPayload, node: PackageCardNode, position: XYPosition) => {
      if (action === "create") {
        createNode(node, position);
      } else if (!requestPackageAdd({ dirName: card.dirName, kind: card.kind, onAdded: () => createNode(node, position) })) {
        showToast(`Add ${card.name} to this dataflow from the Node Catalog first.`, "warning");
      }
    },
    [createNode, showToast],
  );

  const drop = useCallback(
    (dropped: PackageCardDrop) => {
      const { card, position } = dropped;
      const action = packageDropAction({
        inDataflow: (dataflowPackages ?? []).includes(card.dirName),
        hostedGuest,
      });
      if (action === "refuse") {
        showToast(guestAddRefusal(card.name), "warning");
        return;
      }
      if (card.nodes.length === 1) {
        make(action, card, card.nodes[0], position);
        return;
      }
      setPending({ ...dropped, action });
    },
    [dataflowPackages, hostedGuest, showToast, make],
  );

  const dismiss = useCallback(() => setPending(null), []);
  const menu = pending ? (
    <PackageNodeMenu
      drop={pending}
      onPick={(node) => {
        setPending(null);
        make(pending.action, pending.card, node, pending.position);
      }}
      onDismiss={dismiss}
    />
  ) : null;

  return { drop, menu };
}

/** The package's nodes at the drop point, over the drawer the card came from. */
function PackageNodeMenu({
  drop,
  onPick,
  onDismiss,
}: {
  drop: PackageCardDrop;
  onPick: (node: PackageCardNode) => void;
  onDismiss: () => void;
}) {
  // One more layer over the drawer: every Escape listener under the menu
  // stands down (ModalShell's stack), so one Escape closes the menu alone.
  // The menu closes on the document's keydown, and React commits that before
  // the same Escape reaches the drawer's window listener, so the layer is
  // given back a task later.
  useEffect(() => {
    const release = holdModalStack();
    return () => {
      window.setTimeout(release, 0);
    };
  }, []);

  const { card, at } = drop;
  const menu = (
    <CardContextMenu
      x={at.x}
      y={at.y}
      layer="overlay"
      ariaLabel={`${card.name} nodes`}
      items={card.nodes.map((node) => ({ id: node.nodeType, label: node.label }))}
      onSelect={(id) => {
        const node = card.nodes.find((n) => n.nodeType === id);
        if (node) onPick(node);
      }}
      onDismiss={onDismiss}
    />
  );
  // In <body>, as ModalShell's dialogs are: out of any stacking context of the canvas.
  return typeof document === "undefined" ? menu : createPortal(menu, document.body);
}
