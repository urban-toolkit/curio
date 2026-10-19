/**
 * `npm run build:packages` bundles the packages under `packages/` that bring
 * their own interface: each whose manifest declares a `behaviorScript` and that
 * holds the bundle's entry point, `sources/index.tsx`. The bundle is written
 * where `behaviorScript` says. So a package of your own needs no edit in the
 * build config, and a package built outside this repository, which ships its
 * bundle built, is left alone.
 *
 * The helper is required inside each test, so a checkout without it fails
 * each test on its own.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

const HELPER = path.resolve(__dirname, "../../../webpack/packageEntries.js");
const CONFIG = path.resolve(__dirname, "../../../webpack.packages.config.js");
const PACKAGES = path.resolve(__dirname, "../../../../../../packages");

type Entry = { id: string; entry: string; outputDir: string; filename: string };

function packageEntries(root: string): Entry[] {
    return require(HELPER).packageEntries(root);
}

/** A package folder under *root*: its manifest, if any, and empty *files*. */
function writePackage(root: string, folder: string, manifest: object | null, files: string[]): void {
    const dir = path.join(root, folder);
    fs.mkdirSync(dir, { recursive: true });
    if (manifest) fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(manifest));
    for (const file of files) {
        fs.mkdirSync(path.dirname(path.join(dir, file)), { recursive: true });
        fs.writeFileSync(path.join(dir, file), "export {};\n");
    }
}

describe("the packages npm run build:packages bundles", () => {
    let root: string;
    beforeEach(() => {
        root = fs.mkdtempSync(path.join(os.tmpdir(), "curio-package-entries-"));
    });
    afterEach(() => {
        fs.rmSync(root, { recursive: true, force: true });
    });

    it("are the shipped packages that declare a bundle and hold its entry point", () => {
        const declaring = fs.readdirSync(PACKAGES).sort().filter((folder) => {
            const manifest = path.join(PACKAGES, folder, "manifest.json");
            return fs.existsSync(manifest)
                && Boolean(JSON.parse(fs.readFileSync(manifest, "utf8")).behaviorScript)
                && fs.existsSync(path.join(PACKAGES, folder, "sources", "index.tsx"));
        });
        expect(declaring).toContain("curio.example-ui@1");
        expect(packageEntries(PACKAGES).map((entry) => entry.id)).toEqual(declaring);
    });

    it("write Example UI's bundle where it was always written", () => {
        const folder = path.join(PACKAGES, "curio.example-ui@1");
        expect(packageEntries(PACKAGES).find((entry) => entry.id === "curio.example-ui@1")).toEqual({
            id: "curio.example-ui@1",
            entry: path.join(folder, "sources", "index.tsx"),
            outputDir: path.join(folder, "scripts"),
            filename: "behaviors.js",
        });
    });

    it("take a package of your own, with no edit to the build config", () => {
        writePackage(root, "me.heatmap@1", { id: "me.heatmap", behaviorScript: "scripts/behaviors.js" }, [
            "sources/index.tsx",
        ]);
        writePackage(root, "me.layout@2", { id: "me.layout", behaviorScript: "scripts/ui/bundle.js" }, [
            "sources/index.tsx",
        ]);
        // Built outside this repository: the bundle ships built, with no entry point.
        writePackage(root, "me.prebuilt@1", { id: "me.prebuilt", behaviorScript: "scripts/behaviors.js" }, [
            "scripts/behaviors.js",
        ]);
        // No bundle declared: its nodes run Python.
        writePackage(root, "me.python@1", { id: "me.python" }, ["sources/index.tsx", "sources/run.py"]);
        writePackage(root, "notes", null, ["sources/index.tsx"]);
        fs.writeFileSync(path.join(root, "README.md"), "Not a package.\n");

        expect(packageEntries(root)).toEqual([
            {
                id: "me.heatmap@1",
                entry: path.join(root, "me.heatmap@1", "sources", "index.tsx"),
                outputDir: path.join(root, "me.heatmap@1", "scripts"),
                filename: "behaviors.js",
            },
            {
                id: "me.layout@2",
                entry: path.join(root, "me.layout@2", "sources", "index.tsx"),
                outputDir: path.join(root, "me.layout@2", "scripts", "ui"),
                filename: "bundle.js",
            },
        ]);
    });

    it("refuse a bundle path outside its package", () => {
        writePackage(root, "me.escape@1", { id: "me.escape", behaviorScript: "../elsewhere/behaviors.js" }, [
            "sources/index.tsx",
        ]);
        expect(() => packageEntries(root)).toThrow(/me\.escape@1.*behaviorScript/);
    });

    it("are none where there is no packages folder", () => {
        expect(packageEntries(path.join(root, "missing"))).toEqual([]);
    });

    it("are what the build config bundles, each under its own global", () => {
        const configs: any[] = require(CONFIG);
        expect(
            configs.map((config) => ({
                name: config.name,
                entry: config.entry,
                path: config.output.path,
                filename: config.output.filename,
                library: config.output.library.name,
            })),
        ).toEqual(
            packageEntries(PACKAGES).map((entry) => ({
                name: entry.id,
                entry: entry.entry,
                path: entry.outputDir,
                filename: entry.filename,
                library: entry.id.replace(/[@.]/g, "_"),
            })),
        );
    });
});
