import React, { useEffect, useState } from "react";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:5002";

/**
 * Pings the backend /live endpoint. If the backend is unreachable (e.g. not started),
 * shows a dismissible banner so users know to start it instead of only seeing console errors.
 */
export const BackendHealthBanner: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [backendDown, setBackendDown] = useState<boolean | null>(null);
    const [dismissed, setDismissed] = useState(false);

    useEffect(() => {
        let cancelled = false;
        fetch(`${BACKEND_URL}/live`, { method: "GET" })
            .then((res) => {
                if (cancelled) return;
                setBackendDown(!res.ok);
            })
            .catch(() => {
                if (!cancelled) setBackendDown(true);
            });
        return () => {
            cancelled = true;
        };
    }, []);

    const show = backendDown === true && !dismissed;

    return (
        <>
            {show && (
                <div
                    style={{
                        position: "sticky",
                        top: 0,
                        zIndex: 10000,
                        padding: "10px 16px",
                        background: "#c53030",
                        color: "#fff",
                        fontSize: "14px",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "12px",
                        boxShadow: "0 2px 4px rgba(0,0,0,0.2)",
                    }}
                    role="alert"
                >
                    <span>
                        Backend server is not reachable. Start it with:{" "}
                        <code style={{ background: "rgba(0,0,0,0.2)", padding: "2px 6px", borderRadius: "4px" }}>
                            python curio.py start backend
                        </code>
                        {" "}(from project root). Configured URL: {BACKEND_URL}
                    </span>
                    <button
                        type="button"
                        onClick={() => setDismissed(true)}
                        aria-label="Dismiss"
                        style={{
                            background: "rgba(255,255,255,0.2)",
                            border: "none",
                            color: "#fff",
                            padding: "4px 10px",
                            borderRadius: "4px",
                            cursor: "pointer",
                            fontWeight: 600,
                        }}
                    >
                        Dismiss
                    </button>
                </div>
            )}
            {children}
        </>
    );
};
