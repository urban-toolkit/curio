import React, { useEffect, useMemo, useState } from "react";
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
 * "Used in projects" section: one row per project that consumes the dataset,
 * linking to the dataflow and naming its consumer (downstream) nodes. Renders
 * nothing when the dataset isn't used anywhere.
 */
export const DatasetDataflowUsageSection: React.FC<{
  datasetId: string | undefined;
}> = ({ datasetId }) => {
  const usage = useDatasetDataflowUsage(datasetId);

  // One row per project id. The backend already emits one entry per project,
  // so a repeat would be a fault upstream - but the heading counts this list,
  // and a duplicate would have inflated the count as well as the rows.
  const rows = useMemo(() => {
    const byId = new Map<string, DatasetDataflowUsageRef>();
    for (const flow of usage) {
      if (!byId.has(flow.dataflowId)) byId.set(flow.dataflowId, flow);
    }
    return Array.from(byId.values());
  }, [usage]);

  // Two DIFFERENT projects can carry the same name, and a row showed nothing
  // but that name - so "Used in projects (2)" listed what looked like the same
  // project twice. Both rows were truthful and linked to different projects;
  // there was just nothing on screen to tell them apart. Disambiguate only the
  // names that actually collide, so the common case stays clean.
  const collidingNames = useMemo(() => {
    const counts = new Map<string, number>();
    for (const flow of rows) {
      const name = flow.dataflowName || "Untitled dataflow";
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return new Set(
      Array.from(counts.entries())
        .filter(([, count]) => count > 1)
        .map(([name]) => name),
    );
  }, [rows]);

  if (rows.length === 0) return null;

  return (
    <section className={styles.section} aria-label="Projects using this dataset">
      <p className={styles.label}>Used in projects ({rows.length})</p>
      <ul className={styles.list}>
        {rows.map((flow) => {
          const consumers = consumerLabel(flow);
          const name = flow.dataflowName || "Untitled dataflow";
          return (
            <li key={flow.dataflowId} className={styles.item}>
              <Link to={`/dataflow/${flow.dataflowId}`} className={styles.link}>
                {name}
              </Link>
              {collidingNames.has(name) ? (
                <span className={styles.disambiguator} title={flow.dataflowId}>
                  {flow.dataflowId.slice(0, 8)}
                </span>
              ) : null}
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
