import React from "react";

import {
  acquireKey,
  declaredResourceFor,
  downloadBody,
  isServiceSource,
  isStorageSource,
  type DiscoveryAcquireBody,
  type DiscoveryResource,
  type DiscoverySourceRow,
  type UseDiscoveryAcquireResult,
} from "../../services/discoveryCatalog";
import { DiscoveryResourceRow } from "./DiscoveryResourceRow";

export interface DiscoveryFederatedRowsProps {
  resources: DiscoveryResource[];
  /** The roster, by source id: a federated row carries only the source id. */
  sourcesById: Map<string, DiscoverySourceRow>;
  acquisition: UseDiscoveryAcquireResult;
  onViewDataset: (datasetId: string) => void;
  onViewModel?: (modelId: string) => void;
}

/**
 * One search across every source: a row per resource, tagged with the
 * source it came from, because across sources that is not implied. Shared by
 * the browse page and the canvas drawer.
 */
export function DiscoveryFederatedRows({
  resources,
  sourcesById,
  acquisition,
  onViewDataset,
  onViewModel,
}: DiscoveryFederatedRowsProps) {
  // A storage source's rows are added rather than downloaded, and can be
  // narrowed or opened file by file.
  const storageContext = (source: DiscoverySourceRow | undefined, resourceId: string) =>
    source && isStorageSource(source)
      ? {
          dirName: source.dirName,
          declared: declaredResourceFor(source, resourceId),
          onAdd: (r: { resourceId: string }, body: DiscoveryAcquireBody) =>
            void acquisition.start(source.dirName, r.resourceId, body),
        }
      : undefined;

  return (
    <>
      {resources.map((resource) => {
        const source = sourcesById.get(resource.sourceId);
        // The API wants the versioned dirName, which only the roster knows.
        const dir = source?.dirName;
        return (
          <DiscoveryResourceRow
            key={`${resource.sourceId}:${resource.resourceId}`}
            resource={resource}
            showSource
            iconUrl={source?.iconUrl ?? null}
            job={acquisition.jobs[acquireKey(dir ?? resource.sourceId, resource.resourceId)]}
            onViewDataset={onViewDataset}
            onViewModel={onViewModel}
            storage={storageContext(source, resource.resourceId)}
            service={isServiceSource(source ?? { kind: "portal" })}
            onDownload={(r, fmt, parameters, title) => {
              if (source)
                void acquisition.start(
                  source.dirName,
                  r.resourceId,
                  downloadBody(source, r, fmt, parameters, title),
                );
            }}
            onCancel={(r) => {
              if (dir) acquisition.cancel(dir, r.resourceId);
            }}
            onDismiss={(r) => {
              if (dir) acquisition.dismiss(dir, r.resourceId);
            }}
          />
        );
      })}
    </>
  );
}
