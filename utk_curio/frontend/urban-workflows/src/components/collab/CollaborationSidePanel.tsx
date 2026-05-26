/**
 * Collapsible right-docked panel that surfaces real-time collaboration
 * state — connected users, pending code-change proposals, and a recent
 * activity feed.
 *
 * Renders nothing when ``--collab`` is off; the caller is expected to
 * mount it inside ``MainCanvas`` only when ``collab.enabled`` is true.
 */

import React from "react";

import { useCollab } from "../../providers/CollaborationProvider";

const PANEL_WIDTH = 260;

export const CollaborationSidePanel: React.FC = () => {
    const collab = useCollab();

    // Visibility is gated on the panelOpen flag in CollaborationProvider —
    // toggled by the trigger button next to Urbanite in the UpMenu.
    if (!collab.enabled || !collab.panelOpen) return null;

    return (
        <div
            style={{
                position: "absolute",
                top: 60,
                right: 0,
                zIndex: 20,
                display: "flex",
                alignItems: "flex-start",
                pointerEvents: "none",
            }}
        >
            <div
                    style={{
                        pointerEvents: "auto",
                        width: PANEL_WIDTH,
                        maxHeight: "calc(100vh - 80px)",
                        overflowY: "auto",
                        background: "#fafafa",
                        borderLeft: "1px solid #ddd",
                        boxShadow: "-2px 0 6px rgba(0,0,0,0.08)",
                        fontSize: 12,
                        padding: 8,
                        display: "flex",
                        flexDirection: "column",
                        gap: 12,
                    }}
                >
                    <Section title={`Users (${collab.users.length})`}>
                        {collab.users.length === 0 ? (
                            <Empty>Nobody else is here.</Empty>
                        ) : (
                            collab.users.map((u) => (
                                <Row key={u.sid || u.user_id}>
                                    <Avatar name={u.name || u.username} />
                                    <span>{u.name || u.username}</span>
                                </Row>
                            ))
                        )}
                    </Section>

                    <Section title={`Proposals (${collab.proposals.length})`}>
                        {collab.proposals.length === 0 ? (
                            <Empty>No pending changes.</Empty>
                        ) : (
                            collab.proposals.map((p) => {
                                const mine =
                                    collab.currentUserId != null &&
                                    p.proposed_by?.user_id === collab.currentUserId;
                                return (
                                    <div
                                        key={p.id}
                                        style={{
                                            background: "#fff",
                                            border: "1px solid #e0e0e0",
                                            borderRadius: 4,
                                            padding: 6,
                                            display: "flex",
                                            flexDirection: "column",
                                            gap: 4,
                                        }}
                                    >
                                        <div style={{ fontWeight: 600 }}>
                                            {p.kind === "grammar" ? "Grammar" : "Code"} change ·{" "}
                                            <span style={{ color: "#666", fontWeight: 400 }}>
                                                {p.nodeId.slice(0, 8)}
                                            </span>
                                        </div>
                                        <div style={{ color: "#666", fontSize: 11 }}>
                                            by {p.proposed_by?.username || "?"} ·{" "}
                                            {p.approvals.length} approval(s)
                                        </div>
                                        {!mine && (
                                            <div style={{ display: "flex", gap: 4 }}>
                                                <button
                                                    type="button"
                                                    onClick={() => collab.approveCodeChange(p.id)}
                                                    style={{ flex: 1, padding: "2px 4px", fontSize: 11 }}
                                                >
                                                    Approve
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => collab.rejectCodeChange(p.id)}
                                                    style={{ flex: 1, padding: "2px 4px", fontSize: 11 }}
                                                >
                                                    Reject
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })
                        )}
                    </Section>

                    <Section title={`Activity (${collab.activity.length})`}>
                        {collab.activity.length === 0 ? (
                            <Empty>No activity yet.</Empty>
                        ) : (
                            collab.activity.slice(-20).reverse().map((a, i) => (
                                <Row key={i}>
                                    <span style={{ color: "#666" }}>
                                        {a.kind.replace(/_/g, " ")}
                                    </span>
                                </Row>
                            ))
                        )}
                    </Section>
                </div>
        </div>
    );
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({
    title,
    children,
}) => (
    <div>
        <div
            style={{
                fontWeight: 700,
                fontSize: 11,
                color: "#666",
                textTransform: "uppercase",
                letterSpacing: 0.5,
                marginBottom: 4,
            }}
        >
            {title}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {children}
        </div>
    </div>
);

const Row: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>{children}</div>
);

const Empty: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <span style={{ color: "#999", fontStyle: "italic" }}>{children}</span>
);

const Avatar: React.FC<{ name: string }> = ({ name }) => (
    <span
        style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 22,
            height: 22,
            borderRadius: "50%",
            background: "#1976d2",
            color: "#fff",
            fontSize: 10,
            fontWeight: 700,
        }}
    >
        {(name || "?").slice(0, 2).toUpperCase()}
    </span>
);
