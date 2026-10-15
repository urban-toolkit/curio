import React from "react";

import { NodeCatalogDrawer } from "../../packages/publishing/NodeCatalogDrawer";
import type { PackageAddRequest } from "../../../services/packages/packageAddRequests";

export interface ModelCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
  /** The Add of the drop that opened the drawer (`ModelCatalogDrawerProvider`). */
  addRequest?: PackageAddRequest | null;
}

/**
 * The Model Catalog on the canvas: the Node Catalog drawer over model packages
 * (kind `model`). The same tabs (Browse all, In project), Add, Remove, Import,
 * details and restart notice, through the same packages service. A card
 * dropped on the canvas makes its model's node, as a Node Catalog card does
 * (through this drawer's Add when the dataflow does not have the model; a
 * drop with the drawer closed opens it on that Add), and dropped on a node it
 * swaps the node's model for one of the same type.
 */
export const ModelCatalogDrawer: React.FC<ModelCatalogDrawerProps> = (props) => (
  <NodeCatalogDrawer {...props} packageKind="model" />
);

export default ModelCatalogDrawer;
