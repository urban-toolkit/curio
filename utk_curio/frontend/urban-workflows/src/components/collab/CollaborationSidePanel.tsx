/**
 * Collapsible right-docked panel that surfaces real-time collaboration
 * state: connected users with their roles, and a recent activity feed.
 * ``CanvasSidePanels`` places it on the canvas's right edge, under the top
 * bar. Code is typed together in the node's editor, with no vote.
 *
 * Renders nothing when ``--collab`` is off or the panel is closed.
 */

import React from "react";

import { useCollab } from "../../providers/CollaborationProvider";

const PANEL_WIDTH = 260;

export const CollaborationSidePanel: React.FC = () => {
    const collab = useCollab();

    // Visibility is gated on the panelOpen flag in CollaborationProvider —
    // toggled by the 👥 trigger button in the UpMenu.
    if (!collab.enabled || !collab.panelOpen) return null;

    // Placed, and given its share of the height, by CanvasSidePanels.
    return (
        <div
            style={{
                width: PANEL_WIDTH,
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
                        <Row key={u.participant_id || u.user_id}>
                            <Avatar name={u.name || u.username} />
                            <span>{u.name || u.username}</span>
                            {u.role && (
                                <span style={{ color: "#666" }} data-collab-role={u.role}>
                                    {u.role}
                                </span>
                            )}
                        </Row>
                    ))
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
