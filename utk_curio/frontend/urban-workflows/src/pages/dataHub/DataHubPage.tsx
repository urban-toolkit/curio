import React from "react";
import { Navigate, useParams } from "react-router-dom";

/**
 * Legacy route: `/data-hub` and `/data-hub/:datasetId` redirect to the catalog
 * master Data tab (`/catalog/data`).
 */
export default function DataHubPage() {
  const { datasetId } = useParams<{ datasetId?: string }>();
  if (datasetId) {
    return <Navigate to={`/catalog/data/${encodeURIComponent(datasetId)}`} replace />;
  }
  return <Navigate to="/catalog/data" replace />;
}
