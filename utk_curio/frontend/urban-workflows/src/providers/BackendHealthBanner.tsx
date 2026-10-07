import React, { useEffect, useState } from "react";
import { backendUrl } from "../utils/backendUrl";
import { isStandaloneDashboard } from "../standalone/dashboardPayload";

const BACKEND_URL = backendUrl() || "http://localhost:5002";

/** How often /live is asked again while the backend is down. */
export const DOWN_RECHECK_MS = 10_000;
/** How often a hosted page asks while the backend is up, to notice an outage. */
export const UP_RECHECK_MS = 30_000;

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"]);

/**
 * A page served from this machine, whose reader can start the backend
 * themselves. Decided from the page's own address, which needs no backend: on
 * any other address the reader is a visitor, and the backend is down because
 * the site is being updated or its server is.
 */
export function isLocalPage(hostname: string = window.location.hostname): boolean {
    return LOCAL_HOSTS.has(hostname);
}

type Health = "unknown" | "up" | "down" | "back";

/**
 * Pings the backend /live endpoint. If the backend is unreachable, shows a
 * dismissible banner: how to start it on a local page, that Curio is offline on
 * a hosted one. While down it asks again every 10 s, and when the backend
 * answers the banner says so and offers a reload, since the page could not
 * sign in or load anything meanwhile. A hosted page also asks every 30 s while
 * up and visible, so an outage that starts while it is open is shown too.
 */
export const BackendHealthBanner: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [health, setHealth] = useState<Health>("unknown");
    const [dismissed, setDismissed] = useState(false);
    const local = isLocalPage();

    useEffect(() => {
        // A standalone dashboard has no backend to be down. Asking would be the
        // page's only request, and a visitor who opened a link somewhere the
        // server is unreachable would be told so by a banner over a page that
        // is working perfectly.
        if (isStandaloneDashboard()) return;
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let down = false;
        let checked = false;

        const check = async () => {
            // A hidden hosted tab whose backend is up waits for its next turn:
            // nobody is there to read a banner. The first check always runs.
            if (checked && !down && document.visibilityState === "hidden") {
                timer = setTimeout(check, UP_RECHECK_MS);
                return;
            }
            checked = true;
            let ok = false;
            try {
                const res = await fetch(`${BACKEND_URL}/live`, { method: "GET", cache: "no-store" });
                ok = res.ok;
            } catch {
                ok = false;
            }
            if (cancelled) return;
            const wasDown = down;
            down = !ok;
            setHealth((prev) => {
                if (!ok) return "down";
                return wasDown || prev === "back" ? "back" : "up";
            });
            if (down) timer = setTimeout(check, DOWN_RECHECK_MS);
            else if (!local) timer = setTimeout(check, UP_RECHECK_MS);
        };
        check();
        return () => {
            cancelled = true;
            if (timer !== undefined) clearTimeout(timer);
        };
    }, [local]);

    // Dismiss hides one message: a new outage, or the backend coming back,
    // shows the banner again.
    useEffect(() => setDismissed(false), [health]);

    const show = (health === "down" || health === "back") && !dismissed;

    return (
        <>
            {show && (
                <div
                    style={{
                        position: "sticky",
                        top: 0,
                        zIndex: 10000,
                        padding: "10px 16px",
                        background: health === "back" ? "#2f855a" : "#c53030",
                        color: "#fff",
                        fontSize: "14px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "12px",
                        boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
                    }}
                    role={health === "back" ? "status" : "alert"}
                >
                    {health === "back" ? (
                        <span>Curio is back. Reload the page to continue.</span>
                    ) : local ? (
                        <span>
                            Backend server is not reachable. Start it with:{" "}
                            <code style={{ background: "rgba(0,0,0,0.2)", padding: "2px 6px", borderRadius: "4px" }}>
                                python curio.py start backend
                            </code>
                            {" "}(from project root). Configured URL: {BACKEND_URL}
                        </span>
                    ) : (
                        <span>
                            Curio is offline: it is being updated or its server is down. This message
                            changes when Curio is back.
                        </span>
                    )}
                    <span style={{ display: "flex", gap: "8px" }}>
                        {health === "back" && (
                            <button type="button" onClick={() => window.location.reload()} style={BUTTON}>
                                Reload
                            </button>
                        )}
                        <button type="button" onClick={() => setDismissed(true)} aria-label="Dismiss" style={BUTTON}>
                            Dismiss
                        </button>
                    </span>
                </div>
            )}
            {children}
        </>
    );
};

const BUTTON: React.CSSProperties = {
    background: "rgba(255,255,255,0.2)",
    border: "none",
    color: "#fff",
    padding: "4px 10px",
    borderRadius: "4px",
    cursor: "pointer",
    fontWeight: 600,
};
