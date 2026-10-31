/**
 * An invited editor's package or model of his own, asked of the dataflow's
 * owner (`collab/useAsk`): his Add to project in the Node or Model Catalog,
 * his Import package, a card he drops on her canvas, which makes its node at
 * once, and a model he drops on a node of hers each ask her. The answer says
 * when nothing needed asking: a package her dataflow uses already, or the
 * built-in one.
 *
 * Null on any canvas but an invited editor's: the owner adds the package
 * herself, and a watcher's canvas offers none of this.
 */
import { useCallback } from "react";

import { useAsk, type AskHow } from "../collab/useAsk";

/** A package or a model as an ask names it: its `<packageId>@<major>` and name. */
export interface AskedPackage {
  dirName: string;
  name: string;
}

export type AskForPackage = (pkg: AskedPackage, how?: AskHow) => Promise<boolean>;

export function useAskForPackage(): AskForPackage | null {
  const ask = useAsk("packages");
  const askForPackage = useCallback<AskForPackage>(
    (pkg, how) => ask!({ dirName: pkg.dirName }, pkg.name, how),
    [ask],
  );
  return ask ? askForPackage : null;
}
