import React from "react";

import { NodeCatalogDrawer } from "../../packages/publishing/NodeCatalogDrawer";

export interface ModelCatalogDrawerProps {
  presented: boolean;
  onRequestClose: () => void;
  onExitComplete: () => void;
}

/**
 * The Model Catalog on the canvas: the Node Catalog drawer over model packages
 * (kind `model`). The same tabs (Browse all, In project), Add, Remove, Import,
 * details and restart notice, through the same packages service; a card is
 * also a model to drag onto a node that runs one.
 */
export const ModelCatalogDrawer: React.FC<ModelCatalogDrawerProps> = (props) => (
  <NodeCatalogDrawer {...props} packageKind="model" />
);

export default ModelCatalogDrawer;
