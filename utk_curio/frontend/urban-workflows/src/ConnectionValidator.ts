import { BoxType, SupportedType } from "./constants";
import { getAllNodeTypes } from "./registry";

let _inputCache: Record<string, SupportedType[]> | null = null;
let _outputCache: Record<string, SupportedType[]> | null = null;

function buildInputMap(): Record<string, SupportedType[]> {
    if (_inputCache) return _inputCache;
    const map: Record<string, SupportedType[]> = {};
    for (const desc of getAllNodeTypes()) {
        map[desc.id] = desc.inputPorts.flatMap(p => p.types);
    }
    _inputCache = map;
    return map;
}

function buildOutputMap(): Record<string, SupportedType[]> {
    if (_outputCache) return _outputCache;
    const map: Record<string, SupportedType[]> = {};
    for (const desc of getAllNodeTypes()) {
        map[desc.id] = desc.outputPorts.flatMap(p => p.types);
    }
    _outputCache = map;
    return map;
}

export class ConnectionValidator {
    static get _inputTypesSupported(): Record<string, SupportedType[]> {
        return buildInputMap();
    }

    static get _outputTypesSupported(): Record<string, SupportedType[]> {
        return buildOutputMap();
    }

    static checkBoxCompatibility(
        outBox: BoxType | undefined,
        inBox: BoxType | undefined
    ) {
        if (outBox == undefined || inBox == undefined) return false;

        let intersection = ConnectionValidator._inputTypesSupported[
            inBox
        ].filter((value: any) => {
            return ConnectionValidator._outputTypesSupported[outBox].includes(
                value
            );
        });

        return intersection.length > 0;
    }
}
