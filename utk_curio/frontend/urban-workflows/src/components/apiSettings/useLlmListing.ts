import { useCallback, useEffect, useState } from "react";
import { llmConfigsApi, type LlmListing } from "../../api/llmConfigsApi";

export interface LlmListingState {
  listing: LlmListing | null;
  loadError: string | null;
  /** The key of the action running now, such as `remove:<id>`. */
  busy: string | null;
  error: string | null;
  /** Run one change, then read the listing again; a failure lands in `error`. */
  act: (key: string, run: () => Promise<unknown>) => Promise<void>;
}

/**
 * The account's LLM configurations, the default and each agent's choice, read
 * once for both tabs of API Settings: the API keys tab lists and edits the
 * configurations, the Agent configuration tab chooses among them.
 */
export function useLlmListing(): LlmListingState {
  const [listing, setListing] = useState<LlmListing | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setListing(await llmConfigsApi.listing());
      setLoadError(null);
    } catch (e: any) {
      setLoadError(e?.message || "Could not load your LLM configurations.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = useCallback(
    async (key: string, run: () => Promise<unknown>) => {
      setBusy(key);
      setError(null);
      try {
        await run();
        await load();
      } catch (e: any) {
        setError(e?.message || "That did not work.");
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  return { listing, loadError, busy, error, act };
}
