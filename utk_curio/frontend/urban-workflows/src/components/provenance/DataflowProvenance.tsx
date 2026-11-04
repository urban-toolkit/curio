import React, { useCallback, useMemo, useState } from "react";
import { TrillGenerator } from "../../TrillGenerator";
import { useCode } from "../../hook/useCode";
import DataflowThumbnail from "../DataflowThumbnail";
import ConfirmDialog from "../ConfirmDialog";
import { withRegisteredCategories } from "../../utils/graphPreviewCategories";
import {
  type RecordedHistory,
  type RecordedVersion,
  serverVersionItems,
  versionCounts,
  versionItems,
} from "../../utils/dataflowVersions";
import { historyApi, type ServerVersion } from "../../api/historyApi";
import { type ServerHistory, useServerHistory } from "../../providers/history/serverHistory";
import { useServerVersions } from "../../providers/history/useHistoryReads";
import { useOptionalToastContext } from "../../providers/ToastProvider";
import shell from "../packages/publishing/CatalogDrawerShell.module.css";
import { ProvenanceHistory } from "./ProvenanceHistory";
import styles from "./ProvenanceHistory.module.css";

const VERSION_NOUN = ["version", "versions"] as const;
const NO_VERSIONS: ServerVersion[] = [];

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
 * canvas only from its own button.
 *
 * On a canvas bound to the dataflow's doc the versions are the server's, the
 * same for every tab of the owner and the editors: putting one back changes
 * every tab's canvas and is a version of its own, and the owner can clear the
 * history before a version. On a canvas bound to no doc they are the ones
 * recorded in this tab: the restore keeps the history, marks the dataflow
 * unsaved, and the next edit branches from the version put back.
 */
export function DataflowProvenance() {
  const server = useServerHistory();
  return server ? <ServerVersions server={server} /> : <BrowserVersions />;
}

function BrowserVersions() {
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

/** Who made *version*, when it was a person. */
function madeBy(version: ServerVersion | undefined): string | null {
  const by = version?.by;
  if (!by || by.agent) return null;
  return by.name || null;
}

function ServerVersions({ server }: { server: ServerHistory }) {
  const { data, error, reload } = useServerVersions(server);
  const toast = useOptionalToastContext();
  const [clearing, setClearing] = useState<string | null>(null);
  const versions = data?.versions ?? NO_VERSIONS;
  const items = useMemo(() => serverVersionItems(versions), [versions]);
  const byId = useMemo(() => new Map(versions.map((version) => [version.id, version])), [versions]);
  const tagOf = useMemo(() => new Map(items.map((item) => [item.id, item.tag])), [items]);

  if (error) return <div className={shell.empty}>{error}</div>;
  if (!data) return <div className={shell.empty}>Reading the history…</div>;

  const putBack = async (id: string) => {
    try {
      await server.whenKept();
      const { refused } = await historyApi.putBack(server.projectId, id);
      if (refused.length > 0) {
        toast?.showToast(
          `${refused.length === 1 ? "One node keeps" : `${refused.length} nodes keep`} the code someone wrote while this version was put back.`,
          "warning",
        );
      }
    } catch (failure) {
      toast?.showToast((failure as Error)?.message || "This version could not be put back.", "error");
    } finally {
      reload();
    }
  };

  const clear = async (id: string) => {
    setClearing(null);
    try {
      await historyApi.clearBefore(server.projectId, id);
      toast?.showToast(`The history before version ${tagOf.get(id) ?? ""} is cleared.`, "info");
    } catch (failure) {
      toast?.showToast((failure as Error)?.message || "The history could not be cleared.", "error");
    } finally {
      reload();
    }
  };

  const first = versions[0]?.id ?? null;
  const details = (id: string) => {
    const version = byId.get(id);
    const at = version?.at ? new Date(version.at) : null;
    const by = madeBy(version);
    return (
      <>
        <div className={styles.thumbnail}>
          <DataflowThumbnail preview={withRegisteredCategories(version?.preview)} />
        </div>
        {at ? (
          <p className={styles.detailLine}>
            Recorded {at.toLocaleString()}
            {by ? ` by ${by}` : ""}
          </p>
        ) : null}
        <p className={styles.detailLine}>{versionCounts(version?.preview)}</p>
        {id === data.head ? (
          <p className={styles.inUse}>On the canvas now</p>
        ) : (
          <button type="button" className={styles.restore} onClick={() => void putBack(id)}>
            Put this version on the canvas
          </button>
        )}
        {data.canClear && id !== first ? (
          <button type="button" className={styles.clear} onClick={() => setClearing(id)}>
            Clear history before this version
          </button>
        ) : null}
      </>
    );
  };

  return (
    <>
      <ProvenanceHistory
        items={items}
        currentId={data.head}
        noun={VERSION_NOUN}
        details={details}
        emptyText="No versions yet"
      />
      {clearing ? (
        <ConfirmDialog
          title={`Clear the history before version ${tagOf.get(clearing) ?? ""}?`}
          body="The versions before it go, with every run and edit made before it. The dataflow stays as it is, and so does this version and every one after it."
          confirmLabel="Clear history"
          cancelLabel="Keep it"
          destructive
          layer="overlay"
          onConfirm={() => void clear(clearing)}
          onCancel={() => setClearing(null)}
        />
      ) : null}
    </>
  );
}

export default DataflowProvenance;
