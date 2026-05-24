import { NodeType, SupportedType } from "./constants";
import { tryGetNodeDescriptor } from "./registry";

// Looks up types via `tryGetNodeDescriptor` so both versioned
// (`curio.builtin/data-loading@1`, palette) and unversioned
// (`curio.builtin/data-loading`, NotebookConvertor / legacy trills) ids hit.
function makePortsProxy(side: "inputPorts" | "outputPorts"): Record<string, SupportedType[]> {
    return new Proxy({} as Record<string, SupportedType[]>, {
        get(_target, key) {
            if (typeof key !== "string") return undefined;
            const desc = tryGetNodeDescriptor(key);
            return desc ? desc[side].flatMap(p => p.types) : undefined;
        },
        has(_target, key) {
            return typeof key === "string" && tryGetNodeDescriptor(key) !== undefined;
        },
    });
}

const _inputProxy = makePortsProxy("inputPorts");
const _outputProxy = makePortsProxy("outputPorts");

export class ConnectionValidator {
    static get _inputTypesSupported(): Record<string, SupportedType[]> {
        return _inputProxy;
    }

    static get _outputTypesSupported(): Record<string, SupportedType[]> {
        return _outputProxy;
    }

    static checkBoxCompatibility(
        outNodeType: NodeType | undefined,
        inNodeType: NodeType | undefined
    ) {
        if (outNodeType == undefined || inNodeType == undefined) return false;

        const inTypes = ConnectionValidator._inputTypesSupported[inNodeType];
        const outTypes = ConnectionValidator._outputTypesSupported[outNodeType];
        if (!inTypes || !outTypes) return false;

        return inTypes.some((value: any) => outTypes.includes(value));
    }
}
