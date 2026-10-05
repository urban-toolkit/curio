import React, { useId, useState } from "react";
import ModalShell from "../ModalShell";
import styles from "../ConfirmDialog.module.css";
import DataflowCategoryInput from "./DataflowCategoryInput";
import type { DataflowCategories, HandCategories } from "../../utils/dataflowCategories";

export interface DataflowCategoriesDialogProps {
  dataflowName: string;
  categories?: DataflowCategories;
  /** Dataflows whose categories feed the suggestions. */
  suggestionItems: { categories?: DataflowCategories }[];
  busy?: boolean;
  onConfirm: (hand: HandCategories) => void;
  onCancel: () => void;
}

/**
 * The Projects page's "Edit categories": the canvas title's editor inside the
 * PromptDialog chrome. Nothing is saved until Save.
 */
export default function DataflowCategoriesDialog({
  dataflowName,
  categories,
  suggestionItems,
  busy = false,
  onConfirm,
  onCancel,
}: DataflowCategoriesDialogProps) {
  const titleId = useId();
  const [hand, setHand] = useState<HandCategories>(categories?.hand ?? {});

  return (
    <ModalShell onClose={busy ? () => {} : onCancel} titleId={titleId}>
      <form
        className={styles.dialog}
        onSubmit={(e) => {
          e.preventDefault();
          if (!busy) onConfirm(hand);
        }}
      >
        <h2 id={titleId} className={styles.title}>
          {`Categories of "${dataflowName}"`}
        </h2>
        <div className={styles.field}>
          <DataflowCategoryInput
            categories={categories}
            hand={hand}
            onChange={setHand}
            suggestionItems={suggestionItems}
            inlineForm
          />
        </div>
        <div className={styles.footer}>
          <button type="button" className={styles.ghostButton} onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className={styles.actionButton} disabled={busy}>
            Save
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
