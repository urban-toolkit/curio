/**
 * What a dataflow is about: the categories the Projects rail filters by and
 * the canvas title chips show. The backend computes them
 * (`backend/app/projects/categories.py`); this module only labels, merges and
 * counts them.
 *
 * - `source` says where it came from - a use case, an example or a test Curio
 *   ships - and is absent for the account's own dataflows.
 * - `auto` is read off the saved dataflow's nodes, so it changes on save and
 *   cannot be edited.
 * - `hand` is what the user set: their own tags, city, topic and complexity.
 */

export type CategorySource = "use_case" | "example" | "test";

export type HandSection = "tags" | "city" | "topic" | "complexity";

export type HandCategories = Partial<Record<HandSection, string[]>>;

export interface AutoCategories {
  tags?: string[];
  data_type?: string[];
}

export interface DataflowCategories {
  source?: CategorySource | null;
  auto?: AutoCategories;
  hand?: HandCategories;
}

/** Everything the rail can filter by, in rail order. */
export type FacetKey =
  | "owner"
  | "source"
  | "tags"
  | "data_type"
  | "city"
  | "topic"
  | "complexity";

export const SOURCE_LABELS: Record<CategorySource, string> = {
  use_case: "Use cases",
  example: "Examples",
  test: "Tests",
};

const SOURCE_ORDER: CategorySource[] = ["use_case", "example", "test"];

export const COMPLEXITY_LEVELS = ["Beginner", "Intermediate", "Advanced"];

/** The rail's labelled sections, after the unlabelled All / Yours pair. */
export const FACET_SECTIONS: { key: Exclude<FacetKey, "owner">; label: string }[] = [
  { key: "source", label: "By source" },
  { key: "tags", label: "Tags" },
  { key: "data_type", label: "Data type" },
  { key: "city", label: "City" },
  { key: "topic", label: "Topic" },
  { key: "complexity", label: "Complexity" },
];

/** The sections a user writes, with the words the editor uses for them. */
export const HAND_SECTIONS: { key: HandSection; label: string }[] = [
  { key: "tags", label: "Tag" },
  { key: "city", label: "City" },
  { key: "topic", label: "Topic" },
  { key: "complexity", label: "Complexity" },
];

/** Sections that hold one value: a new pick replaces the old one. */
export const SINGLE_VALUE_SECTIONS: ReadonlySet<HandSection> = new Set(["complexity"]);

export const MAX_CATEGORY_LENGTH = 40;

export const OWNER_YOURS = "yours";

function unique(values: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    const key = value.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

/** Trim, collapse spaces and cap the length, as the backend does. */
export function cleanCategoryValue(raw: string): string {
  return raw.split(/\s+/).filter(Boolean).join(" ").slice(0, MAX_CATEGORY_LENGTH).trim();
}

/** A copy of `hand` with `value` added to `section` (or replacing it, for one-value sections). */
export function addHandCategory(
  hand: HandCategories,
  section: HandSection,
  raw: string,
): HandCategories {
  const value = cleanCategoryValue(raw);
  if (!value) return hand;
  const current = hand[section] ?? [];
  const next = SINGLE_VALUE_SECTIONS.has(section) ? [value] : unique([...current, value]);
  return { ...hand, [section]: next };
}

/** A copy of `hand` without `value` in `section`; an emptied section is dropped. */
export function removeHandCategory(
  hand: HandCategories,
  section: HandSection,
  value: string,
): HandCategories {
  const next = (hand[section] ?? []).filter((v) => v !== value);
  const copy = { ...hand };
  if (next.length) copy[section] = next;
  else delete copy[section];
  return copy;
}

/** The values one dataflow has in `key`, labelled for display. */
export function facetValues(categories: DataflowCategories | undefined, key: FacetKey): string[] {
  const c = categories ?? {};
  switch (key) {
    case "owner":
      return c.source ? [] : [OWNER_YOURS];
    case "source":
      return c.source ? [SOURCE_LABELS[c.source]] : [];
    case "tags":
      return unique([...(c.auto?.tags ?? []), ...(c.hand?.tags ?? [])]);
    case "data_type":
      return c.auto?.data_type ?? [];
    default:
      return c.hand?.[key] ?? [];
  }
}

/** Every category label a dataflow carries, for search. */
export function allCategoryValues(categories: DataflowCategories | undefined): string[] {
  const keys: FacetKey[] = ["source", "tags", "data_type", "city", "topic", "complexity"];
  return keys.flatMap((key) => facetValues(categories, key));
}

export type FacetSelection = Partial<Record<FacetKey, string>>;

interface HasCategories {
  categories?: DataflowCategories;
}

/** Whether `item` has the selected value in every section that has one. */
export function matchesSelection(
  item: HasCategories,
  selection: FacetSelection,
  except?: FacetKey,
): boolean {
  return (Object.entries(selection) as [FacetKey, string | undefined][]).every(
    ([key, wanted]) =>
      key === except || !wanted || facetValues(item.categories, key).includes(wanted),
  );
}

export interface FacetEntry {
  value: string;
  count: number;
}

function orderFor(key: FacetKey): string[] | null {
  if (key === "source") return SOURCE_ORDER.map((s) => SOURCE_LABELS[s]);
  if (key === "complexity") return COMPLEXITY_LEVELS;
  return null;
}

/**
 * The entries one section lists, with counts.
 *
 * Counts follow the OTHER sections' selections, so a number always says how
 * many cards clicking it would leave - the same way the Node Catalog's
 * category counts follow its status filter. Entries with no dataflow are left
 * out. Source and complexity keep their natural order; the rest sort by count.
 */
export function facetEntries<T extends HasCategories>(
  items: T[],
  key: FacetKey,
  selection: FacetSelection,
): FacetEntry[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (!matchesSelection(item, selection, key)) continue;
    for (const value of facetValues(item.categories, key)) {
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
  }
  const entries = Array.from(counts, ([value, count]) => ({ value, count }));
  const order = orderFor(key);
  if (order) {
    const rank = (v: string) => {
      const i = order.indexOf(v);
      return i === -1 ? order.length : i;
    };
    return entries.sort((a, b) => rank(a.value) - rank(b.value) || a.value.localeCompare(b.value));
  }
  return entries.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
}

/** Every value the account already uses in a hand section, for suggestions. */
export function knownValues<T extends HasCategories>(items: T[], section: HandSection): string[] {
  const values = items.flatMap((item) =>
    section === "tags" ? facetValues(item.categories, "tags") : item.categories?.hand?.[section] ?? [],
  );
  const base = section === "complexity" ? [...COMPLEXITY_LEVELS, ...values] : values;
  return unique(base).sort((a, b) => {
    if (section !== "complexity") return a.localeCompare(b);
    const ia = COMPLEXITY_LEVELS.indexOf(a);
    const ib = COMPLEXITY_LEVELS.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
  });
}
