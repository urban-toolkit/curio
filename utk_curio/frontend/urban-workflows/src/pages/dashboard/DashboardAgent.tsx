// The dashboard agent: a chat beside the tiles that sets their widgets and
// runs the dataflow.
//
// The page sends the pinned tiles' widgets (`dashboardControls`) with each
// message; the backend's one model turn answers with a reply, the changes it
// makes and whether to run (`agents/application/dashboard_chat.py`). A change
// is written as a widget change is (the node's widgets, then the node and the
// nodes that read a shared value go stale), and a run is the Run button's own
// Run All, started once React has committed the new values. The transcript
// lives here only: like a run from this page, nothing of it is saved.
//
// The LLM is the viewer's own. Without one, the panel says so and opens API
// Settings to add one, and a refusal from the backend does the same. It opens
// the drawer itself: a dashboard page is served with its data inside it, and
// such a page's header mounts no ApiSettingsRequestHost, so a request sent as
// an event (`requestAgentModel`) would reach nothing.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useReactFlow } from "reactflow";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPaperPlane, faXmark } from "@fortawesome/free-solid-svg-icons";

import { dashboardAgentApi, type DashboardChatTurn } from "../../api/dashboardAgentApi";
import { llmConfigsApi } from "../../api/llmConfigsApi";
import { settingsPath, type ApiSettingsFocus } from "../../components/apiSettings/apiSettingsRequest";
import { useApiSettingsDrawerOptional } from "../../providers/ApiSettingsDrawerProvider";
import { useFlowContext } from "../../providers/FlowProvider";
import {
  applyAgentChanges,
  dashboardControls,
  formatValue,
  type AgentControl,
} from "../../utils/dashboardAgent";
import { isParameterNode, nodesUsingShared } from "../../utils/references/sharedParameters";
import styles from "./DashboardAgent.module.css";

interface Entry extends DashboardChatTurn {
  /** What the turn did: the values it changed, what it skipped, the run. */
  notes?: string[];
  error?: boolean;
}

type LlmState = "checking" | "ready" | "missing" | "unknown";

/** The earlier turns the backend reads, as plain text. */
const HISTORY_TURNS = 20;

const EMPTY_HINT =
  "Ask me to change any widget on this dashboard, one or several at once, and to run it. "
  + "For example: “set the season to winter in the Baseline scenario and rerun”.";

