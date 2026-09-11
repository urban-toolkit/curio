/**
 * Did this node's render actually draw anything? (memo dev/136)
 *
 * dev/133 made an empty RESULT a verdict and dev/134 made a document's
 * STRUCTURE a verdict. Neither sees an empty PICTURE: a Vega-Lite spec can be
 * schema-valid, reference columns that exist, compile without an error and
 * draw nothing at all, and an Autark map whose every `layerRef` was dropped
 * renders a grey canvas — both reported as success until now.
 *
 * The rule's ORDER is the attribution, and attribution is the point: the fix
 * for an empty plot depends entirely on what emptied it.
 *
 * 1. `no-layers`      — the document names data this dataflow does not produce.
 * 2. `no-input-rows`  — nothing arrived; the UPSTREAM is what must change.
 * 3. `nothing-drawn`  — rows arrived and the document drew none of them.
 *
 * Pure and total: no counts means no claim (an unverifiable emptiness is never
 * reported), and nothing here reads or forwards the data itself.
 */

export type RenderCause = "no-layers" | "no-input-rows" | "nothing-drawn" | null;

export interface RenderCounts {
  /** Rows/features handed to the renderer. `undefined` = could not count. */
  rowsIn?: number;
  /**
   * Rows whose ENCODED fields hold a usable value (dev/137). A chart can be
   * handed rows that are all null in the field it plots — the owner's
   * `7a27b702` joined with `how="left"` on keys that cannot match — and then
   * the renderer either drops them (no marks) or draws zero-extent ones. Both
   * are an empty picture, so the data decides rather than the scene graph.
   * `undefined` = could not count.
   */
  usableRows?: number;
  /** The field(s) whose values were counted, for the message. */
  usableFields?: string[];
  /** Marks/items the renderer actually drew. `undefined` = could not count. */
  drawn?: number;
  /** Layers the document asked for (Autark). */
  layersRequested?: number;
  /** Layers that survived resolution and were drawn (Autark). */
  layersDrawn?: number;
  /** The data the document asked for, for the `no-layers` message. */
  requestedRefs?: string[];
  /** What the dataflow actually produced, for the same message. */
  availableRefs?: string[];
}

export interface RenderOutcome {
  empty: boolean;
  cause: RenderCause;
  /** One short sentence, bounded — the node's error text and the journal's. */
  message: string;
}

const MESSAGE_CHARS = 400;
const NAMES_SHOWN = 6;

function names(list: string[] | undefined): string {
  const shown = (list ?? []).filter((n) => typeof n === "string" && n).slice(0, NAMES_SHOWN);
  if (!shown.length) return "none";
  const more = (list ?? []).length - shown.length;
  return shown.join(", ") + (more > 0 ? `, … ${more} more` : "");
}

function bounded(text: string): string {
  return text.length > MESSAGE_CHARS ? text.slice(0, MESSAGE_CHARS - 1) + "…" : text;
}

const NOT_EMPTY: RenderOutcome = { empty: false, cause: null, message: "" };

/** The one decision, shared by every renderer Curio owns. */
export function renderOutcome(counts: RenderCounts): RenderOutcome {
  const { rowsIn, drawn, layersRequested, layersDrawn } = counts;

  // 1. Every layer the document asked for was dropped: there is nothing to
  //    draw FROM, whatever the data holds. The document is what must change.
  if (
    typeof layersRequested === "number" && layersRequested > 0 &&
    typeof layersDrawn === "number" && layersDrawn === 0
  ) {
    return {
      empty: true,
      cause: "no-layers",
      message: bounded(
        `rendered nothing — every layer this document asks for names data the ` +
        `dataflow does not produce (asked for: ${names(counts.requestedRefs)}; ` +
        `available: ${names(counts.availableRefs)}). Point the layerRefs at a ` +
        `table this node's input actually provides.`,
      ),
    };
  }

  // 2. Nothing arrived. The document is NOT at fault — dev/133's rule: a node
  //    is never blamed for emptiness it did not create.
  if (typeof rowsIn === "number" && rowsIn === 0) {
    return {
      empty: true,
      cause: "no-input-rows",
      message: bounded(
        "rendered nothing — 0 rows arrived at this node, so there was nothing " +
        "to draw. The upstream node that feeds it is what must change; this " +
        "document is not at fault.",
      ),
    };
  }

  // 3. Rows arrived and NONE of them hold a value in the fields this document
  //    plots. Counted from the data, so a renderer that draws a zero-extent
  //    mark for a null cannot read as "drawn" (dev/137).
  if (
    typeof rowsIn === "number" && rowsIn > 0 &&
    typeof counts.usableRows === "number" && counts.usableRows === 0
  ) {
    const fields = names(counts.usableFields);
    return {
      empty: true,
      cause: "nothing-drawn",
      message: bounded(
        `rendered nothing — ${rowsIn} row${rowsIn === 1 ? "" : "s"} arrived and ` +
        `every value of ${fields} is null, so there is nothing to plot. The ` +
        "upstream node that produces those columns is what must change — a " +
        "join that matched nothing leaves rows with no data in them.",
      ),
    };
  }

  // 4. Rows arrived and none of them became a mark: an encoding, a transform
  //    or a scale domain removed every one. The document is what must change.
  if (
    typeof rowsIn === "number" && rowsIn > 0 &&
    typeof drawn === "number" && drawn === 0
  ) {
    return {
      empty: true,
      cause: "nothing-drawn",
      message: bounded(
        `rendered nothing — ${rowsIn} row${rowsIn === 1 ? "" : "s"} arrived and ` +
        "no mark was drawn: an encoding, a transform or a scale domain removed " +
        "every row. Check that the encoded fields hold values (not all null) " +
        "and that no filter or domain excludes the data.",
      ),
    };
  }

  return NOT_EMPTY;
}

/**
 * A note for a render that DID draw, or "" — the dropped layers a partial
 * resolution swallowed. dev/136: dropping is the right recovery, but a
 * `console.warn` was the only trace it ever left.
 */
export function partialRenderNote(counts: RenderCounts): string {
  const { layersRequested, layersDrawn } = counts;
  if (
    typeof layersRequested !== "number" || typeof layersDrawn !== "number" ||
    layersDrawn <= 0 || layersDrawn >= layersRequested
  ) {
    return "";
  }
  return bounded(
    `drew ${layersDrawn} of ${layersRequested} layers — the rest name data the ` +
    `dataflow does not produce (asked for: ${names(counts.requestedRefs)}; ` +
    `available: ${names(counts.availableRefs)}).`,
  );
}
