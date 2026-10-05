/**
 * The Compare Scenarios node's What differs tab (#662): each lever that
 * differs between the compared scenarios, with the widget values and the code
 * lines that changed, and the levers only some of them have.
 */
import React from "react";
import type { WidgetValue } from "../../utils/widgets/widgetModel";
import type { ComparedScenario, WhatDiffers } from "../../utils/compare/whatDiffers";
import { listOf } from "../../utils/compare/compareInputs";
import styles from "./CompareScenarios.module.css";

function shownValue(value: WidgetValue | undefined): string {
  if (value === undefined) return "no such widget";
  return typeof value === "string" ? value : JSON.stringify(value);
}

export function WhatDiffersList({
  compared,
  differs,
}: {
  compared: readonly ComparedScenario[];
  differs: WhatDiffers;
}) {
  if (compared.length < 2) {
    return (
      <p className={styles.empty} data-compare-differs-empty="true">
        Connect the outcomes of two scenarios or more to see what differs between them.
      </p>
    );
  }
  const nameOf = (id: string) => compared.find((c) => c.scenario.id === id)?.scenario.name ?? id;
  const colorOf = (id: string) => compared.find((c) => c.scenario.id === id)?.scenario.color;
  const reference = compared[0].scenario;
  const swatch = (id: string) => (
    <span className={styles.swatch} style={{ ["--scenario-color" as any]: colorOf(id) }} aria-hidden="true" />
  );

  return (
    <div data-compare-differs="true">
      {differs.differences.length === 0 ? (
        <p className={styles.empty}>The scenarios&apos; levers are the same: no widget value or code line differs.</p>
      ) : (
        <ul className={styles.levers}>
          {differs.differences.map((lever) => (
            <li key={lever.key} className={styles.lever} data-compare-lever={lever.key}>
              <span className={styles.leverName}>{lever.label}</span>
              {lever.onlyIn ? (
                <span className={styles.onlyIn} data-compare-only-in={lever.onlyIn.join(" ")}>
                  only in {listOf(lever.onlyIn.map(nameOf))}
                </span>
              ) : null}
              {lever.widgets.length > 0 ? (
                <ul className={styles.values}>
                  {lever.widgets.map((widget) => (
                    <li key={widget.name} className={styles.value} data-compare-widget={widget.name}>
                      <span className={styles.widgetName}>{widget.name}</span>
                      {widget.values.map(({ scenarioId, value }) => (
                        <span key={scenarioId} data-compare-value={scenarioId}>
                          {swatch(scenarioId)}
                          {nameOf(scenarioId)}: {shownValue(value)}
                        </span>
                      ))}
                    </li>
                  ))}
                </ul>
              ) : null}
              {lever.code.map((change) => (
                <div key={change.scenarioId} data-compare-code={change.scenarioId}>
                  <span className={styles.onlyIn}>
                    Code lines of {nameOf(change.scenarioId)} against {reference.name}
                  </span>
                  <pre className={`nowheel ${styles.code}`}>
                    {change.removed.map((line, i) => (
                      <div key={`r${i}`} className={styles.removed} data-compare-code-removed="true">
                        {`- ${line}`}
                      </div>
                    ))}
                    {change.added.map((line, i) => (
                      <div key={`a${i}`} className={styles.added} data-compare-code-added="true">
                        {`+ ${line}`}
                      </div>
                    ))}
                  </pre>
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
      {differs.same > 0 ? (
        <p className={styles.same} data-compare-same={differs.same}>
          {differs.same === 1 ? "1 other lever is" : `${differs.same} other levers are`} the same in every scenario.
        </p>
      ) : null}
    </div>
  );
}
