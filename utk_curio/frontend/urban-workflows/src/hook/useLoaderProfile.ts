import { useEffect, useMemo, useState } from "react";
import { useOptionalDatasetPalette } from "../providers/DatasetPaletteContext";
import { useFlowContext } from "../providers/FlowProvider";
import {
  artifactDataType,
  detectLoaderProfile,
  needsTypeProbe,
  type LoaderProfile,
} from "../services/datasetCatalog/loaderProfile";
import { journalDataTypeFor, requestTypeProbe } from "../services/datasetCatalog/loaderTypeProbe";

/** How long the canvas is left to settle before a background run is queued. */
const PROBE_SETTLE_MS = 1500;
/** How long the code must stay unchanged before the journal is read. */
const JOURNAL_DEBOUNCE_MS = 400;

export interface UseLoaderProfileOptions {
  nodeId: string;
  nodeType: string;
  /** The code in the node now (the editor's live buffer). */
  code: string;
  /** The node is a loader on the canvas; otherwise nothing is read or run. */
  enabled: boolean;
  /** A background run is allowed: the viewer can run nodes and no run is in flight. */
  canProbe: boolean;
  /** The template's declared output types (one type is evidence). */
  portTypes?: readonly string[];
  /** The node's own output state, so a finished run re-reads the journal. */
  outputCode?: string;
  /**
   * What the node itself recorded of the datasets it reads: the palette's
   * `datasetSource` and the drop's `appliedDatasets`. Read when the catalog has
   * not answered (or no longer lists the dataset), so the preview does not
   * wait on it to say what a palette-made loader reads.
   */
  nodeDatasets?: { datasetSource?: any; appliedDatasets?: Record<string, any> | null };
}

export interface LoaderProfileState {
  profile: LoaderProfile;
  /** A background run is finding the type. */
  detecting: boolean;
}

/**
 * A loader's profile with every piece of evidence the canvas has: the catalog
 * record, this tab's last artifact, the run journal for this exact code, the
 * template's ports, and, when all of those are silent, one background run.
 */
export function useLoaderProfile({
  nodeId,
  nodeType,
  code,
  enabled,
  canProbe,
  portTypes,
  outputCode,
  nodeDatasets,
}: UseLoaderProfileOptions): LoaderProfileState {
  const datasetsById = useOptionalDatasetPalette()?.datasetsById;
  const { outputs, projectId } = useFlowContext();

  const runDataType = useMemo(() => {
    const own = (outputs ?? []).find((o) => o.nodeId === nodeId);
    return own ? artifactDataType(own.output) : null;
  }, [outputs, nodeId]);

  const datasetSource = nodeDatasets?.datasetSource;
  const appliedDatasets = nodeDatasets?.appliedDatasets;
  const lookupDataset = useMemo(
    () => (id: string) => {
      const item = datasetsById?.get(id);
      if (item) return { title: item.title, format: item.format };
      if (datasetSource?.datasetId === id && datasetSource?.format) {
        return { title: datasetSource.title, format: datasetSource.format };
      }
      const applied = Object.values(appliedDatasets ?? {}).find(
        (d: any) => d && (d.datasetId === id || d.id === id),
      ) as any;
      return applied?.format ? { title: applied.title, format: applied.format } : undefined;
    },
    [datasetsById, datasetSource, appliedDatasets],
  );

  const portKey = (portTypes ?? []).join(",");
  const base = useMemo(
    () =>
      enabled
        ? detectLoaderProfile(code, { lookupDataset, runDataType, portTypes })
        : detectLoaderProfile(""),
    // portTypes is read through its key, so a new array of the same types is no change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [enabled, code, lookupDataset, runDataType, portKey],
  );

  // The journal: a successful run of exactly this code. Read again when the
  // node settles after a run, which writes a new record.
  const [journal, setJournal] = useState<{ code: string; dataType: string | null } | null>(null);
  const settled = outputCode === "success" || outputCode === "error";
  const wantsJournal = enabled && base.dataType === "unknown" && !!projectId;
  useEffect(() => {
    if (!wantsJournal) return;
    const controller = new AbortController();
    // Typing changes the code on every key: read once the edits pause.
    const timer = setTimeout(() => {
      void journalDataTypeFor(projectId as string, nodeId, code, controller.signal).then((dataType) => {
        if (!controller.signal.aborted) setJournal({ code, dataType });
      });
    }, JOURNAL_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [wantsJournal, projectId, nodeId, code, settled]);
  const journalDataType = journal && journal.code === code ? journal.dataType : null;
  const journalRead = !wantsJournal || (journal !== null && journal.code === code);

  const withJournal = useMemo(
    () =>
      journalDataType
        ? detectLoaderProfile(code, { lookupDataset, runDataType, portTypes, journalDataType })
        : base,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [base, journalDataType],
  );

  // The background run: only when everything above is silent, once per code.
  const [probe, setProbe] = useState<{ code: string; dataType: string | null } | null>(null);
  const [detecting, setDetecting] = useState(false);
  const wantsProbe = enabled && canProbe && journalRead && needsTypeProbe(withJournal);
  useEffect(() => {
    if (!wantsProbe) return;
    if (probe && probe.code === code) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setDetecting(true);
      void requestTypeProbe({ dataflowId: projectId, nodeId, nodeType, code }, controller.signal).then(
        (dataType) => {
          if (controller.signal.aborted) return;
          setProbe({ code, dataType });
          setDetecting(false);
        },
      );
    }, PROBE_SETTLE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
      setDetecting(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantsProbe, code, projectId, nodeId, nodeType]);
  const probeDataType = probe && probe.code === code ? probe.dataType : null;

  const profile = useMemo(
    () =>
      probeDataType && withJournal.dataType === "unknown"
        ? detectLoaderProfile(code, { lookupDataset, runDataType, portTypes, journalDataType, probeDataType })
        : withJournal,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [withJournal, probeDataType],
  );

  return { profile, detecting: detecting && profile.dataType === "unknown" };
}
