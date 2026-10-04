import React from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faBookOpen, faDiagramProject, type IconDefinition } from "@fortawesome/free-solid-svg-icons";

import type { CanvasView } from "../../../providers/flow/useNotebookView";
import styles from "./CanvasViewSwitch.module.css";

const VIEWS: ReadonlyArray<{ view: CanvasView; label: string; icon: IconDefinition }> = [
  { view: "canvas", label: "Canvas", icon: faDiagramProject },
  { view: "notebook", label: "Notebook", icon: faBookOpen },
];

/**
 * How the dataflow is shown: the canvas, or its nodes as a column of notebook
 * cells with their connections in a bar. Both options always in the bar; the
 * words give way to the icons when the bar runs short, as the catalogs' do.
 */
export function CanvasViewSwitch({
  value,
  onChange,
  crowded = false,
}: {
  value: CanvasView;
  onChange: (view: CanvasView) => void;
  /** Another control shares the bar (the collaboration button), so the
   *  words give way sooner. */
  crowded?: boolean;
}) {
  return (
    <div
      className={clsx(styles.switch, crowded && styles.switchCrowded)}
      role="radiogroup"
      aria-label="Dataflow view"
    >
      {VIEWS.map(({ view, label, icon }) => (
        <button
          key={view}
          type="button"
          role="radio"
          aria-checked={value === view}
          aria-label={`${label} view`}
          title={`${label} view`}
          data-curio-canvas-view={view}
          className={clsx(styles.option, value === view && styles.optionChecked)}
          onClick={() => {
            if (value !== view) onChange(view);
          }}
        >
          <FontAwesomeIcon icon={icon} className={styles.icon} />
          <span className={styles.label}>{label}</span>
        </button>
      ))}
    </div>
  );
}

export default CanvasViewSwitch;
