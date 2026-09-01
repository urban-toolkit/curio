import React, { useRef } from "react";
import styles from "./CatalogBrowseLayout.module.css";

/**
 * The import control for a catalog's standalone page, sitting in the header
 * tools row beside the search box.
 *
 * The three catalog DRAWERS each have an import in a sticky footer, but the
 * three catalog PAGES had none at all: the only way to get a file into the
 * product from `/catalog/data`, `/catalog/nodes` or `/catalog/agents` was to
 * leave the page, open a dataflow, and use that dataflow's drawer - even though
 * two of the three imports are not dataflow-scoped in the first place.
 *
 * The arrangement copies the Projects page, which already had this shape and is
 * the only page that did: search, then a light-filled import, then (where there
 * is one) the dark primary action. So `publishButton` here is deliberate - it
 * is the same class the Projects page gives "Import Jupyter notebook", which
 * keeps import a secondary treatment across all four pages rather than
 * competing with the page's primary action.
 */
export interface CatalogHeaderImportProps {
  /** Button text, e.g. "Import dataset". */
  label: string;
  busy?: boolean;
  /**
   * File types to accept. When set, the button opens a file dialog and hands
   * the chosen File to `onPick`. When omitted, it is a plain button and only
   * `onClick` fires - the Agent catalog needs that, because an agent package is
   * a manifest plus its prompt files and is assembled inside a modal.
   */
  accept?: string;
  onPick?: (file: File) => void;
  onClick?: () => void;
  /** Overrides the button's tooltip; defaults to the label. */
  title?: string;
}

export const CatalogHeaderImport: React.FC<CatalogHeaderImportProps> = ({
  label,
  busy = false,
  accept,
  onPick,
  onClick,
  title,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const isFilePicker = accept != null && onPick != null;

  return (
    <>
      {isFilePicker ? (
        <input
          ref={fileInputRef}
          type="file"
          accept={accept}
          hidden
          aria-hidden
          tabIndex={-1}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onPick(file);
            // Clear it, or picking the SAME file twice fires no change event
            // and the second import silently does nothing.
            if (fileInputRef.current) fileInputRef.current.value = "";
          }}
        />
      ) : null}
      <button
        type="button"
        className={styles.publishButton}
        disabled={busy}
        title={title ?? label}
        onClick={() => {
          if (isFilePicker) fileInputRef.current?.click();
          else onClick?.();
        }}
      >
        {busy ? "Importing…" : label}
      </button>
    </>
  );
};

export default CatalogHeaderImport;
