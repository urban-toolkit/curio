/**
 * The node settings config as a spec stores it, at
 * `metadata.packageTemplateConfig` (#412), and back.
 *
 * The node settings modal writes its whole config to
 * `data.packageTemplateConfig`. Two of its fields stay out of the spec:
 * `sourceCode`, a copy of the node's code that the spec already holds as the
 * node's `content`, and each port's `id`, a random key for the port editor's
 * rows. A load gives every port a fresh id from the same id maker.
 *
 * TrillGenerator writes with `canvasTemplateConfigToSpec`, and `loadTrill`
 * reads with `canvasTemplateConfigFromSpec`. This module imports nothing but
 * the id maker, because `canvasTemplateConfig.ts` pulls in the node registry
 * and TrillGenerator must not.
 */
import type { CanvasTemplateConfig } from "./canvasTemplateConfig";
import type { PortDraft } from "../services/packages/factoryDraft";
import { factoryUiMakeId } from "../services/packages/factoryDraft";

/** A port as the spec stores it: everything but the editor's row id. */
export type CanvasTemplatePortSpec = Omit<PortDraft, "id">;

/** The config as the spec stores it. */
export type CanvasTemplateConfigSpec = Partial<
    Omit<CanvasTemplateConfig, "sourceCode" | "inputPorts" | "outputPorts">
> & {
    inputPorts?: CanvasTemplatePortSpec[];
    outputPorts?: CanvasTemplatePortSpec[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === "object" && !Array.isArray(value);
}

/** The port rows of a list, or undefined when it is not a list. */
function portRows(value: unknown): Record<string, unknown>[] | undefined {
    return Array.isArray(value) ? value.filter(isRecord) : undefined;
}

/**
 * What `data.packageTemplateConfig` writes into the spec. Undefined means
 * write nothing: the node never had its settings saved.
 */
export function canvasTemplateConfigToSpec(config: unknown): CanvasTemplateConfigSpec | undefined {
    if (!isRecord(config)) return undefined;
    const { sourceCode: _sourceCode, inputPorts, outputPorts, ...settings } = config;
    const spec: Record<string, unknown> = { ...settings };
    const inputs = portRows(inputPorts);
    const outputs = portRows(outputPorts);
    if (inputs) spec.inputPorts = inputs.map(({ id: _id, ...port }) => port);
    if (outputs) spec.outputPorts = outputs.map(({ id: _id, ...port }) => port);
    return Object.keys(spec).length > 0 ? (spec as CanvasTemplateConfigSpec) : undefined;
}

/**
 * What a spec's `metadata.packageTemplateConfig` puts back on the node, with a
 * fresh id on every port. A `sourceCode` in a hand-written spec is dropped, so
 * the node's `content` stays its only code.
 */
export function canvasTemplateConfigFromSpec(spec: unknown): Partial<CanvasTemplateConfig> | undefined {
    if (!isRecord(spec)) return undefined;
    const { sourceCode: _sourceCode, inputPorts, outputPorts, ...settings } = spec;
    const config: Record<string, unknown> = { ...settings };
    const inputs = portRows(inputPorts);
    const outputs = portRows(outputPorts);
    if (inputs) config.inputPorts = inputs.map((port) => ({ ...port, id: factoryUiMakeId() }));
    if (outputs) config.outputPorts = outputs.map((port) => ({ ...port, id: factoryUiMakeId() }));
    return Object.keys(config).length > 0 ? (config as Partial<CanvasTemplateConfig>) : undefined;
}
