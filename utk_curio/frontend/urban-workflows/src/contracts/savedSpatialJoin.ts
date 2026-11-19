/**
 * A Spatial Join saved before its join was code reads as one made now.
 *
 * The join's body once picked its operation and output, saved at
 * `metadata.spatialJoin` (`predicate`, `output`). A join saved so, with no
 * code and no widgets, reads with its template's code and widgets, each widget
 * holding the setting saved for it when that setting is one of its choices,
 * and without `metadata.spatialJoin` (`savedSpatialJoin.json`). A join with
 * code or widgets is left as it is. `hook/codeNodes.ts` reads every node of a
 * load and of the doc through it. The backend's twin is
 * `projects/saved_joins.py`; both run `savedSpatialJoin.cases.json`.
 */
import saved from './savedSpatialJoin.json';

type TrillNode = Record<string, any>;

const settingOf: Record<string, string> = Object.fromEntries(
  Object.entries(saved.widgetOf).map(([setting, widget]) => [widget, setting]),
);

function unversioned(type: unknown): unknown {
  return typeof type === 'string' ? type.split('@')[0] : type;
}

/** Whether *node*, a dataflow's node, is a Spatial Join saved before its code: of the join's type, with no code and no widgets. */
export function isSavedJoin(node: unknown): boolean {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return false;
  const trill = node as TrillNode;
  if (unversioned(trill.type) !== saved.nodeType) return false;
  const content = trill.content;
  if (content !== undefined && content !== null && !(typeof content === 'string' && content.trim() === '')) return false;
  const metadata = trill.metadata;
  return !(metadata && typeof metadata === 'object' && !Array.isArray(metadata) && Array.isArray(metadata.widgets));
}

/** *node* as a join made now reads it, or *node* itself when it is no saved join. */
export function convertedSavedJoin<T>(node: T): T {
  if (!isSavedJoin(node)) return node;
  const trill = node as unknown as TrillNode;
  const metadata: TrillNode = trill.metadata && typeof trill.metadata === 'object' && !Array.isArray(trill.metadata)
    ? { ...trill.metadata }
    : {};
  const settings = metadata[saved.setting];
  delete metadata[saved.setting];
  const given: TrillNode = settings && typeof settings === 'object' && !Array.isArray(settings) ? settings : {};
  metadata.widgets = saved.widgets.map((templateWidget) => {
    const widget: TrillNode = JSON.parse(JSON.stringify(templateWidget));
    const value = given[settingOf[widget.name]];
    if (typeof value === 'string' && widget.options.choices.includes(value)) widget.value = value;
    return widget;
  });
  return { ...trill, content: saved.code, metadata } as unknown as T;
}
