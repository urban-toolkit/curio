/**
 * The Edit Features node's map (#662): the node's input drawn by the Autark
 * node's own map code (`useAutkGrammarBehavior`) into the node's
 * `autk-grammar-map-<nodeId>` canvas, from a document whose layer to edit is
 * pickable, as an Autark node draws its input. A pick reaches the body as the
 * input rows it names, the way an Autark node reports a pick to the flow.
 *
 * The map hands nothing on: the node's output is what its code makes of the
 * edit list. A map that cannot draw says so here, leaving the node's own
 * outcome as its run left it.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useAutkGrammarBehavior } from "../../adapters/node/autkGrammarBehavior";
import type { NodeBehaviorData, UseNodeStateReturn } from "../../registry/types";
import styles from "./EditFeatures.module.css";

/** What the map's last run came to, and the document it was asked to draw. */
type Outcome = { code: string; content: string; doc: string };

export default function EditFeaturesMap({
  nodeId,
  input,
  docText,
  onPick,
}: {
  nodeId: string;
  /** The node's input, as the flow handed it on. */
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
  const { applyGrammar, contentComponent } = useAutkGrammarBehavior(data, state, { marksNodeErrored: false });

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
    <div className={styles.map} data-edit-map-state={drawn ? "drawn" : problem ? "problem" : "drawing"}>
      <div className={styles.mapCanvas}>{contentComponent}</div>
      {problem ? (
        <p className={styles.problem} data-edit-map-problem="true">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
