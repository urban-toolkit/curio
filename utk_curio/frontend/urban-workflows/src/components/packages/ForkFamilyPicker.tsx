import React, { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronDown } from "@fortawesome/free-solid-svg-icons";
import dockStyles from "./ForkFamilyPicker.dock.module.css";
import hubStyles from "./ForkFamilyPicker.hub.module.css";

export type ForkFamilyPickerVariant = "dock" | "hub";

export interface ForkFamilyPickerOption {
    key: string;
    label: string;
}

export interface ForkFamilyPickerProps {
    variant: ForkFamilyPickerVariant;
    /** Used in accessibility strings (family lineage root id). */
    rootKey: string;
    options: readonly ForkFamilyPickerOption[];
    value: string;
    onChange: (key: string) => void;
}

/** Multiline fork picker (native `<select>` cannot wrap option text). */
export function ForkFamilyPicker({ variant, rootKey, options, value, onChange }: ForkFamilyPickerProps) {
    const s = variant === "dock" ? dockStyles : hubStyles;

    const [open, setOpen] = useState(false);
    /** Fixed viewport box for Hub — avoids clipping inside ``overflow: auto`` sidebars. */
    const [hubListRect, setHubListRect] = useState<{ top: number; left: number; width: number } | null>(
        null,
    );
    const rootRef = useRef<HTMLDivElement>(null);
    const triggerRef = useRef<HTMLButtonElement>(null);
    const triggerId = useId();
    const visibleLabelId = useId();
    const listboxId = `${triggerId}-fork-listbox`;

    const commit = useCallback(
        (next: string) => {
            onChange(next);
            setOpen(false);
        },
        [onChange],
    );

    useEffect(() => {
        if (!open) setHubListRect(null);
    }, [open]);

    useLayoutEffect(() => {
        if (!open || variant !== "hub") return;

        const measure = () => {
            const el = triggerRef.current;
            if (!el) return;
            const r = el.getBoundingClientRect();
            setHubListRect({ top: r.bottom + 4, left: r.left, width: r.width });
        };

        measure();
        window.addEventListener("scroll", measure, true);
        window.addEventListener("resize", measure);
        return () => {
            window.removeEventListener("scroll", measure, true);
            window.removeEventListener("resize", measure);
        };
    }, [open, variant]);

    useEffect(() => {
        if (!open) return;
        const onDocMouseDown = (ev: MouseEvent) => {
            if (!rootRef.current?.contains(ev.target as Node)) setOpen(false);
        };
        const onKey = (ev: KeyboardEvent) => {
            if (ev.key === "Escape") setOpen(false);
        };
        document.addEventListener("mousedown", onDocMouseDown, true);
        window.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("mousedown", onDocMouseDown, true);
            window.removeEventListener("keydown", onKey);
        };
    }, [open]);

    const resolvedLabel = useMemo(() => {
        const hit = options.find((o) => o.key === value);
        return hit?.label ?? options[0]?.label ?? "";
    }, [options, value]);

    const listboxStyle: CSSProperties | undefined =
        variant === "hub" && hubListRect
            ? {
                  position: "fixed",
                  top: hubListRect.top,
                  left: hubListRect.left,
                  width: hubListRect.width,
                  zIndex: 4000,
              }
            : undefined;

    if (options.length === 0) {
        return null;
    }

    return (
        <div className={s.root} ref={rootRef}>
            <button
                type="button"
                id={triggerId}
                ref={triggerRef}
                className={s.trigger}
                aria-expanded={open}
                aria-haspopup="listbox"
                aria-controls={listboxId}
                aria-labelledby={visibleLabelId}
                title={rootKey}
                onClick={() => setOpen((o) => !o)}
            >
                <span id={visibleLabelId} className={s.triggerLabel}>
                    {resolvedLabel}
                </span>
                <FontAwesomeIcon
                    icon={faChevronDown}
                    className={`${s.triggerChevron} ${open ? s.triggerChevronOpen : ""}`}
                    aria-hidden
                />
            </button>
            {open ? (
                <div
                    id={listboxId}
                    className={s.listbox}
                    role="listbox"
                    aria-labelledby={visibleLabelId}
                    aria-label={`Forks for ${rootKey}`}
                    style={listboxStyle}
                >
                    {options.map((opt) => (
                        <button
                            key={opt.key}
                            type="button"
                            role="option"
                            aria-selected={opt.key === value}
                            className={
                                opt.key === value ? `${s.option} ${s.optionSelected}` : s.option
                            }
                            onClick={() => commit(opt.key)}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            ) : null}
        </div>
    );
}
