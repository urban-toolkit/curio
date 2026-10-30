/**
 * The Note node's body: its text as simple markdown, on its color. Its title,
 * a node's one name, is its heading, which the node's header shows, so the
 * body does not show it again. Edit opens a form for the three; a new, empty note opens on it. On
 * the dashboard and on a read-only canvas a note is shown, never edited.
 *
 * What it holds is what an agent's note holds, so a save writes it the same
 * way: the title in `data.title`, the text in `data.code` (the node's content),
 * the color in `data.appearance.backgroundColor`.
 */
import React, { useState } from "react";
import { useFlowContext } from "../../providers/FlowProvider";
import { useSharedView } from "../../hook/useSharedView";
import { NOTE_COLORS, noteColors, type NoteColorName } from "../../utils/noteColors";
import { NoteMarkdown } from "./NoteMarkdown";
import styles from "./Note.module.css";

const COLOR_NAMES = Object.keys(NOTE_COLORS) as NoteColorName[];

function titleOf(data: any): string {
  return typeof data?.title === "string" ? data.title.trim() : "";
}

function textOf(data: any): string {
  return typeof data?.code === "string" ? data.code : "";
}

function NoteForm({
  data,
  background,
  onDone,
}: {
  data: any;
  background: string;
  onDone: () => void;
}) {
  const { updateDataNode, markDirty } = useFlowContext();
  const [title, setTitle] = useState(titleOf(data));
  const [text, setText] = useState(textOf(data));
  const [color, setColor] = useState(background);

  const save = () => {
    updateDataNode(data.nodeId, {
      ...data,
      title: title.trim() || undefined,
      code: text,
      defaultCode: text,
      appearance: { ...(data.appearance ?? {}), backgroundColor: color },
    });
    markDirty?.();
    onDone();
  };

  return (
    <form
      className={`nodrag nopan nowheel ${styles.form}`}
      aria-label="Write the note"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <label className={styles.field}>
        <span>Title</span>
        <input type="text" value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label className={styles.field}>
        <span>Text</span>
        <textarea
          value={text}
          placeholder="# A heading, - a list, **bold**, [a link](https://...)"
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <div className={styles.colors} role="radiogroup" aria-label="Color">
        <span className={styles.colorsLabel}>Color</span>
        {COLOR_NAMES.map((name) => (
          <button
            key={name}
            type="button"
            role="radio"
            aria-checked={color === NOTE_COLORS[name]}
            aria-label={name}
            data-tooltip={name}
            className={styles.swatch}
            style={{ backgroundColor: NOTE_COLORS[name] }}
            onClick={() => setColor(NOTE_COLORS[name])}
          />
        ))}
      </div>
      <div className={styles.actions}>
        <button type="button" className={styles.button} onClick={onDone}>
          Cancel
        </button>
        <button type="submit" className={styles.button}>
          Save
        </button>
      </div>
    </form>
  );
}

export function NoteBody({ data }: { data: any }) {
  const { dashboardOn } = useFlowContext();
  const readOnly = useSharedView();
  const editable = !dashboardOn && !readOnly;
  const title = titleOf(data);
  const text = textOf(data);
  const colors = noteColors(data?.appearance?.backgroundColor);
  // A note with nothing written yet opens on its form, where it can be written.
  const [editing, setEditing] = useState(() => !title && !text.trim());

  if (editing && editable) {
    return <NoteForm data={data} background={colors.background} onDone={() => setEditing(false)} />;
  }
  const style = {
    backgroundColor: colors.background,
    color: colors.foreground,
    "--note-link": colors.link,
  } as React.CSSProperties;
  return (
    <div role="note" aria-label={title || "Note"} className={`nodrag nopan nowheel ${styles.note}`} style={style}>
      {text.trim() ? (
        <div className={styles.body}>
          <NoteMarkdown text={text} />
        </div>
      ) : (
        <p className={styles.empty}>An empty note.</p>
      )}
      {editable ? (
        <button type="button" className={styles.edit} aria-label="Edit note" onClick={() => setEditing(true)}>
          Edit
        </button>
      ) : null}
    </div>
  );
}
