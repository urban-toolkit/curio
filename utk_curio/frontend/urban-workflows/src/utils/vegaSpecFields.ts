/**
 * The columns a Vega-Lite spec reads from its data: every field its encodings,
 * facets and transforms name, and every `datum.x` in an expression, less the
 * fields the spec makes itself (a transform's `as`). A Vega-Lite node comparing
 * scenarios checks each scenario's input against these (utils/vegaCompare).
 *
 * Pure, and no `vega-lite` import, so it stays testable under jest.
 */

const isObject = (value: unknown): value is Record<string, any> =>
  value != null && typeof value === "object" && !Array.isArray(value);

/** `datum.x` and `datum["x y"]` in an expression. */
const DATUM = /datum(?:\.([A-Za-z_$][\w$]*)|\[\s*(['"])(.*?)\2\s*\])/g;

/** The transforms whose own key names what they read. */
const TRANSFORMS = [
  "calculate", "filter", "fold", "aggregate", "joinaggregate", "window", "bin", "timeUnit",
  "density", "regression", "loess", "quantile", "pivot", "lookup", "flatten", "impute", "stack",
];

/** Field names in a string, a list, or a `{field}` definition. */
function names(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(names);
  if (isObject(value) && typeof value.field === "string") return [value.field];
  return [];
}

/** The column a field reads: `a.b` is the nested path into column `a`, `a\.b` the column `a.b`. */
function column(field: string): string {
  return field.replace(/\\\./g, "\u0000").split(".")[0].replace(/\u0000/g, ".");
}

/** The columns *spec* reads, in the order it first reads them. */
export function specFields(spec: unknown): string[] {
  const read: string[] = [];
  const made = new Set<string>();
  const add = (field: unknown) => {
    if (typeof field !== "string" || field === "") return;
    const name = column(field);
    // A field the spec made earlier is its own, not its data's.
    if (!made.has(name) && !read.includes(name)) read.push(name);
  };
  const addExpr = (expr: unknown) => {
    if (typeof expr !== "string") return;
    for (const match of expr.matchAll(DATUM)) add(match[1] ?? match[3]);
  };

  const transform = (step: any) => {
    if (!isObject(step)) return;
    const kind = TRANSFORMS.find((key) => key in step);
    const as = names(step.as);
    switch (kind) {
      case "calculate": addExpr(step.calculate); break;
      case "filter":
        if (typeof step.filter === "string") addExpr(step.filter);
        else names(step.filter).forEach(add);
        break;
      case "fold":
        names(step.fold).forEach(add);
        if (as.length === 0) as.push("key", "value");
        break;
      case "aggregate": case "joinaggregate": case "window":
        for (const op of Array.isArray(step[kind]) ? step[kind] : []) {
          add(op?.field);
          if (typeof op?.as === "string") made.add(op.as);
        }
        names(step.sort).forEach(add);
        break;
      case "bin": case "timeUnit": add(step.field); break;
      case "density":
        add(step.density);
        if (as.length === 0) as.push("value", "density");
        break;
      case "regression": case "loess": add(step[kind]); add(step.on); break;
      case "quantile":
        add(step.quantile);
        if (as.length === 0) as.push("prob", "value");
        break;
      case "pivot": add(step.pivot); add(step.value); break;
      case "lookup":
        add(step.lookup);
        names(step.from?.fields).forEach((field) => made.add(field));
        break;
      case "flatten": names(step.flatten).forEach(add); break;
      case "impute": add(step.impute); add(step.key); break;
      case "stack": add(step.stack); break;
      default: break;
    }
    names(step.groupby).forEach(add);
    as.forEach((field) => made.add(field));
  };

  const channel = (def: unknown) => {
    for (const one of Array.isArray(def) ? def : [def]) {
      if (!isObject(one)) continue;
      add(one.field);
      names(one.condition).forEach(add);
      if (isObject(one.sort)) add(one.sort.field);
    }
  };

  const visit = (node: unknown) => {
    if (Array.isArray(node)) return node.forEach(visit);
    if (!isObject(node)) return;
    (Array.isArray(node.transform) ? node.transform : []).forEach(transform);
    if (isObject(node.facet)) {
      if ("row" in node.facet || "column" in node.facet) {
        channel(node.facet.row);
        channel(node.facet.column);
      } else channel(node.facet);
    }
    if (isObject(node.encoding)) Object.values(node.encoding).forEach(channel);
    for (const key of ["layer", "concat", "hconcat", "vconcat", "spec"]) visit(node[key]);
  };

  visit(spec);
  return read;
}
