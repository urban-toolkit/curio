/**
 * The agents attached to the dataflow are kept beside its doc, so no change
 * of the doc tells this tab of them: the room does. When someone attaches an
 * agent to the dataflow or takes one off, the server tells the tabs of its
 * owner and editors (`ATTACHMENTS_CHANGED_EVENT`, `dataflow_docs.py`), and
 * this tab lists the agents again. A tab back in the room after a time away
 * lists them again too, as it may have missed what the room told meanwhile.
 */
import { useEffect, useRef } from "react";

import { useCollab } from "../CollaborationProvider";
import { ATTACHMENTS_CHANGED_EVENT } from "../collab/docContext";

/** List *projectId*'s agents again (*reload*) whenever the room says they
 *  changed, and when this tab joins the room again. */
export function useAttachmentsInTheRoom(projectId: string | null, reload: () => Promise<void>): void {
  const { onRemote, participantId } = useCollab();
  useEffect(() => {
    if (!projectId || typeof onRemote !== "function") return undefined;
    return onRemote(ATTACHMENTS_CHANGED_EVENT, (payload) => {
      if ((payload as { projectId?: unknown } | null)?.projectId === projectId) void reload();
    });
  }, [onRemote, projectId, reload]);

  // A tab away from the room has no id there: the join is the next id that
  // differs from the last one it had.
  const joinedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!participantId) return;
    const before = joinedRef.current;
    joinedRef.current = participantId;
    if (before && before !== participantId) void reload();
  }, [participantId, reload]);
}
