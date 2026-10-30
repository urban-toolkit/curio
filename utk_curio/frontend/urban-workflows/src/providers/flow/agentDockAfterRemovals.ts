/**
 * A node or a connection removed takes the agents attached to it along. No
 * tab saves a dataflow its canvas is bound to, so no save prunes them: the
 * attachments' listing does, with their transcripts, once the server has the
 * removal. So after a removal the agent dock lists them again, when the
 * server has every change this tab made (or the wait gives up).
 */
import { notifyAgentDockRefresh } from "../../services/agents/agentEvents";

export function refreshAgentsWhenKept(whenKept: (() => Promise<unknown>) | undefined): Promise<void> {
    return Promise.resolve(whenKept?.()).then(
        () => notifyAgentDockRefresh(),
        () => notifyAgentDockRefresh(),
    );
}
