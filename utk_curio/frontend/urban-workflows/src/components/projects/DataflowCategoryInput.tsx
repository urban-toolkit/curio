import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import {
  HAND_SECTIONS,
  SINGLE_VALUE_SECTIONS,
  SOURCE_LABELS,
  addHandCategory,
  cleanCategoryValue,
  knownValues,
  removeHandCategory,
  type DataflowCategories,
  type HandCategories,
  type HandSection,
} from "../../utils/dataflowCategories";
import styles from "./DataflowCategoryInput.module.css";

interface Chip {
  key: string;
  value: string;
  /** What the chip is, for its tooltip: "Tag", "Data type (from the nodes)"... */
  kind: string;
  /** Set on hand chips: the section a × removes it from. */
  section?: HandSection;
}

export interface DataflowCategoryInputProps {
  /** Source and automatic categories, as the server computed them. */
  categories?: DataflowCategories;
  /** The hand-set categories being edited. */
  hand: HandCategories;
  /** Absent = read-only: no ×, no "+ Category". */
  onChange?: (next: HandCategories) => void;
  /** Dataflows whose categories feed the suggestions. */
  suggestionItems?: { categories?: DataflowCategories }[];
  /** Called when the add form opens, so a caller can fetch suggestion items lazily. */
  onOpenAdd?: () => void;
  /** Chips shown before "+N" collapses the rest; unset shows every chip. */
  maxVisible?: number;
  /** Keep the add form open below the chips instead of behind "+ Category"
   *  (the dialog, where a floating form would be clipped by the modal). */
  inlineForm?: boolean;
  className?: string;
}

function buildChips(categories: DataflowCategories | undefined, hand: HandCategories): Chip[] {
  const chips: Chip[] = [];
  const push = (value: string, kind: string, section?: HandSection) =>
    chips.push({ key: `${section ?? kind}:${value}`, value, kind, section });
  if (categories?.source) push(SOURCE_LABELS[categories.source], "Source");
  for (const tag of categories?.auto?.tags ?? []) push(tag, "Tag (from the nodes)");
  for (const tag of hand.tags ?? []) push(tag, "Tag", "tags");
  for (const type of categories?.auto?.data_type ?? []) push(type, "Data type (from the nodes)");
  for (const city of hand.city ?? []) push(city, "City", "city");
  for (const topic of hand.topic ?? []) push(topic, "Topic", "topic");
  for (const level of hand.complexity ?? []) push(level, "Complexity", "complexity");
  return chips;
}

/**
 * A dataflow's categories as chips, with a way to add and remove the hand-set
 * ones. The canvas title and the Projects page's "Edit categories" dialog both
 * render this, so the two cannot disagree about what a category is.
 */
export const DataflowCategoryInput: React.FC<DataflowCategoryInputProps> = ({
  categories,
  hand,
  onChange,
  suggestionItems,
  onOpenAdd,
  maxVisible,
  inlineForm = false,
  className,
}) => {
  const [adding, setAdding] = useState(inlineForm);
  const [expanded, setExpanded] = useState(false);
  const [section, setSection] = useState<HandSection>("topic");
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const chips = useMemo(() => buildChips(categories, hand), [categories, hand]);
  const collapsed = maxVisible != null && !expanded && chips.length > maxVisible;
  const shown = collapsed ? chips.slice(0, maxVisible) : chips;
  const hidden = chips.length - shown.length;

  const suggestions = useMemo(() => {
    const taken = new Set((hand[section] ?? []).map((v) => v.toLocaleLowerCase()));
    return knownValues(suggestionItems ?? [], section).filter(
      (v) => !taken.has(v.toLocaleLowerCase()),
    );
  }, [suggestionItems, section, hand]);

  useEffect(() => {
    if (inlineForm) onOpenAdd?.();
    // Once, on mount: the inline form is open from the start.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding, section]);

  useEffect(() => {
    if (!adding || inlineForm) return;
    const onPointerDown = (event: PointerEvent) => {
      if (formRef.current && !formRef.current.contains(event.target as Node)) {
        setAdding(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [adding]);

  const openAdd = () => {
    setAdding(true);
    onOpenAdd?.();
  };

  const commit = () => {
    if (!onChange) return;
    const value = cleanCategoryValue(draft);
    if (!value) return;
    onChange(addHandCategory(hand, section, value));
    setDraft("");
    // Show what was just added, even when it lands past the "+N" fold.
    setExpanded(true);
    if (SINGLE_VALUE_SECTIONS.has(section) && !inlineForm) setAdding(false);
  };

  const form = (
    <div
      className={inlineForm ? styles.formInline : styles.form}
      role="group"
      aria-label="Add a category"
    >
      <select
        className={styles.select}
        aria-label="Category section"
        value={section}
        onChange={(e) => setSection(e.target.value as HandSection)}
      >
        {HAND_SECTIONS.map((s) => (
          <option key={s.key} value={s.key}>
            {s.label}
          </option>
        ))}
      </select>
      <input
        ref={inputRef}
        className={styles.input}
        aria-label="Category name"
        placeholder="Type or pick"
        list={listId}
        value={draft}
        maxLength={40}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          } else if (e.key === "Escape" && !inlineForm) {
            setAdding(false);
          }
        }}
      />
      <datalist id={listId}>
        {suggestions.map((value) => (
          <option key={value} value={value} />
        ))}
      </datalist>
      <button
        type="button"
        className={styles.confirm}
        disabled={!cleanCategoryValue(draft)}
        onClick={commit}
      >
        Add
      </button>
    </div>
  );

  const row = (
    <div className={styles.row}>
      {shown.map((chip) => (
        <span
          key={chip.key}
          className={clsx(styles.chip, chip.section ? styles.chipHand : styles.chipAuto)}
          title={`${chip.kind}: ${chip.value}`}
          data-curio-category-chip={chip.section ?? "auto"}
        >
          <span>{chip.value}</span>
          {chip.section && onChange ? (
            <button
              type="button"
              className={styles.remove}
              aria-label={`Remove ${chip.value}`}
              onClick={() => onChange(removeHandCategory(hand, chip.section!, chip.value))}
            >
              ×
            </button>
          ) : null}
        </span>
      ))}
      {hidden > 0 ? (
        <button
          type="button"
          className={styles.more}
          aria-label={`Show ${hidden} more categories`}
          onClick={() => setExpanded(true)}
        >
          +{hidden}
        </button>
      ) : null}
      {expanded && maxVisible != null && chips.length > maxVisible ? (
        <button type="button" className={styles.more} onClick={() => setExpanded(false)}>
          Fewer
        </button>
      ) : null}
      {onChange && !inlineForm ? (
        <div className={styles.addWrap} ref={formRef}>
          <button
            type="button"
            className={styles.add}
            aria-expanded={adding}
            onClick={() => (adding ? setAdding(false) : openAdd())}
          >
            + Category
          </button>
          {adding ? form : null}
        </div>
      ) : null}
    </div>
  );

  return (
    <div className={clsx(inlineForm && styles.stack, className)} data-curio-category-chips="true">
      {row}
      {onChange && inlineForm ? form : null}
    </div>
  );
};

export default DataflowCategoryInput;
