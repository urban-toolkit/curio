import React from 'react';
import { render } from '@testing-library/react';
import { SummaryContent } from '../../../adapters/node/dataSummaryBehavior';

/**
 * The Data Summary node must scroll a wide table, not crush it (#345).
 *
 * #203 fixed exactly this for the Data Pool and left two sibling surfaces
 * alone. This is the first: `describe()` with `include="all"` produces one
 * column per dataframe column, so the stats table is arbitrarily wide, and MUI
 * `Table` defaults to `width: 100%` with `table-layout: auto` - which squeezes
 * columns toward min-content instead of overflowing, so the container's own
 * `overflow-x: auto` never has anything to scroll. `min-width: max-content` is
 * the piece that makes the overflow real.
 *
 * Note the ownership differs from the Data Pool on purpose. There, one outer
 * div owns the scroll because the body IS the table. Here three tables stack
 * under their own headings, so each table scrolls inside its own container and
 * "Shape" / "Data Types" stay put while you read across.
 */
const WIDE_SUMMARY = {
  shape: { rows: 5, columns: 40 },
  describe: Object.fromEntries(
    Array.from({ length: 40 }, (_, i) => [
      `a_very_long_column_name_${i}`,
      { count: 5, mean: 1.5, std: 0.5, min: 0, max: 3 },
    ]),
  ),
  dtypes: Object.fromEntries(
    Array.from({ length: 40 }, (_, i) => [`a_very_long_column_name_${i}`, 'float64']),
  ),
  missing: { a_very_long_column_name_0: 2 },
};

function renderSummary() {
  return render(<SummaryContent summary={WIDE_SUMMARY} nodeId="n1" />);
}

describe('Data Summary wide-table scroll', () => {
  test('every stats table declares a max-content min-width, so it overflows', () => {
    const { container } = renderSummary();
    const tables = Array.from(container.querySelectorAll('table')) as HTMLElement[];

    // describe + dtypes + missing
    expect(tables.length).toBe(3);
    for (const table of tables) {
      expect(getComputedStyle(table).minWidth).toBe('max-content');
    }
  });

  test('each table sits in a container that owns the x overflow', () => {
    const { container } = renderSummary();
    const scrollers = Array.from(
      container.querySelectorAll('[data-curio-summary-scroll]'),
    ) as HTMLElement[];

    expect(scrollers.length).toBe(3);
    // Named rather than positional: the wide one (describe) renders LAST, so a
    // test keying off order would measure the 2-column dtypes table instead -
    // which cannot overflow, and would pass while proving nothing.
    expect(
      scrollers.map((el) => el.getAttribute('data-curio-summary-scroll')),
    ).toEqual(['dtypes', 'missing', 'describe']);
    for (const scroller of scrollers) {
      // MUI's TableContainer default, kept rather than overridden: unlike the
      // Data Pool there is no outer scroller to pass the overflow up to.
      expect(['auto', 'scroll']).toContain(getComputedStyle(scroller).overflowX);
    }
  });

  test('the node body still owns vertical scroll, and still stops React Flow', () => {
    // #156's fix on this component; the horizontal change must not disturb it.
    const { container } = renderSummary();
    const body = container.firstElementChild as HTMLElement;

    expect(getComputedStyle(body).overflowY).toBe('auto');
    // `nowheel` is matched with `closest`, so it covers the inner scrollers too
    // - without it React Flow's ZoomPane eats the wheel before they see it.
    expect(body.className).toContain('nowheel');
  });
});
