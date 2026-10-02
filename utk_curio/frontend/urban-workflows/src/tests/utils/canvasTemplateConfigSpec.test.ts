/**
 * The node settings config on its way into a spec and back (#412).
 *
 * The modal's whole config persists at `metadata.packageTemplateConfig`, minus
 * two things that would only go stale there: `sourceCode`, a copy of the
 * node's code that the spec already holds as the node's `content`, and the
 * port `id`s, which are random keys for the port editor's rows. A load hands
 * each port a fresh id from the same id maker the editor uses.
 */
import * as fs from "fs";
import * as path from "path";

import {
    canvasTemplateConfigFromSpec,
    canvasTemplateConfigToSpec,
} from "../../utils/canvasTemplateConfigSpec";
import type { CanvasTemplateConfig } from "../../utils/canvasTemplateConfig";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..");

/** Every field, so a field added to the type has to be added here too. */
const FULL: CanvasTemplateConfig = {
    label: "Clean the parcels",
    category: "computation",
    engine: "python",
    editor: "code",
    description: "Drops parcels without a zoning code",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    hasProvenance: false,
    inputPorts: [{ id: "k3j9x0a1", types: ["DATAFRAME"], cardinality: "1" }],
    outputPorts: [
        { id: "p0q8w2e4", types: ["DATAFRAME"], cardinality: "1" },
        { id: "z7y6x5w4", types: ["JSON"], cardinality: "[1,n]" },
    ],
    sourceFilename: "clean.py",
    sourceCode: "return arg.dropna()",
};

describe("canvasTemplateConfigToSpec", () => {
    test("keeps every setting and leaves out the code copy and the port ids", () => {
        const { sourceCode, inputPorts, outputPorts, ...settings } = FULL;
        expect(canvasTemplateConfigToSpec(FULL)).toEqual({
            ...settings,
            inputPorts: inputPorts.map(({ types, cardinality }) => ({ types, cardinality })),
            outputPorts: outputPorts.map(({ types, cardinality }) => ({ types, cardinality })),
        });
        expect(sourceCode).toBeTruthy();
    });

    test("does not touch the live config", () => {
        const live = JSON.parse(JSON.stringify(FULL));
        canvasTemplateConfigToSpec(live);
        expect(live).toEqual(FULL);
    });

    test("writes nothing for a node that has no config", () => {
        expect(canvasTemplateConfigToSpec(undefined)).toBeUndefined();
        expect(canvasTemplateConfigToSpec(null)).toBeUndefined();
        expect(canvasTemplateConfigToSpec("code")).toBeUndefined();
        expect(canvasTemplateConfigToSpec([])).toBeUndefined();
        expect(canvasTemplateConfigToSpec({ sourceCode: "return arg" })).toBeUndefined();
    });
});

describe("canvasTemplateConfigFromSpec", () => {
    test("restores every setting and gives each port a fresh, distinct id", () => {
        const restored = canvasTemplateConfigFromSpec(canvasTemplateConfigToSpec(FULL));
        const { sourceCode: _code, inputPorts, outputPorts, ...settings } = FULL;
        expect(restored).toMatchObject(settings);
        expect(restored).not.toHaveProperty("sourceCode");

        const ports = [...(restored!.inputPorts ?? []), ...(restored!.outputPorts ?? [])];
        expect(ports.map(({ types, cardinality }) => ({ types, cardinality }))).toEqual(
            [...inputPorts, ...outputPorts].map(({ types, cardinality }) => ({ types, cardinality })),
        );
        for (const port of ports) expect(port.id).toMatch(/^[a-z0-9]+$/);
        expect(new Set(ports.map((p) => p.id)).size).toBe(ports.length);
    });

    test("restores a partial config as it is", () => {
        expect(canvasTemplateConfigFromSpec({ hasProvenance: false })).toEqual({
            hasProvenance: false,
        });
    });

    test("ignores a code copy a hand-written spec carries, so the content stays the only code", () => {
        expect(
            canvasTemplateConfigFromSpec({ hasCode: true, sourceCode: "return 1" }),
        ).toEqual({ hasCode: true });
    });

    test("ignores what is not a config", () => {
        expect(canvasTemplateConfigFromSpec(undefined)).toBeUndefined();
        expect(canvasTemplateConfigFromSpec("x")).toBeUndefined();
        expect(canvasTemplateConfigFromSpec([{ hasCode: true }])).toBeUndefined();
        expect(
            canvasTemplateConfigFromSpec({ inputPorts: "DATAFRAME", outputPorts: [null, 3] }),
        ).toEqual({ outputPorts: [] });
    });
});

describe("the trill schema declares what the writer emits", () => {
    const schema = JSON.parse(
        fs.readFileSync(path.join(REPO_ROOT, "docs", "schemas", "trill.v1.json"), "utf-8"),
    );
    const declared = schema.$defs.nodeMetadata.properties.packageTemplateConfig;

    test("every key of a full config", () => {
        const written = canvasTemplateConfigToSpec(FULL)!;
        expect(Object.keys(declared.properties).sort()).toEqual(Object.keys(written).sort());
        expect(declared.additionalProperties).toBe(false);
    });

    test("every key of a port", () => {
        const written = canvasTemplateConfigToSpec(FULL)! as { inputPorts: object[] };
        const port = declared.properties.inputPorts.items;
        expect(Object.keys(port.properties).sort()).toEqual(Object.keys(written.inputPorts[0]).sort());
        expect(port.additionalProperties).toBe(false);
        expect(declared.properties.outputPorts.items).toEqual(port);
    });
});
