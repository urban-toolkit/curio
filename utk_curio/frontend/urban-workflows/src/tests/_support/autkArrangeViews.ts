/**
 * autk-grammar's `arrangeViews`, for the suites that stand in for the grammar:
 * where each view of a spec goes, as its `layout` says, by the grammar's own
 * rule (autk-grammar 5.0.0, `grammar/src/layout.ts`). Free of app imports, so
 * a `jest.mock` factory can require it:
 *
 *     jest.mock("@urban-toolkit/autk-grammar", () => ({ ..., arrangeViews: require("<this file>").arrangeViews }), { virtual: true });
 */

type Pane = { kind: 'map' | 'plot'; index: number; id?: string; key: string | number; row: number; column: number };

const asList = (value: unknown): any[] => (value === undefined ? [] : Array.isArray(value) ? value : [value]);

export function arrangeViews(spec: any): {
  type: 'vertical' | 'horizontal' | 'grid'; rows: number; columns: number; gap: number; panes: Pane[];
} {
  const layout = spec?.layout ?? {};
  const type = layout.type ?? 'vertical';
  if (type !== 'vertical' && type !== 'horizontal' && type !== 'grid')
    throw new Error(`Layout type must be vertical, horizontal or grid, not ${JSON.stringify(type)}.`);
  const gap = layout.gap ?? 0;
  if (typeof gap !== 'number' || !Number.isFinite(gap) || gap < 0)
    throw new Error(`Layout gap must be a number of pixels, 0 or more, not ${JSON.stringify(gap)}.`);
  const gridColumns = layout.columns ?? 2;
  if (!Number.isInteger(gridColumns) || gridColumns < 1)
    throw new Error(`Layout columns must be a whole number, 1 or more, not ${JSON.stringify(gridColumns)}.`);
  const views = [
    ...asList(spec?.map).map((map, index) => ({ kind: 'map' as const, index, id: map?.id, key: map?.id ?? index })),
    ...asList(spec?.plot).map((plot, index) => ({ kind: 'plot' as const, index, id: plot?.id, key: plot?.id ?? plot?.dataRef })),
  ];
  const columns = type === 'vertical' ? 1 : type === 'horizontal' ? Math.max(views.length, 1) : gridColumns;
  const panes = views.map(({ kind, index, id, key }, at): Pane => ({
    kind,
    index,
    ...(id !== undefined && { id }),
    key,
    row: Math.floor(at / columns),
    column: at % columns,
  }));
  return { type, rows: Math.ceil(views.length / columns), columns, gap, panes };
}

/** The panes `arrangeViews` gives *spec*'s views. */
export const panesOf = (spec: any): Pane[] => arrangeViews(spec).panes;
