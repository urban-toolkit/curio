import { currentCode } from "../codeOnlyUsage";
import type { ModelBlockPayload, PackagePayload } from "./types";
import { hasRewritableModelCall, modelIdsInCode, rewriteFirstModelCall } from "./modelCode";
import { MODEL_TYPE_LABEL } from "./modelPackages";
import {
  beginPackageCardDrag,
  endPackageCardDrag,
  writePackageCardDragData,
  type PackageCardNode,
} from "./packageCardDrag";

/**
 * A model package (kind `model`) on the canvas: dragged from the Model
 * Catalog onto a node, whose `curio_load_model("<id>")` call it then names
 * when the node runs a model of its known type, or onto the canvas, where it is its
 * package's card and becomes the package's node. A model's id is its
 * package's `packageId`.
 */

/** What a model drag carries: enough to rewrite a call, to check the node's
 *  type and to say so. */
export interface ModelDragPayload {
  modelId: string;
  name: string;
  runtime: ModelBlockPayload["runtime"];
  type?: ModelBlockPayload["type"];
}

/** The binding a node keeps for the model it runs, beside its code. Saved at
 *  `metadata.modelRefs` by `TrillGenerator`, as `datasetRefs` is. */
export interface ModelRef {
  id: string;
  name: string;
}

/** A model by its id and name: a model package's row, or a drag of one. */
type ModelLike = Pick<PackagePayload, "packageId" | "name"> | ModelDragPayload;

function modelIdOf(model: ModelLike): string {
  return "modelId" in model ? model.modelId : model.packageId;
}

export const MODEL_DRAG_MIME = "application/x-curio-model";
const MODEL_DRAG_PLAIN_PREFIX = "curio-model:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activeModelDrag: ModelDragPayload | null = null;

/** The drag of a model package. Its `model` block says how its weights run,
 *  and which type of model it is. */
export function createModelDragPayload(model: PackagePayload): ModelDragPayload {
  return {
    modelId: model.packageId,
    name: model.name,
    runtime: model.model?.runtime ?? "onnx",
    ...(model.model?.type ? { type: model.model.type } : {}),
  };
}

function parseModelDragJson(raw: string): ModelDragPayload | null {
  if (!raw) return null;
  try {
    const payload = JSON.parse(raw) as Partial<ModelDragPayload>;
    if (!payload.modelId || !payload.name) return null;
    return payload as ModelDragPayload;
  } catch {
    return null;
  }
}

/** Call from `dragStart` on model rows and cards. */
export function beginModelDrag(model: PackagePayload): ModelDragPayload {
  const payload = createModelDragPayload(model);
  activeModelDrag = payload;
  return payload;
}

/** Call from `dragEnd` so a stale payload is not reused. */
export function endModelDrag(): void {
  activeModelDrag = null;
}

/** Write drag data (custom MIME + text/plain fallback for the drop handler). */
export function writeModelDragData(dataTransfer: DataTransfer, payload: ModelDragPayload): void {
  const json = JSON.stringify(payload);
  dataTransfer.setData(MODEL_DRAG_MIME, json);
  dataTransfer.setData("text/plain", `${MODEL_DRAG_PLAIN_PREFIX}${json}`);
  dataTransfer.effectAllowed = "copy";
}

export function readModelDragPayload(dataTransfer: DataTransfer): ModelDragPayload | null {
  if (activeModelDrag) return activeModelDrag;
  const fromMime = parseModelDragJson(dataTransfer.getData(MODEL_DRAG_MIME));
  if (fromMime) return fromMime;
  const plain = dataTransfer.getData("text/plain");
  if (plain.startsWith(MODEL_DRAG_PLAIN_PREFIX)) {
    return parseModelDragJson(plain.slice(MODEL_DRAG_PLAIN_PREFIX.length));
  }
  return null;
}

export function hasModelDrag(dataTransfer: DataTransfer): boolean {
  if (activeModelDrag) return true;
  const types = Array.from(dataTransfer.types || []);
  return types.includes(MODEL_DRAG_MIME);
}

/**
 * Call from `dragStart` on a model's card or palette row: the drag is the
 * model, for a node that runs one, and its package's card, which the canvas
 * takes as the Node Catalog drawer's cards (`usePackageCardDrop`).
 */
export function writeModelCardDrag(dataTransfer: DataTransfer, model: PackagePayload): void {
  const card = beginPackageCardDrag(model);
  if (card) writePackageCardDragData(dataTransfer, card);
  writeModelDragData(dataTransfer, beginModelDrag(model));
}

/** Call from `dragEnd` on a model's card or palette row. */
export function endModelCardDrag(): void {
  endPackageCardDrag();
  endModelDrag();
}

/**
 * What the node a card's drop makes opens with, beside its type and place.
 * A model package's node is bound to its model (`modelRefs`) and, once its
 * template's code has arrived (*starter*), opens with that code naming the
 * model: its own code, or the default cell of the model's type the backend
 * writes for a template without one. A node package's node opens with its
 * template's code as a palette drop does, so nothing is added.
 */
export function packageCardNodeOptions(
  node: PackageCardNode,
  starter: string | undefined,
): { code?: string; modelRefs?: ModelRef[] } {
  if (!node.model) return {};
  const model = { packageId: node.model.id, name: node.model.name };
  const made = modelNodeForCanvas([{ nodeType: node.nodeType, label: node.label, code: starter }], model);
  if (made) return { code: made.code, modelRefs: made.modelRefs };
  return {
    ...(starter !== undefined ? { code: starter } : {}),
    modelRefs: [{ id: model.packageId, name: model.name }],
  };
}

