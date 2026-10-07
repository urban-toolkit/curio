import type { ModelRow, ModelRuntime, ModelTask } from "./modelCatalogTypes";
import { hasRewritableModelCall, modelIdsInCode, rewriteFirstModelCall } from "./modelCode";

/** What a model drag carries: enough to rewrite a call and to say so. */
export interface ModelDragPayload {
  modelId: string;
  name: string;
  runtime: ModelRuntime;
  /** What it does, so a drop goes only to a node that runs that kind of model. */
  task?: ModelTask;
  /** The node that runs it, when its manifest names one (`ModelRow.node`). */
  node?: string;
}

/** The binding a node keeps for the model it runs, beside its code. Saved at
 *  `metadata.modelRefs` by `TrillGenerator`, as `datasetRefs` is. */
export interface ModelRef {
  id: string;
  name: string;
}

type ModelLike = (Pick<ModelRow, "id" | "name"> & Partial<Pick<ModelRow, "task" | "node">>) | ModelDragPayload;

function modelIdOf(model: ModelLike): string {
  return "modelId" in model ? model.modelId : model.id;
}

export const MODEL_DRAG_MIME = "application/x-curio-model";
const MODEL_DRAG_PLAIN_PREFIX = "curio-model:";

/** In-memory payload for the current drag (HTML5 getData is unreliable for custom MIME). */
let activeModelDrag: ModelDragPayload | null = null;

export function createModelDragPayload(model: ModelRow): ModelDragPayload {
  return {
    modelId: model.id,
    name: model.name,
    runtime: model.runtime,
    task: model.task,
    ...(model.node ? { node: model.node } : {}),
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
 * `curio_load_model("...")` with a literal string. Unlike a dataset, a model is not
 * written into code that does not ask for one, so a node that never calls
 * `curio_load_model` cannot take it. Checks the same code `applyModelToNodeData`
 * rewrites, so a drop that is accepted always changes something.
 */
export function canApplyModelToNode(data: any): boolean {
  return hasRewritableModelCall(currentCode(data));
}

/**
 * The task of the model *data* runs now when it differs from *model*'s, so a
 * drop onto it can be refused: a node built for one kind of model (routing's
 * graph network) cannot run another (a segmentation model). `null` when they
 * match or either task is unknown, which leaves the drop to go ahead.
 */
export function modelTaskConflict(
  data: any,
  model: ModelLike,
  taskOf: (modelId: string) => ModelTask | undefined,
): ModelTask | null {
  const current = modelIdsInCode(currentCode(data))[0];
  if (!current || !model.task || current === modelIdOf(model)) return null;
  const task = taskOf(current);
  return task && task !== model.task ? task : null;
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
  /** `<packageId>@<major>`, the package a project adds to get it. */
  packageDirName?: string;
}

/** The node a model dropped on the canvas becomes. */
export interface ModelCanvasNode extends ModelDropTemplate {
  /** Unset only for the model's own node whose code is not loaded yet: the
   *  node fills it from its template when it mounts, and that code already
   *  names the model. */
  code: string | undefined;
  modelRefs: ModelRef[];
}

/** The task of each model the catalog knows, by id. */
export type ModelTaskLookup = (modelId: string) => ModelTask | undefined;

/** The package a canonical template id belongs to, as `<packageId>@<major>`. */
export function packageDirOfNodeType(nodeType: string): string | null {
  const match = /^([^/@]+)\/[^/@]+@(\d+)$/.exec(nodeType);
  return match ? `${match[1]}@${match[2]}` : null;
}

/**
 * Whether *template* can run *model*, best first: 0 when its code already
 * names the model, 1 when it is the node the model's manifest names, 2 when
 * its code runs another model of the same task (a downloaded segmentation
 * model goes to Image Segmentation). `null` when it cannot: a node that runs a
 * model of another task (the routing GNN's node cannot run a segmentation
 * model), or one whose model's task is unknown.
 */
function fitOf(template: ModelDropTemplate, model: ModelLike, taskOf: ModelTaskLookup): number | null {
  const modelId = modelIdOf(model);
  const named = modelIdsInCode(template.code);
  if (named.includes(modelId)) return 0;
  if (model.node && template.nodeType === model.node) return 1;
  if (!model.task || !hasRewritableModelCall(template.code)) return null;
  const current = named[0];
  return current && taskOf(current) === model.task ? 2 : null;
}

/**
 * What a model dropped on the empty canvas becomes, as a dataset dropped there
 * becomes a Data Loading node: the best fit among *templates* (`fitOf`), made
 * to run *model*. So a model with a node of its own (Deep Umbra, Accumulated
 * Shadow) gets that node, and a model never gets a node built for another
 * kind of model, which is how Deep Umbra once became a Weather Routing node.
 * `null` when none of them fits. Pure, like `applyModelToNodeData`, which it
 * goes through.
 */
export function modelNodeForCanvas(
  templates: ModelDropTemplate[],
  model: ModelLike,
  taskOf: ModelTaskLookup = () => undefined,
): ModelCanvasNode | null {
  const modelId = modelIdOf(model);
  const ranked = templates
    .map((template, order) => ({ template, order, fit: fitOf(template, model, taskOf) }))
    .filter((entry): entry is { template: ModelDropTemplate; order: number; fit: number } => entry.fit !== null)
    .sort((a, b) => a.fit - b.fit || a.order - b.order);
  for (const { template } of ranked) {
    const applied = applyModelToNodeData({ code: template.code }, model);
    if (applied.modelRefs) return { ...template, code: applied.code, modelRefs: applied.modelRefs };
    // Its own node, its code not loaded yet: the template fills it.
    if (template.code === undefined && template.nodeType === model.node) {
      return { ...template, code: undefined, modelRefs: [{ id: modelId, name: model.name }] };
    }
  }
  return null;
}

/**
 * The node a model dropped on the canvas should become when the dataflow has
 * none that fits, so its package can be added: the node its manifest names,
 * else one installed in this account that fits (`modelNodeForCanvas` over
 * every template), else the node another catalog model of the same task
 * names. `null` when nothing in Curio runs it.
 */
export function modelNodeElsewhere(
  allTemplates: ModelDropTemplate[],
  model: ModelLike,
  catalog: Pick<ModelRow, "id" | "task" | "node">[],
): string | null {
  if (model.node) return model.node;
  const taskOf: ModelTaskLookup = (id) => catalog.find((row) => row.id === id)?.task;
  const installed = modelNodeForCanvas(allTemplates, model, taskOf);
  if (installed) return installed.nodeType;
  if (!model.task) return null;
  return catalog.find((row) => row.task === model.task && row.node)?.node ?? null;
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
