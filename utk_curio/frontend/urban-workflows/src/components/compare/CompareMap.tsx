/**
 * The Compare Scenarios node's difference map (#662): the node's output drawn
 * by the Autark node's own map code (`useAutkGrammarBehavior`) into the node's
 * `autk-grammar-map-<nodeId>` canvas, as an Autark node draws its input, from
 * a document the view writes (`utils/compare/compareDifference`).
 *
 * The difference is the node's output, which its run has already handed on,
 * so the map hands nothing on and links to nothing; and a map that cannot draw
 * says so here, leaving the node's own outcome as its run left it.
 *
 * Loaded only when a difference is drawn, so the node's other views never
 * load the map code.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useAutkGrammarBehavior } from "../../adapters/node/autkGrammarBehavior";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../registry/types";
import styles from "./CompareScenarios.module.css";

/** What the map's last run came to, and the document it was asked to draw. */
type Outcome = { code: string; content: string; doc: string };

/** The column or band a document colors by, for the page to tell which map it shows. */
function coloredBy(docText: string): string {
  try {
    return String(JSON.parse(docText)?.map?.layerRefs?.[0]?.getFnv ?? "");
  } catch {
    return "";
  }
}

export default function CompareMap({
  nodeId,
  difference,
  docText,
}: {
  nodeId: string;
  /** The node's output: the difference's reference. */
  difference: { path: string; dataType?: string };
  /** The Autark document that draws it. */
  docText: string;
}) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  // The document the map was last asked to draw, which its outcome is for.
  const requested = useRef(docText);
  // Only what the Autark node's map reads: whose canvas it is, the input it
  // draws and its document. No callbacks, so nothing is handed on.
  const data = useMemo(
    () => ({ nodeId, input: difference, code: docText, defaultCode: docText }) as unknown as NodeBehaviorData,
    [nodeId, difference, docText],
  );
  const state = useMemo(
    () => ({
      output: outcome ?? { code: "", content: "" },
      setOutput: (o: { code: string; content: string }) => setOutcome({ ...o, doc: requested.current }),
      code: docText,
    }) as unknown as UseNodeStateReturn,
    [outcome, docText],
  );
  const { applyGrammar, contentComponent } = useAutkGrammarBehavior(data, state, { marksNodeErrored: false });

  useEffect(() => {
    requested.current = docText;
    setOutcome(null);
    void applyGrammar?.(docText);
    // A new difference or a new document draws again; the hook's own
    // functions change on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [difference, docText]);

  // An outcome of the document before this one says nothing about this one.
  const current = outcome?.doc === docText ? outcome : null;
  const drawn = current?.code === "success";
  const problem = current?.code === "error" ? String(current.content ?? "") : null;
  return (
    <div
      className={styles.map}
      data-compare-map-state={drawn ? "drawn" : problem ? "problem" : "drawing"}
      data-compare-map-color={coloredBy(docText)}
    >
      <div className={styles.mapCanvas}>{contentComponent}</div>
      {problem ? (
        <p className={styles.problem} data-compare-map-problem="true">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
