import React from "react";
import { useParams } from "react-router-dom";

import { NodeCatalogBrowse } from "../catalog/NodeCatalogBrowse";

/**
 * The account-scope Model Catalog under `/catalog/models`: the Node Catalog
 * page over model packages (kind `model`), with the same rail, header import,
 * cards, side drawer, Add to all projects and details modal, through the same
 * packages service. `/catalog/models/<id>` is this page with that model's
 * details open.
 */
export const ModelCatalogBrowse: React.FC = () => {
  const { modelId } = useParams<{ modelId?: string }>();
  return (
    <NodeCatalogBrowse
      packageKind="model"
      linkedPackageId={modelId ? decodeURIComponent(modelId) : undefined}
    />
  );
};

export default ModelCatalogBrowse;
