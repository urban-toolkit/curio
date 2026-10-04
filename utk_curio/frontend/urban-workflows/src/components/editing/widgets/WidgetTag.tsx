import React from "react";
import styles from "./WidgetTags.module.css";
import { WIDGET_REF_MIME, referenceText } from "./monacoWidgetRefs";
import type { WidgetDef } from "../../../utils/widgets/widgetModel";

/** One widget's tag (#662): dragged into a code editor, or clicked to insert
 * the reference at the cursor. */
export function WidgetTag({
  name,
  onInsert,
  disabled = false,
}: {
  name: string;
  onInsert?: (name: string) => void;
  disabled?: boolean;
}) {
  return (
    <span
      className={styles.tag}
      draggable={!disabled}
      role={onInsert ? "button" : undefined}
      tabIndex={onInsert ? 0 : undefined}
      title={onInsert ? "Drag into the code, or click to insert it at the cursor" : "Drag into the code"}
      data-widget-tag={name}
      onDragStart={(event) => {
        event.dataTransfer.setData(WIDGET_REF_MIME, name);
        event.dataTransfer.setData("text/plain", referenceText(name));
        event.dataTransfer.effectAllowed = "copy";
        event.stopPropagation();
      }}
      onClick={() => {
        if (!disabled) onInsert?.(name);
      }}
      onKeyDown={(event) => {
        if (!onInsert || disabled) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onInsert(name);
        }
      }}
    >
      {name}
    </span>
  );
}

/** The node's tags above a code or grammar editor. Nothing when it has none. */
export function WidgetTagStrip({
  widgets,
  onInsert,
  disabled = false,
}: {
  widgets: WidgetDef[];
  onInsert: (name: string) => void;
  disabled?: boolean;
}) {
  if (widgets.length === 0) return null;
  return (
    <div className={styles.strip} aria-label="Widget tags" data-widget-strip="true">
      <span className={styles.stripHint}>Widgets</span>
      {widgets.map((w) => (
        <WidgetTag key={w.name} name={w.name} onInsert={onInsert} disabled={disabled} />
      ))}
    </div>
  );
}

export default WidgetTag;
