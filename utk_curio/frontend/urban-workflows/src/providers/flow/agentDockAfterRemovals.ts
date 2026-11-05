/**
 * A node or a connection removed takes the agents attached to it along. No
 * tab saves a dataflow its canvas is bound to, so no save prunes them: the
 * attachments' listing does, with their transcripts, once the server has the
 * removal. So after a removal the agent dock lists them again, when the
 * server has every change this tab made (or the wait gives up).
 *
 * The wait starts once the canvas has drawn the removal (`useOnceDrawn`):
 * the write that sends it to the server runs after that draw
 * (`useDataflowDoc`). A wait started before writes the canvas as it still
 * is: it finds nothing of this tab's to wait for, so the dock asks before
 * the server has the removal, and on another tab's removal it diffs a canvas
 * that still draws what the doc took out.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { notifyAgentDockRefresh } from "../../services/agents/agentEvents";

export function refreshAgentsWhenKept(whenKept: (() => Promise<unknown>) | undefined): Promise<void> {
    return Promise.resolve(whenKept?.()).then(
        () => notifyAgentDockRefresh(),
        () => notifyAgentDockRefresh(),
    );
}

/** Run *then* once React has drawn the changes made with the call, after the
 *  layout effects of that render. Asked again before that draw, only the last
 *  *then* runs. */
export function useOnceDrawn(): (then: () => void) => void {
    const dueRef = useRef<(() => void) | null>(null);
    const [asked, setAsked] = useState(0);
    useEffect(() => {
        const due = dueRef.current;
        dueRef.current = null;
        due?.();
    }, [asked]);
    return useCallback((then: () => void) => {
        dueRef.current = then;
        setAsked((count) => count + 1);
    }, []);
}
