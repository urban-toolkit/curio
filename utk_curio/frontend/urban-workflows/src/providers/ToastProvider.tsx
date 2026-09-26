import React, { createContext, useState, useContext, useCallback, useMemo, ReactNode } from "react";
import { createPortal } from "react-dom";
import { Toast } from "react-bootstrap";

export type ToastVariant = "error" | "warning" | "info" | "success";

/** A way into what the toast is about, e.g. "View details" on a dataset. */
export interface ToastAction {
    label: string;
    onClick: () => void;
}

export interface ToastOptions {
    action?: ToastAction;
}

interface ToastItem {
    id: number;
    /** The slot this message holds in the stack, shared by every occurrence. */
    seq: number;
    message: string;
    variant: ToastVariant;
    action?: ToastAction;
}

/** Every outstanding occurrence of one message, rendered as a single toast. */
interface ToastGroup {
    seq: number;
    ids: number[];
    message: string;
    variant: ToastVariant;
    /** The latest occurrence's, so it acts on what was reported last. */
    action?: ToastAction;
}

interface ToastContextValue {
    showToast: (message: string, variant?: ToastVariant, options?: ToastOptions) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let _nextId = 0;

const VARIANT_BG: Record<ToastVariant, string> = {
    error: "#c0392b",
    warning: "#e8a838",
    success: "#27ae60",
    info: "#2980b9",
};

const VARIANT_TITLE: Record<ToastVariant, string> = {
    error: "Error",
    warning: "Warning",
    success: "Success",
    info: "Info",
};

// How long a toast stays up before it clears itself. An ERROR never does: it
// reports something that went wrong and usually names what to do about it -
// a library that will not import, a package that could not be added - and
// five seconds is not long enough to read a sentence like that, let alone act
// on it. Every other variant is an acknowledgement of something that worked,
// which the user does not have to retain, so those still clear themselves.
const AUTO_DISMISS_MS: Partial<Record<ToastVariant, number>> = {
    warning: 5000,
    success: 5000,
    info: 5000,
};

export const ToastProvider = ({ children }: { children: ReactNode }) => {
    const [toasts, setToasts] = useState<ToastItem[]>([]);

    const showToast = useCallback((
        message: string,
        variant: ToastVariant = "error",
        options: ToastOptions = {},
    ) => {
        const id = _nextId++;
        setToasts((prev) => {
            // A repeat joins the slot its message already holds. Derive the
            // slot from the occurrences still outstanding instead and a toast
            // the user can see moves: when the first of two "Saved" toasts
            // expires, the second would re-enter the stack below an error
            // raised between them, swapping two live toasts under the pointer.
            const sibling = prev.find(
                (t) => t.variant === variant && t.message === message,
            );
            const seq = sibling
                ? sibling.seq
                : prev.reduce((highest, t) => Math.max(highest, t.seq), -1) + 1;
            return [...prev, { id, seq, message, variant, action: options.action }];
        });
        const after = AUTO_DISMISS_MS[variant];
        if (after !== undefined) {
            setTimeout(() => {
                setToasts((prev) => prev.filter((t) => t.id !== id));
            }, after);
        }
    }, []);

    const dismiss = useCallback((ids: readonly number[]) => {
        setToasts((prev) => prev.filter((t) => !ids.includes(t.id)));
    }, []);

    /**
     * One entry per distinct message, in the order the first of them arrived.
     *
     * Repeats collapse instead of stacking. A failure that fans out raises the
     * same sentence once per occurrence - one per Autark node that probes
     * WebGPU, one per library in a batch install - and since an error stays
     * until it is dismissed, five of them were taller than the window: the
     * oldest was clipped off the TOP of the screen, close button and all, and
     * could not be dismissed at all.
     *
     * Grouped at render rather than counted at insert, so each occurrence keeps
     * its own id and its own auto-dismiss timer (a repeated info toast counts
     * back down as they expire) and the state updater stays a pure function of
     * the previous state.
     */
    const groups = useMemo(() => {
        const bySlot = new Map<number, ToastGroup>();
        for (const toast of toasts) {
            const seen = bySlot.get(toast.seq);
            if (seen) {
                seen.ids.push(toast.id);
                if (toast.action) seen.action = toast.action;
            } else bySlot.set(toast.seq, {
                seq: toast.seq, ids: [toast.id],
                message: toast.message, variant: toast.variant, action: toast.action,
            });
        }
        // By slot, not by whichever occurrence happens to still be outstanding.
        return [...bySlot.values()].sort((a, b) => a.seq - b.seq);
    }, [toasts]);

    const toastContainer = (
        <div
            // aria-live so screen readers announce feedback even while a
            // focus-trapped `aria-modal` drawer/dialog is open. Error toasts
            // escalate to assertive via role="alert" on the toast itself.
            aria-live="polite"
            aria-atomic="false"
            aria-label="Notifications"
            style={{
                position: "fixed",
                // Clears the bottom-anchored footer band of the right-side
                // drawers; see the token. An error toast now stays until it is
                // dismissed, so overlapping a button is not a passing moment.
                bottom: "var(--curio-toast-bottom-gutter, 20px)",
                right: "20px",
                // Top of the overlay/layering scale (see curioTokens.css) so
                // dataset action feedback stays visible above drawers/modals.
                zIndex: "var(--curio-z-toast)",
                display: "flex",
                flexDirection: "column",
                gap: "8px",
                maxWidth: "360px",
            }}
        >
            {groups.map((toast) => (
                    <Toast
                        // The slot, not `ids[0]`: that changes when the oldest
                        // occurrence expires, and React would then tear down a
                        // toast still on screen - dropping keyboard focus from
                        // its close button to <body> mid-interaction.
                        key={toast.seq}
                        show
                        onClose={() => dismiss(toast.ids)}
                        role={toast.variant === "error" ? "alert" : "status"}
                        aria-live={toast.variant === "error" ? "assertive" : "polite"}
                        aria-atomic="true"
                        style={{
                            backgroundColor: VARIANT_BG[toast.variant],
                            color: "white",
                            border: "none",
                            borderRadius: "6px",
                            boxShadow: "0 4px 12px rgba(0,0,0,0.35)",
                            minWidth: "260px",
                        }}
                    >
                        <Toast.Header
                            style={{
                                backgroundColor: "rgba(0,0,0,0.15)",
                                color: "white",
                                border: "none",
                                borderRadius: "6px 6px 0 0",
                            }}
                        >
                            <strong className="me-auto">
                                {VARIANT_TITLE[toast.variant]}
                            </strong>
                            {toast.ids.length > 1 && (
                                // How many times it happened, rather than one
                                // toast per time. Reads as a tally, so the
                                // sentence underneath is still read once.
                                <span
                                    data-testid="toast-count"
                                    title={`Reported ${toast.ids.length} times`}
                                    style={{
                                        marginRight: "8px",
                                        padding: "0 6px",
                                        borderRadius: "10px",
                                        backgroundColor: "rgba(255,255,255,0.25)",
                                        fontSize: "11px",
                                        fontVariantNumeric: "tabular-nums",
                                    }}
                                >
                                    &times;{toast.ids.length}
                                </span>
                            )}
                        </Toast.Header>
                        <Toast.Body style={{ fontSize: "13px", padding: "8px 12px" }}>
                            {toast.message}
                            {toast.action ? (
                                // The same "View details" a card or a row offers,
                                // for the thing the toast just reported. Using it
                                // settles the toast.
                                <button
                                    type="button"
                                    data-testid="toast-action"
                                    onClick={() => {
                                        toast.action?.onClick();
                                        dismiss(toast.ids);
                                    }}
                                    style={{
                                        display: "block",
                                        marginTop: "6px",
                                        padding: 0,
                                        border: 0,
                                        background: "none",
                                        color: "white",
                                        font: "inherit",
                                        fontWeight: 600,
                                        textDecoration: "underline",
                                        cursor: "pointer",
                                    }}
                                >
                                    {toast.action.label}
                                </button>
                            ) : null}
                        </Toast.Body>
                    </Toast>
                ))}
        </div>
    );

    // Portal to <body> so the toasts escape any ancestor stacking context
    // (transform/opacity/z-index on a provider wrapper would otherwise trap
    // the fixed container and re-bury it behind portaled overlays). Mirrors
    // ModalShell. Fall back to inline render where document is unavailable.
    const toastPortal =
        typeof document !== "undefined"
            ? createPortal(toastContainer, document.body)
            : toastContainer;

    return (
        <ToastContext.Provider value={{ showToast }}>
            {children}
            {toastPortal}
        </ToastContext.Provider>
    );
};

export const useToastContext = (): ToastContextValue => {
    const ctx = useContext(ToastContext);
    if (!ctx) throw new Error("useToastContext must be used within ToastProvider");
    return ctx;
};
