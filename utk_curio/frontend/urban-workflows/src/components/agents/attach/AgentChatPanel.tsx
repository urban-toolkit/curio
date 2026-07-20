import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentAttachment } from "../../../api/agentsApi";
import styles from "./AgentDock.module.css";

type Turn = { role: "user" | "agent"; text: string };

/**
 * Chat panel for one attached agent. Each send runs the agent (one turn) via the
 * provided ``onSend`` and appends the reply. History is in-memory for now
 * (backend run is stateless single-turn; persistent sessions are a follow-up).
 */
export const AgentChatPanel: React.FC<{
  attachment: AgentAttachment;
  onSend: (message: string) => Promise<string>;
  onClose: () => void;
}> = ({ attachment, onSend, onClose }) => {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  const targetLabel =
    attachment.target.kind === "canvas"
      ? "canvas"
      : `${attachment.target.kind} · ${attachment.target.targetId ?? ""}`;

  const send = async () => {
    const message = input.trim();
    if (!message || sending) return;
    setTurns((t) => [...t, { role: "user", text: message }]);
    setInput("");
    setSending(true);
    try {
      const reply = await onSend(message);
      setTurns((t) => [...t, { role: "agent", text: reply }]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "run failed";
      setTurns((t) => [...t, { role: "agent", text: `(error) ${msg}` }]);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className={styles.panel} role="dialog" aria-label={`Chat with ${attachment.name}`}>
      <div className={styles.panelHeader}>
        <FontAwesomeIcon icon={faRobot} />
        <span className={styles.panelTitle}>{attachment.name}</span>
        <span className={styles.panelTarget}>{targetLabel}</span>
        <button type="button" className={styles.panelClose} aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className={styles.messages}>
        {turns.length === 0 ? (
          <div className={styles.empty}>Ask this agent something to get started.</div>
        ) : (
          turns.map((t, i) => (
            <div key={i} className={t.role === "user" ? styles.msgUser : styles.msgAgent}>
              {t.text}
            </div>
          ))
        )}
      </div>

      <div className={styles.inputRow}>
        <input
          className={styles.input}
          value={input}
          placeholder="Message this agent…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button type="button" className={styles.send} disabled={sending || !input.trim()} onClick={send}>
          {sending ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
};
