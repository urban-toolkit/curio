import React from "react";

import { formatBytes } from "../../datasets/catalog/datasetDetailHelpers";
import {
  MODEL_ORIGIN_LABEL,
  MODEL_RUNTIME_LABEL,
  MODEL_TASK_LABEL,
  type ModelRow,
} from "../../../services/modelCatalog";

/**
 * What the Model Catalog says about one model, for its browse drawer, its
 * canvas card and its details modal alike, as `discoverySourceFacts` is for a
 * source. Each view lays the rows out in its own container, and none of them
 * can disagree with another about a model.
 */

export interface ModelFact {
  label: string;
  value: React.ReactNode;
}

/** `"19 labels"`, singular for one. */
export function modelLabelCount(model: Pick<ModelRow, "labelCount">): string {
  return `${model.labelCount} ${model.labelCount === 1 ? "label" : "labels"}`;
}

/** `"23.1 MB"`, or null when the manifest does not say. */
export function modelSizeLabel(model: Pick<ModelRow, "sizeBytes">): string | null {
  return model.sizeBytes > 0 ? formatBytes(model.sizeBytes) : null;
}

/** `"1024 × 512, uint8"`, or null for a model that reads any size. */
export function modelInputLabel(model: Pick<ModelRow, "input">): string | null {
  if (!model.input) return null;
  return `${model.input.width} × ${model.input.height}, ${model.input.dtype}`;
}

/** The card meta line: runtime, label count, size. */
export function modelMetaLine(model: ModelRow): string {
  return [MODEL_RUNTIME_LABEL[model.runtime], modelLabelCount(model), modelSizeLabel(model)]
    .filter(Boolean)
    .join(" · ");
}

export function modelInfoRows(model: ModelRow): ModelFact[] {
  const input = modelInputLabel(model);
  const size = modelSizeLabel(model);
  const rows: (ModelFact | null)[] = [
    { label: "Runtime", value: MODEL_RUNTIME_LABEL[model.runtime] ?? model.runtime },
    { label: "Task", value: MODEL_TASK_LABEL[model.task] ?? model.task },
    input ? { label: "Input", value: input } : null,
    { label: "Labels", value: String(model.labelCount) },
    size ? { label: "Size", value: size } : null,
    { label: "Version", value: model.version },
    { label: "License", value: model.license || "Unknown" },
    { label: "Origin", value: MODEL_ORIGIN_LABEL[model.origin] ?? model.origin },
    model.homepage
      ? {
          label: "Homepage",
          value: (
            <a href={model.homepage} target="_blank" rel="noreferrer noopener">
              {hostOf(model.homepage)} ↗
            </a>
          ),
        }
      : null,
  ];
  return rows.filter((row): row is ModelFact => row != null);
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
