/**
 * The Map Edits node's map: the node's layers as its edits leave them, drawn
 * by the Autark node's own map code (`useAutkGrammarBehavior`) into the node's
 * `autk-grammar-map-<nodeId>` canvas, from a document whose layer to edit is
 * pickable, as an Autark node draws its input. The input it draws is inline
 * (utils/mapEdits/mapEditsLayers `mapInput`), so an edit draws again at once,
 * with no run. Only the first draw frames the layers; a later one keeps the
 * view the person zoomed and panned to. A pick reaches the body as the rows
 * it names, the way an Autark node reports a pick to the flow.
 *
 * The map hands nothing on: the node's output is what its code makes of its
 * input. A map that cannot draw says so here, leaving the node's own outcome
 * as its run left it.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useAutkGrammarBehavior } from "../../adapters/node/autkGrammarBehavior";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../registry/types";
import styles from "./MapEdits.module.css";

/** What the map's last run came to, and the document it was asked to draw. */
type Outcome = { code: string; content: string; doc: string };

export default function MapEditsMap({
  nodeId,
  input,
  docText,
  onPick,
}: {
  nodeId: string;
  /** The layers to draw, inline, the one to edit as the edits leave it. */
  input: unknown;
  /** The Autark document that draws it. */
  docText: string;
  /** A pick on the map: the selection as an Autark node reports it. */
  onPick: (details: Record<string, any>) => void;
}) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const requested = useRef(docText);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  // Only what the Autark node's map reads: whose canvas it is, the input it
  // draws, its document, and where a pick goes. Nothing is handed on.
  const data = useMemo(
    () => ({
      nodeId,
      input,
      code: docText,
      defaultCode: docText,
      interactionsCallback: (details: Record<string, any>) => pickRef.current(details),
    }) as unknown as NodeBehaviorData,
    [nodeId, input, docText],
  );
  const state = useMemo(
    () => ({
      output: outcome ?? { code: "", content: "" },
      setOutput: (o: { code: string; content: string }) => setOutcome({ ...o, doc: requested.current }),
      code: docText,
    }) as unknown as UseNodeStateReturn,
    [outcome, docText],
  );
  // A draw of the map is not a run of the node: the provenance drawer lists the
  // node's own runs and edits. A draw after an edit keeps the view.
  const { applyGrammar, contentComponent } = useAutkGrammarBehavior(data, state, {
    marksNodeErrored: false,
    recordsProvenance: false,
    keepsView: true,
  });

  useEffect(() => {
    requested.current = docText;
    setOutcome(null);
    void applyGrammar?.(docText);
    // A new input or a new document draws again; the hook's own functions
    // change on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, docText]);

  const current = outcome?.doc === docText ? outcome : null;
  const drawn = current?.code === "success";
  const problem = current?.code === "error" ? String(current.content ?? "") : null;
  return (
    <div className={styles.map} data-map-edits-map-state={drawn ? "drawn" : problem ? "problem" : "drawing"}>
      <div className={styles.mapCanvas}>{contentComponent}</div>
      {problem ? (
        <p className={styles.problem} data-map-edits-map-problem="true">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
