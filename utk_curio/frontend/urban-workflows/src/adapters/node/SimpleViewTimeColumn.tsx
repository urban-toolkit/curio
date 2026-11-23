import React, { useEffect, useState } from 'react';
import TextField from '@mui/material/TextField';
import { ThemeProvider } from '@mui/material/styles';
import styles from '../../components/editing/widgets/WidgetTags.module.css';
import { widgetTheme } from '../../components/editing/widgets/widgetTheme';
import { changeableOnDashboard } from '../../utils/widgets/dashboardControls';
import { effectiveValue, type WidgetDef } from '../../utils/widgets/widgetModel';

type Props = {
  /** The Time column widget: the node's own, else its template's. */
  widget: WidgetDef;
  /** Sets the widget's value, the column the player's range names. */
  onCommit: (value: string) => void;
  /** On a dashboard tile, where a text widget's value is read-only. */
  dashboard?: boolean;
};

/**
 * Simple View's Time column, drawn as a widget's row is: its label above a
 * text field. The value is the column a card's player names its range in,
 * in the views linked to the Simple View (utils/playerSelection), and it
 * reaches the node when the field is left or Enter is pressed. On a
 * dashboard tile it shows the column, read-only, as every text widget there.
 */
export function SimpleViewTimeColumn({ widget, onCommit, dashboard = false }: Props) {
  const held = effectiveValue(widget);
  const committed = typeof held === 'string' ? held : '';
  // The value shown follows the field at once; the node's data, when it changes.
  const [shown, setShown] = useState(committed);
  useEffect(() => setShown(committed), [committed]);
  const commit = () => {
    if (shown !== committed) onCommit(shown);
  };
  const label = widget.label || widget.name;

  return (
    <div className={`${styles.row} ${styles.plainRow}`} data-widget-row={widget.name} style={{ width: '100%' }}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowControl}>
        <ThemeProvider theme={widgetTheme}>
          <span className={`${styles.control} nodrag nowheel`}>
            <TextField
              fullWidth
              value={shown}
              disabled={dashboard && !changeableOnDashboard(widget)}
              inputProps={{ 'aria-label': label }}
              onChange={(event) => setShown(event.target.value)}
              onBlur={commit}
              onKeyDown={(event) => {
                if (event.key === 'Enter') commit();
              }}
            />
          </span>
        </ThemeProvider>
      </span>
    </div>
  );
}

export default SimpleViewTimeColumn;
