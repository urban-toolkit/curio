import React from "react";

import { formatBytes } from "../../datasets/catalog/datasetDetailHelpers";
import {
  MODEL_RUNTIME_LABEL,
  MODEL_TYPE_LABEL,
  type ModelBlockPayload,
  type PackagePayload,
} from "../../../services/packages";

/**
 * What the Model Catalog says about one model package, for the cards, the
 * page's side drawer and the details modal alike, as `discoverySourceFacts`
 * is for a source. Each view lays the rows out in its own container, and none
 * of them can disagree with another about a model. A model is a package of
 * kind `model`: its `model` block says how its weights run, its `license` is
 * its code's.
 */

export interface ModelFact {
  label: string;
  value: React.ReactNode;
}

type ModelPackage = PackagePayload & { model: ModelBlockPayload };

/** `"19 labels"`, singular for one. */
export function modelLabelCount(pkg: ModelPackage): string {
  const count = pkg.model.labels.length;
  return `${count} ${count === 1 ? "label" : "labels"}`;
}

/** `"22.0 MB"`, or null when the manifest does not say. */
export function modelSizeLabel(pkg: ModelPackage): string | null {
  return pkg.model.sizeBytes > 0 ? formatBytes(pkg.model.sizeBytes) : null;
}

/** `"2048 × 1024, uint8"`, or null for a model that reads any size. */
export function modelInputLabel(pkg: ModelPackage): string | null {
  const input = pkg.model.input;
  return input ? `${input.width} × ${input.height}, ${input.dtype}` : null;
}

export function modelRuntimeLabel(pkg: ModelPackage): string {
  return MODEL_RUNTIME_LABEL[pkg.model.runtime] ?? pkg.model.runtime;
}

export function modelTypeLabel(pkg: ModelPackage): string {
  return MODEL_TYPE_LABEL[pkg.model.type] ?? pkg.model.type;
}

/** The node a drop of the model creates: its package's own. */
export function modelNodeLabel(pkg: ModelPackage): string | null {
  const template = pkg.templates[0];
  return template ? template.label || template.templateId : null;
}

/** The card meta line: runtime, label count (a model with none, its type
 *  instead), size. */
export function modelMetaLine(pkg: ModelPackage): string {
  const kind = pkg.model.labels.length > 0 ? modelLabelCount(pkg) : modelTypeLabel(pkg);
  return [modelRuntimeLabel(pkg), kind, modelSizeLabel(pkg)].filter(Boolean).join(" · ");
}

/** The model's rows for the details: how its weights run, the code's license
 *  (the package's) beside the weights' license, the weights' publisher and
 *  homepage, the node a drop creates, and whether the weights download on
 *  first use. */
export function modelInfoRows(pkg: ModelPackage, weightsLicense?: React.ReactNode): ModelFact[] {
  const input = modelInputLabel(pkg);
  const size = modelSizeLabel(pkg);
  const node = modelNodeLabel(pkg);
  const rows: (ModelFact | null)[] = [
    { label: "Type", value: modelTypeLabel(pkg) },
    { label: "Runtime", value: modelRuntimeLabel(pkg) },
    input ? { label: "Input size", value: input } : null,
    pkg.model.labels.length > 0 ? { label: "Labels", value: String(pkg.model.labels.length) } : null,
    size ? { label: "Size", value: size } : null,
    { label: "Code license", value: pkg.license || "Unknown" },
    { label: "Weights license", value: weightsLicense ?? (pkg.model.license || "Unknown") },
    pkg.model.publisher ? { label: "Weights publisher", value: pkg.model.publisher } : null,
    pkg.model.homepage
      ? {
          label: "Homepage",
          value: (
            <a href={pkg.model.homepage} target="_blank" rel="noreferrer noopener">
              {hostOf(pkg.model.homepage)} ↗
            </a>
          ),
        }
      : null,
    node ? { label: "Node", value: node } : null,
    pkg.model.downloadsOnFirstUse ? { label: "Weights", value: "Downloads on first use" } : null,
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
