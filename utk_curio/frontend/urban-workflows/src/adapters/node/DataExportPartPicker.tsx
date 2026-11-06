import React, { useEffect, useState } from 'react';
import TextField from '@mui/material/TextField';
import { ThemeProvider } from '@mui/material/styles';
import styles from '../../components/editing/widgets/WidgetTags.module.css';
import { widgetTheme } from '../../components/editing/widgets/widgetTheme';
import { partNamed, partValue, type ExportPart } from '../../utils/dataExportParts';

/** The longest label the list shows whole; a longer one is cut, and the
 * chosen one shows whole on hover. */
export const PART_LABEL_CHARS = 40;

/** What the list shows of *label*. */
const shortened = (label: string): string =>
  label.length > PART_LABEL_CHARS ? `${label.slice(0, PART_LABEL_CHARS - 1).trimEnd()}…` : label;

type Props = {
  /** The parts the node's input holds, in their order (utils/dataExportParts). */
  parts: readonly ExportPart[];
  /** The Part widget's value: empty for every part. */
  value: string;
  /** Sets the Part widget's value. */
  onPick: (value: string) => void;
  disabled?: boolean;
};

/**
 * Data Export's Part, when its input holds several parts: a dropdown of All
 * parts, then each part by the label its file in the zip is named after. A
 * pick writes the Part widget's value (`partValue`), the one
 * `curio_export(..., part=[!! part !!])` reads; a saved value no part of the
 * input has stays chosen, marked as not in the input, so a run's refusal
 * names what the dropdown shows.
 */
export function DataExportPartPicker({ parts, value, onPick, disabled = false }: Props) {
  // The value shown follows a pick at once; the node's data, when it changes.
  const [shown, setShown] = useState(value);
  useEffect(() => setShown(value), [value]);

  const chosen = partNamed(parts, shown);
  const stale = shown !== '' && chosen === null;
  const selected = chosen ? partValue(parts, chosen) : shown;
  const staleText = `${shown} (not in the input)`;
  const tooltip = chosen ? chosen.label : stale ? staleText : undefined;

  return (
    <div className={`${styles.row} ${styles.plainRow}`} data-part-picker="true">
      <span className={styles.rowLabel}>Part</span>
      <span className={styles.rowControl}>
        <ThemeProvider theme={widgetTheme}>
          <span className={`${styles.control} nodrag nowheel`}>
            {/* A native list: it opens at any zoom of the canvas. */}
            <TextField
              select
              fullWidth
              SelectProps={{ native: true }}
              value={selected}
              disabled={disabled}
              inputProps={{
                'aria-label': 'Part',
                'data-tooltip': tooltip,
                'data-stale': stale ? 'true' : undefined,
              }}
              onChange={(event) => {
                setShown(event.target.value);
                onPick(event.target.value);
              }}
            >
              <option value="">All parts</option>
              {parts.map((part) => (
                <option key={part.index} value={partValue(parts, part)} data-label={part.label}>
                  {shortened(part.label)}
                </option>
              ))}
              {stale ? <option value={shown}>{staleText}</option> : null}
            </TextField>
          </span>
        </ThemeProvider>
      </span>
    </div>
  );
}

export default DataExportPartPicker;