export function DashboardAgent({ canRun, onClose }: { canRun: boolean; onClose: () => void }) {
  const reactFlow = useReactFlow();
  const settingsDrawer = useApiSettingsDrawerOptional();
  const openLlmSettings = () => {
    const focus: ApiSettingsFocus = { section: "llm-configs" };
    if (settingsDrawer) settingsDrawer.openApiSettings(focus);
    // No drawer here: the settings page, in a tab of its own so the dashboard stays.
    else window.open(settingsPath(focus), "_blank", "noopener");
  };
  const {
    dashboardPins,
    scenarios,
    updateDataNode,
    markNodeStale,
    markDirty,
    playAllNodes,
    isRunActive,
    serverRunActive,
  } = useFlowContext();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [llm, setLlm] = useState<LlmState>("checking");
  const listRef = useRef<HTMLDivElement>(null);
  // Run All as it is when the run starts, after the changes have rendered.
  const playAllRef = useRef(playAllNodes);
  playAllRef.current = playAllNodes;
  const runningRef = useRef(false);
  runningRef.current = Boolean(isRunActive || serverRunActive);

  const checkLlm = useCallback(() => {
    setLlm("checking");
    llmConfigsApi
      .listing()
      .then((listing) => {
        // Any configuration will do: the agent runs on the default, else the
        // first one added (agents/application/dashboard_chat.py).
        if (listing.active?.source || listing.configs.length > 0) {
          setLlm("ready");
        } else {
          setLlm("missing");
        }
      })
      // The listing could not be read: let the backend answer, and refuse if it must.
      .catch(() => setLlm("unknown"));
  }, []);

  useEffect(() => {
    checkLlm();
    // Back from API Settings, the configuration may be there now.
    const onFocus = () => checkLlm();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [checkLlm]);

  // Closing the drawer after adding a configuration: ask again.
  const drawerOpen = Boolean(settingsDrawer?.isApiSettingsOpen);
  const wasDrawerOpen = useRef(drawerOpen);
  useEffect(() => {
    if (wasDrawerOpen.current && !drawerOpen) checkLlm();
    wasDrawerOpen.current = drawerOpen;
  }, [drawerOpen, checkLlm]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [entries, busy]);

  const apply = (controls: AgentControl[], changes: { id: string; value: any }[]): string[] => {
    const live = reactFlow.getNodes();
    const { widgetsByNode, applied, skipped } = applyAgentChanges(live, controls, changes);
    for (const [nodeId, widgets] of widgetsByNode) {
      const node = reactFlow.getNode(nodeId);
      if (!node) continue;
      updateDataNode(nodeId, { ...node.data, widgets });
      markNodeStale?.(nodeId);
      // A Parameter node's value is read by every node that names it.
      if (isParameterNode(node)) {
        for (const change of applied.filter((a) => a.nodeId === nodeId)) {
          const name = controls.find((c) => c.id === change.id)?.name;
          if (!name) continue;
          for (const user of nodesUsingShared(live, name)) markNodeStale?.(user.id);
        }
      }
    }
    if (widgetsByNode.size > 0) markDirty?.();
    return [
      ...applied.map((a) => `${a.label}${a.scenario ? ` (${a.scenario})` : ""}: ${formatValue(a.from)} → ${formatValue(a.to)}`),
      ...skipped.map((s) => `Not changed, ${controls.find((c) => c.id === s.id)?.label ?? s.id}: ${s.problem}`),
    ];
  };

  const startRun = (): string => {
    if (runningRef.current) return "A run is already going; ask again when it ends.";
    // After React commits the new widget values: Run All reads the graph as it is.
    requestAnimationFrame(() => requestAnimationFrame(() => playAllRef.current()));
    return "Running the dataflow…";
  };

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    const history = entries
      .filter((e) => !e.error)
      .slice(-HISTORY_TURNS)
      .map(({ role, content }) => ({ role, content }));
    setEntries((prev) => [...prev, { role: "user", content: message }]);
    setInput("");
    setBusy(true);
    const controls = dashboardControls(reactFlow.getNodes(), dashboardPins ?? {}, scenarios ?? []);
    try {
      const answer = await dashboardAgentApi.turn({
        message,
        history,
        controls: controls.map(({ nodeId: _nodeId, ...control }) => control),
        scenarios: (scenarios ?? []).map((s) => s.name),
        canRun,
      });
      const notes = answer.needsClarification ? [] : apply(controls, answer.changes);
      for (const rejected of answer.rejected) {
        notes.push(`Not changed, ${controls.find((c) => c.id === rejected.id)?.label ?? rejected.id}: ${rejected.problem}`);
      }
      if (answer.run) notes.push(startRun());
      setEntries((prev) => [...prev, { role: "assistant", content: answer.reply, notes }]);
    } catch (err) {
      const remedy = (err as { body?: { remedy?: { kind?: string } } })?.body?.remedy;
      if (remedy?.kind === "llm-config") {
        setLlm("missing");
      }
      setEntries((prev) => [
        ...prev,
        { role: "assistant", content: (err as Error)?.message || "The agent did not answer.", error: true },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const blocked = llm === "missing";

  return (
    <aside className={`${styles.panel} nowheel nodrag`} aria-label="Dashboard agent" data-testid="dashboard-agent">
      <header className={styles.header}>
        <span className={styles.title}>Agent</span>
        <button type="button" className={styles.close} onClick={onClose} aria-label="Close the agent">
          <FontAwesomeIcon icon={faXmark} />
        </button>
      </header>

      {blocked ? (
        <div className={styles.setup} data-testid="dashboard-agent-setup">
          <span className={styles.setupTitle}>Set up an LLM to use the agent.</span>
          <span>{"Add an LLM configuration in API Settings, then close it to start chatting. The agent runs on your own configuration."}</span>
          <div className={styles.setupActions}>
            <button type="button" className={styles.primary} onClick={openLlmSettings}>
              Open API Settings
            </button>
            <button type="button" className={styles.secondary} onClick={checkLlm}>
              Check again
            </button>
          </div>
        </div>
      ) : (
        <div className={styles.list} ref={listRef}>
          {entries.length === 0 ? <p className={styles.hint}>{EMPTY_HINT}</p> : null}
          {entries.map((entry, index) => (
            <div
              key={index}
              className={`${styles.entry} ${entry.role === "user" ? styles.user : styles.assistant} ${entry.error ? styles.error : ""}`}
            >
              <span>{entry.content}</span>
              {entry.notes && entry.notes.length > 0 ? (
                <ul className={styles.notes}>
                  {entry.notes.map((note, i) => <li key={i}>{note}</li>)}
                </ul>
              ) : null}
            </div>
          ))}
          {busy ? <div className={`${styles.entry} ${styles.assistant} ${styles.pending}`}>Thinking…</div> : null}
        </div>
      )}

      <form
        className={styles.composer}
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <textarea
          className={styles.input}
          value={input}
          disabled={blocked || busy || llm === "checking"}
          placeholder={blocked ? "Set up an LLM first" : "Change a widget, or ask to run…"}
          rows={2}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
          data-testid="dashboard-agent-input"
        />
        <button
          type="submit"
          className={styles.send}
          disabled={blocked || busy || !input.trim() || llm === "checking"}
          aria-label="Send"
        >
          <FontAwesomeIcon icon={faPaperPlane} />
        </button>
      </form>
    </aside>
  );
}

export default DashboardAgent;