/**
 * The ids of the canvas *nodes* that name the model *modelId* in their code
 * alone: not a node of its package (whose type keeps the package in the
 * dataflow), and not bound to it (`modelRefs`, which keeps it too). Removing
 * the model leaves their code as it is, which the Remove dialog says.
 */
export function nodesNamingModelInCodeOnly(
  nodes: ReadonlyArray<{ id: string; data?: any }>,
  modelId: string,
): string[] {
  return nodes
    .filter(({ data }) => {
      if (String(data?.nodeType ?? "").startsWith(`${modelId}/`)) return false;
      if ((data?.modelRefs || []).some((ref: any) => String(ref?.id ?? "").split("@")[0] === modelId)) return false;
      return modelIdsInCode(currentCode(data)).includes(modelId);
    })
    .map((node) => node.id);
}

/**
 * The type of model a node runs: the type of the first model its code names
 * whose type *typeOf* knows, else *ownType*, the type of the model package
 * the node comes from. `undefined` when neither is known.
 */
export function nodeModelType(
  data: any,
  typeOf: (modelId: string) => string | undefined,
  ownType?: string,
): string | undefined {
  for (const id of modelIdsInCode(currentCode(data))) {
    const type = typeOf(id);
    if (type) return type;
  }
  return ownType || undefined;
}

function modelTypeText(type: string): string {
  const label = (MODEL_TYPE_LABEL as Record<string, string>)[type] ?? type;
  return label.charAt(0).toLowerCase() + label.slice(1);
}

/**
 * Why a node that runs models of *nodeType* does not take *model*: a model
 * swaps another of its own type only, so the node takes it only when both
 * types are known and equal. `null` when the node takes it; else the reason,
 * an unknown type (the node's said first) or the two types.
 */
export function modelSwapRefusal(
  nodeType: string | null | undefined,
  model: Pick<ModelDragPayload, "name" | "type">,
): string | null {
  if (!nodeType) return `This node's model type is unknown, so it does not take ${model.name}.`;
  if (!model.type) return `The model type of ${model.name} is unknown, so this node does not take it.`;
  if (nodeType === model.type) return null;
  const dropped = modelTypeText(model.type);
  const article = /^[aeiou]/i.test(dropped) ? "an" : "a";
  return `This node runs ${modelTypeText(nodeType)} models, and ${model.name} is ${article} ${dropped} model.`;
}

/**
 * True when a dropped model has somewhere to go: the node's code calls
 * `curio_load_model("...")` with a literal string. Unlike a dataset, a model is not
 * written into code that does not ask for one, so a node that never calls
 * `curio_load_model` cannot take it. Checks the same code `applyModelToNodeData`
 * rewrites, so a drop that is accepted always changes something.
 */
export function canApplyModelToNode(data: any): boolean {
  return hasRewritableModelCall(currentCode(data));
}

/**
 * *data* running *model*: the id inside its code's first literal
 * `curio_load_model(...)` call becomes the model's, in the call's own quotes, and
 * `modelRefs` names that one model. *data* itself comes back when its code has
 * no such call. Pure: nothing outside the returned object changes.
 */
export function applyModelToNodeData(data: any, model: ModelLike): any {
  const code = currentCode(data);
  const modelId = modelIdOf(model);
  const rewritten = code == null ? null : rewriteFirstModelCall(code, modelId);
  if (rewritten == null) return data;
  const modelRefs: ModelRef[] = [{ id: modelId, name: model.name }];
  return {
    ...data,
    code: rewritten,
    defaultCode: rewritten,
    modelRefs,
  };
}

/** A node template, as far as a model dropped on the canvas asks about it. */
export interface ModelDropTemplate {
  nodeType: string;
  label: string;
  /** The code a fresh node of it opens with, when it has any. */
  code: string | undefined;
  packageName?: string;
}

/** The node a model dropped on the canvas becomes. */
export interface ModelCanvasNode extends ModelDropTemplate {
  code: string;
  modelRefs: ModelRef[];
}

/**
 * What a model dropped on the empty canvas becomes, as a dataset dropped there
 * becomes a Data Loading node: a node of the template whose code already names
 * *model*, made to run it, else of the first of *templates* whose code calls
 * `curio_load_model("...")`, with that call naming *model*. So a model with a
 * node of its own (Deep Umbra, Accumulated Shadow) gets that node, not an
 * Image Segmentation one. `null` when none of them runs a model. Pure, like
 * `applyModelToNodeData`, which it goes through.
 */
export function modelNodeForCanvas(
  templates: ModelDropTemplate[],
  model: ModelLike,
): ModelCanvasNode | null {
  const modelId = modelIdOf(model);
  const own = templates.filter((template) => modelIdsInCode(template.code).includes(modelId));
  for (const template of [...own, ...templates]) {
    const applied = applyModelToNodeData({ code: template.code }, model);
    if (!applied.modelRefs) continue;
    return { ...template, code: applied.code, modelRefs: applied.modelRefs };
  }
  return null;
}

/**
 * Every model id a canvas node is linked to: the `modelRefs` a drop wrote, and
 * every literal call in its code and its template's. Mirrors
 * `nodeLinkedDatasetIds`, for the same reason: code that was typed or generated
 * names a model without any binding at all. A ref counts only while the code
 * still names its id: a hand edit to another model leaves the drop's
 * `modelRefs` behind, saved with the node.
 */
export function nodeLinkedModelIds(data: any): string[] {
  const named = [...modelIdsInCode(data?.code), ...modelIdsInCode(data?.defaultCode)];
  const ids = new Set<string>();
  for (const ref of data?.modelRefs || []) {
    if (typeof ref?.id === "string" && named.includes(ref.id)) ids.add(ref.id);
  }
  for (const id of named) ids.add(id);
  return Array.from(ids);
}
