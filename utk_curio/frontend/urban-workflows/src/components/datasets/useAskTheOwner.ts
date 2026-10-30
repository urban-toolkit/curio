/**
 * An invited editor's dataset of his own, asked of the dataflow's owner.
 *
 * On the owner's dataflow an editor's tab writes neither her store nor her
 * dataflow's datasets: a file he drops goes into his own Data Catalog, and
 * that file, his Add to project and a card of his catalog he drags onto her
 * canvas or a node each ask her instead (`collab/useAsk`). A collection of
 * his asks as a dataset does. The answer says when nothing needed asking: a
 * dataset her dataflow lists already, or, for a drop, one of the shared
 * catalog, which every account's runs read.
 *
 * Null on any canvas but an invited editor's: the owner adds the dataset
 * herself, and a watcher's canvas offers none of this.
 */
import { useCallback } from "react";

import { useAsk, type AskHow } from "../collab/useAsk";

/** A dataset as an ask names it: a catalog item's id or a drag's. */
export interface AskedDataset {
  id?: string;
  datasetId?: string;
  title: string;
}

export type AskTheOwner = (dataset: AskedDataset, how?: AskHow) => Promise<boolean>;

export function useAskTheOwner(): AskTheOwner | null {
  const ask = useAsk("datasets");
  const askForDataset = useCallback<AskTheOwner>(
    (dataset, how) => ask!({ datasetId: dataset.datasetId ?? dataset.id }, dataset.title, how),
    [ask],
  );
  return ask ? askForDataset : null;
}
