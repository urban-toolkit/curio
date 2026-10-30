import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import type { XYPosition } from "reactflow";

import { CardContextMenu } from "../catalog/CardContextMenu";
import { holdModalStack } from "../ModalShell";
import {
  guestAddRefusal,
  packageDropAction,
  requestPackageAdd,
  type PackageAddRequest,
} from "../../services/packages/packageAddRequests";
import type { PackageCardDragPayload, PackageCardNode } from "../../services/packages/packageCardDrag";
import type { ToastVariant } from "../../providers/ToastProvider";
import type { AskForPackage } from "../collab/useAskTheOwner";

/**
 * A package's card dropped on the canvas from the Node Catalog drawer, or a
 * model's from the Model Catalog drawer (a model package has one node).
 *
 * A hosted guest's drop of a package the dataflow has not added is refused
 * first, before any menu: guests never install. Otherwise a package with one
 * node makes it, and a package with several offers them in a menu at the drop
 * point, Curio's one dark pop-up menu (`CardContextMenu`); the node picked is
 * made. Escape or a click outside makes none. A package the dataflow has not
 * added goes through the open drawer's own Add first (the review, then the
 * install of its libraries), and the node is made once it is added. A row of
 * the Tools panel's Models dropdown is a model the dataflow has, so it makes
 * its node at once. On the owner's dataflow an invited editor's drop
 * (*askTheOwner*) makes the node at once and asks her to add the package: the
 * node waits for her review (`editorRequests.ts`).
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
  /** Make *node* at *position*; the node made, by its id. */
  createNode: (node: PackageCardNode, position: XYPosition) => string | undefined | void;
  showToast: (message: string, variant?: ToastVariant) => void;
  /** On the owner's dataflow, an invited editor's ask of a package of his: set on his canvas alone. */
  askTheOwner?: AskForPackage | null;
}

/** A drop of a card of a package with several nodes, waiting for a pick. */
interface PendingPick extends PackageCardDrop {
  action: "create" | "add" | "ask";
}

export function usePackageCardDrop({
  dataflowPackages,
  hostedGuest,
  createNode,
  showToast,
  askTheOwner = null,
}: PackageCardDropOptions): { drop: (dropped: PackageCardDrop) => void; menu: React.ReactNode } {
  const [pending, setPending] = useState<PendingPick | null>(null);

  const make = useCallback(
    (action: PendingPick["action"], card: PackageCardDragPayload, node: PackageCardNode, position: XYPosition) => {
      if (action === "create") {
        createNode(node, position);
        return;
      }
      if (action === "ask") {
        const nodeId = createNode(node, position);
        void askTheOwner?.({ dirName: card.dirName, name: card.name }, nodeId ? { nodeId } : {});
        return;
      }
      const request: PackageAddRequest = {
        dirName: card.dirName,
        kind: card.kind,
        onAdded: () => createNode(node, position),
      };
      if (requestPackageAdd(request)) return;
      const catalog = card.kind === "model" ? "Model Catalog" : "Node Catalog";
      showToast(`Add ${card.name} to this dataflow from the ${catalog} first.`, "warning");
    },
    [createNode, showToast, askTheOwner],
  );

  const drop = useCallback(
    (dropped: PackageCardDrop) => {
      const { card, position } = dropped;
      const action = packageDropAction({
        inDataflow: (dataflowPackages ?? []).includes(card.dirName),
        hostedGuest,
        asksTheOwner: !!askTheOwner,
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
    [dataflowPackages, hostedGuest, showToast, make, askTheOwner],
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
