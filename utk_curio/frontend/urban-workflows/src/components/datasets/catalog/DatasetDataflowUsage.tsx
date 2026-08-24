import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  DatasetDataflowUsageRef,
  datasetCatalogApi,
} from "../../../services/datasetCatalog";
import { formatNodeTypeLabel } from "../../../services/datasetLineage";
import styles from "./DatasetDataflowUsage.module.css";

/**
 * Cross-dataflow usage from the backend (``GET /datasets/<id>/usage``).
 *
 * Unlike the live-canvas lineage, this works on canvas-less surfaces — the
 * standalone catalog detail page and the browse drawer — so a dataset shows the
 * dataflows that consume it with links and the consumer node names. Returns an
 * empty list when the dataset isn't used anywhere (or while loading).
 */
export function useDatasetDataflowUsage(
  datasetId: string | undefined,
): DatasetDataflowUsageRef[] {
  const [usage, setUsage] = useState<DatasetDataflowUsageRef[]>([]);
  useEffect(() => {
    if (!datasetId) {
      setUsage([]);
      return;
    }
    let cancelled = false;
    datasetCatalogApi
      .datasetUsage(datasetId)
      .then((rows) => {
        if (!cancelled) setUsage(rows);
      })
      .catch(() => {
        if (!cancelled) setUsage([]);
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);
  return usage;
}

function consumerLabel(flow: DatasetDataflowUsageRef): string | null {
  const nodes = flow.nodes ?? [];
  if (nodes.length > 0) {
    return nodes.map((node) => formatNodeTypeLabel(node.nodeType ?? undefined)).join(", ");
  }
  if (flow.nodeCount > 0) {
    return `${flow.nodeCount} ${flow.nodeCount === 1 ? "node" : "nodes"}`;
  }
  return null;
}

/**
 * "Used in dataflows" section: one row per dataflow that consumes the dataset,
 * linking to the dataflow and naming its consumer (downstream) nodes. Renders
 * nothing when the dataset isn't used anywhere.
 */
export const DatasetDataflowUsageSection: React.FC<{
  datasetId: string | undefined;
}> = ({ datasetId }) => {
  const usage = useDatasetDataflowUsage(datasetId);
  if (usage.length === 0) return null;

  return (
    <section className={styles.section} aria-label="Dataflows using this dataset">
      <p className={styles.label}>Used in dataflows ({usage.length})</p>
      <ul className={styles.list}>
        {usage.map((flow) => {
          const consumers = consumerLabel(flow);
          return (
            <li key={flow.dataflowId} className={styles.item}>
              <Link to={`/dataflow/${flow.dataflowId}`} className={styles.link}>
                {flow.dataflowName || "Untitled dataflow"}
              </Link>
              {consumers ? (
                <span className={styles.consumers}>Consumed by {consumers}</span>
              ) : (
                <span className={styles.consumers}>Produced here</span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
};
