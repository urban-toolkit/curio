import React, { useCallback, useState } from "react";
import { TrillGenerator } from "../../TrillGenerator";
import { useCode } from "../../hook/useCode";
import DataflowThumbnail from "../DataflowThumbnail";
import { withRegisteredCategories } from "../../utils/graphPreviewCategories";
import {
  type RecordedHistory,
  type RecordedVersion,
  versionCounts,
  versionItems,
} from "../../utils/dataflowVersions";
import { ProvenanceHistory } from "./ProvenanceHistory";
import styles from "./ProvenanceHistory.module.css";

const VERSION_NOUN = ["version", "versions"] as const;

/** What `TrillGenerator` holds now. It is not React state, so the history is
 *  read when the drawer opens and again after a restore. */
function readHistory() {
  const graph = TrillGenerator.provenanceJSON as RecordedHistory;
  return {
    items: versionItems(graph),
    versions: new Map<string, RecordedVersion>((graph?.nodes ?? []).map((version) => [version.id, version])),
  };
}

/**
 * The dataflow's versions in the provenance drawer. An opened version shows
 * its thumbnail, when it was recorded and its size, and puts itself on the
 * canvas only from its own button: the restore keeps the history, marks the
 * dataflow unsaved, and the next edit branches from the version put back.
 */
export function DataflowProvenance() {
  const { loadTrill } = useCode();
  const [history, setHistory] = useState(readHistory);
  const [currentId, setCurrentId] = useState<string | null>(() => TrillGenerator.latestTrill || null);

  const restore = useCallback(
    (id: string) => {
      TrillGenerator.switchProvenanceTrill(id, loadTrill);
      setCurrentId(TrillGenerator.latestTrill || null);
      setHistory(readHistory());
    },
    [loadTrill],
  );

  const details = (id: string) => {
    const version = history.versions.get(id);
    const at = version?.timestamp ? new Date(version.timestamp) : null;
    return (
      <>
        <div className={styles.thumbnail}>
          <DataflowThumbnail preview={withRegisteredCategories(version?.preview)} />
        </div>
        {at ? <p className={styles.detailLine}>Recorded {at.toLocaleString()}</p> : null}
        <p className={styles.detailLine}>{versionCounts(version?.preview)}</p>
        {id === currentId ? (
          <p className={styles.inUse}>On the canvas now</p>
        ) : (
          <button type="button" className={styles.restore} onClick={() => restore(id)}>
            Put this version on the canvas
          </button>
        )}
      </>
    );
  };

  return (
    <ProvenanceHistory
      items={history.items}
      currentId={currentId}
      noun={VERSION_NOUN}
      details={details}
      emptyText="No versions yet"
    />
  );
}

export default DataflowProvenance;
