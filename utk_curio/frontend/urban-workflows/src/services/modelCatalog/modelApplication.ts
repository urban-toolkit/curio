import type { ModelRow, ModelRuntime } from "./modelCatalogTypes";
import { hasRewritableModelCall, modelIdsInCode, rewriteFirstModelCall } from "./modelCode";

/** What a model drag carries: enough to rewrite a call and to say so. */
export interface ModelDragPayload {
  modelId: string;
  name: string;
  runtime: ModelRuntime;
}

/** The binding a node keeps for the model it runs, beside its code. Saved at
 *  `metadata.modelRefs` by `TrillGenerator`, as `datasetRefs` is. */
export interface ModelRef {
  id: string;
  name: string;
}

type ModelLike = Pick<ModelRow, "id" | "name"> | ModelDragPayload;

function modelIdOf(model: ModelLike): string {
  return "modelId" in model ? model.modelId : model.id;
}

export const MODEL_DRAG_MIME = "application/x-curio-model";
const MODEL_DRAG_PLAIN_PREFIX = "curio-model:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activeModelDrag: ModelDragPayload | null = null;

export function createModelDragPayload(model: ModelRow): ModelDragPayload {
  return { modelId: model.id, name: model.name, runtime: model.runtime };
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
export function beginModelDrag(model: ModelRow): ModelDragPayload {
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

/** The code a node runs: its own once it has any, else its template's. */
function currentCode(data: any): string | undefined {
  if (typeof data?.code === "string") return data.code;
  if (typeof data?.defaultCode === "string") return data.defaultCode;
  return undefined;
}

/**
 * True when a dropped model has somewhere to go: the node's code calls
 * `curio_model("...")` with a literal string. Unlike a dataset, a model is not
 * written into code that does not ask for one, so a node that never calls
 * `curio_model` cannot take it. Checks the same code `applyModelToNodeData`
 * rewrites, so a drop that is accepted always changes something.
 */
export function canApplyModelToNode(data: any): boolean {
  return hasRewritableModelCall(currentCode(data));
}

/**
 * *data* running *model*: the id inside its code's first literal
 * `curio_model(...)` call becomes the model's, in the call's own quotes, and
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
 * becomes a Data Loading node: a node of the first of *templates* whose code
 * calls `curio_model("...")`, with that call naming *model*. `null` when none
 * of them runs a model. Pure, like `applyModelToNodeData`, which it goes through.
 */
export function modelNodeForCanvas(
  templates: ModelDropTemplate[],
  model: ModelLike,
): ModelCanvasNode | null {
  for (const template of templates) {
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
 * names a model without any binding at all.
 */
export function nodeLinkedModelIds(data: any): string[] {
  const ids = new Set<string>();
  for (const ref of data?.modelRefs || []) {
    if (typeof ref?.id === "string" && ref.id) ids.add(ref.id);
  }
  for (const id of modelIdsInCode(data?.code)) ids.add(id);
  for (const id of modelIdsInCode(data?.defaultCode)) ids.add(id);
  return Array.from(ids);
}
