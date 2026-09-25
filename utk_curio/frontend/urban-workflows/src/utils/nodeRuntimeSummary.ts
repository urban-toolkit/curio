/**
 * Bounded, truthful one-line summaries of a node's live runtime state.
 *
 * dev/111, ported to `imp/agentcatalog` by dev/129 at the owner's question
 * ("does this have to do with `nodeContext.current_input/current_output` still
 * sent empty?" — it did, and the fix had shipped only on `feat/agentscatalog`,
 * which is never merged back).
 *
 * Two rules the whole module exists to keep:
 *
 * - **The output's CONTENT is never forwarded.** An artifact id, a dataType and
 *   an error message are; the data itself is not, because a chat prompt is not
 *   a data channel.
 * - **Never-executed says so.** The vocabulary matches the server's own
 *   (`node_context.py`'s `runtimeStatus`), so the client and the runtime cannot
 *   describe the same node differently.
 */

export const NEVER_EXECUTED = "never-executed";

const ARTIFACT_CHARS = 60;
const ERROR_CHARS = 240;
const MERGE_SLOTS = 6;

type NodeData = {
    input?: unknown;
    output?: { code?: string; content?: unknown; outputType?: string; dataType?: string };
    in?: string;
    out?: string;
};

function truncate(text: string, max: number): string {
    return text.length > max ? text.slice(0, max) + "…" : text;
}

function declared(value: unknown): string {
    return typeof value === "string" && value.trim() ? ` (declared: ${value.trim()})` : "";
}

function artifactId(value: Record<string, unknown>): string {
    const id = value.dataset ?? value.path ?? "";
    return typeof id === "string" && id ? truncate(id, ARTIFACT_CHARS) : "";
}

/** One input value, whatever shape the propagation left it in. */
function summarizeValue(value: unknown): string {
    if (value === undefined || value === null || value === "") return "empty";
    if (typeof value === "string") return `string (${value.length} chars)`;
    if (typeof value === "number" || typeof value === "boolean") return typeof value;
    if (Array.isArray(value)) {
        const slots = value
            .slice(0, MERGE_SLOTS)
            .map((slot, i) => `[${i}] ${slot === undefined || slot === null ? "empty" : summarizeValue(slot)}`);
        return `MULTIPLE (${value.length} slots): ${slots.join("; ")}`;
    }
    if (typeof value === "object") {
        const record = value as Record<string, unknown>;
        const type = typeof record.dataType === "string" && record.dataType
            ? record.dataType
            : "unknown type";
        const id = artifactId(record);
        return id ? `${type} from artifact ${id}` : type;
    }
    return "input present (unrecognized shape)";
}

/** `current_input`: what this node received when it last ran. */
export function summarizeNodeInput(data: NodeData | undefined): string {
    if (!data) return "";
    const value = data.input;
    if (value === undefined || value === null || value === "") {
        return `no upstream input${declared(data.in)}`;
    }
    return `${summarizeValue(value)}${declared(data.in)}`;
}

/** `current_output`: what this node produced, or why it did not. */
export function summarizeNodeOutput(
    data: NodeData | undefined,
    storeOutput?: unknown,
): string {
    if (!data) return "";
    const output = data.output ?? {};
    const code = typeof output.code === "string" ? output.code : "";
    const suffix = declared(data.out);
    if (code === "error") {
        // The one `content` that IS forwarded: short, runtime-authored, and
        // exactly what an agent asked "why is this node red?" needs.
        return `error: ${truncate(String(output.content ?? "unknown error"), ERROR_CHARS)}${suffix}`;
    }
    if (code === "exec") return `running${suffix}`;
    const store = storeOutput && typeof storeOutput === "object"
        ? (storeOutput as Record<string, unknown>)
        : null;
    if (code === "success") {
        const type = output.dataType || output.outputType || (
            store && typeof store.dataType === "string" ? store.dataType : ""
        ) || "unknown type";
        const id = store ? artifactId(store) : "";
        return `success: ${type}${id ? ` artifact ${id}` : ""}${suffix}`;
    }
    if (store) {
        const type = typeof store.dataType === "string" && store.dataType ? store.dataType : "unknown type";
        const id = artifactId(store);
        return `success (restored): ${type}${id ? ` artifact ${id}` : ""}${suffix}`;
    }
    return `${NEVER_EXECUTED}${suffix}`;
}

/** The artifact the outputs store holds for a node, if any. */
export function storeOutputFor(
    outputs: Array<{ nodeId?: string; output?: unknown }> | undefined,
    nodeId: string,
): unknown {
    if (!Array.isArray(outputs)) return undefined;
    return outputs.find((entry) => entry?.nodeId === nodeId)?.output;
}
