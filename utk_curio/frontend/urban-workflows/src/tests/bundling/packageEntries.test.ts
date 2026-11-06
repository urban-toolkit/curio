/**
 * `npm run build:packages` bundles the packages under `packages/` and the e2e
 * suite's test packages that bring their own interface: each whose manifest
 * declares a `behaviorScript` and that holds the bundle's entry point,
 * `sources/index.tsx`. The bundle is written where `behaviorScript` says. So a
 * package of your own needs no edit in the build config, and a package built
 * outside this repository, which ships its bundle built, is left alone.
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
const TEST_PACKAGES = path.resolve(__dirname, "../../../../../backend/tests/test_frontend/packages");
/** The test package made with `scripts/new_package.py --with-ui`. */
const UI_TEST_PACKAGE = "test.ui-node@1";

type Entry = { id: string; entry: string; outputDir: string; filename: string };

function packageEntries(...roots: string[]): Entry[] {
    return require(HELPER).packageEntries(...roots);
}

/** The package folders under *root* that declare a bundle and hold its entry point. */
function declaringBundles(root: string): string[] {
    return fs.readdirSync(root).sort().filter((folder) => {
        const manifest = path.join(root, folder, "manifest.json");
        return fs.existsSync(manifest)
            && Boolean(JSON.parse(fs.readFileSync(manifest, "utf8")).behaviorScript)
            && fs.existsSync(path.join(root, folder, "sources", "index.tsx"));
    });
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

    it("are the shipped and the test packages that declare a bundle and hold its entry point", () => {
        const shipped = declaringBundles(PACKAGES);
        const tests = declaringBundles(TEST_PACKAGES);
        expect(tests).toContain(UI_TEST_PACKAGE);
        expect(packageEntries(PACKAGES).map((entry) => entry.id)).toEqual(shipped);
        expect(packageEntries(TEST_PACKAGES).map((entry) => entry.id)).toEqual(tests);
        // The build's folders: the shipped catalog, then the test packages.
        const { PACKAGE_ROOTS } = require(HELPER);
        expect(PACKAGE_ROOTS).toEqual([PACKAGES, TEST_PACKAGES]);
        expect(packageEntries(...PACKAGE_ROOTS).map((entry) => entry.id)).toEqual([...shipped, ...tests]);
    });

    it("write the test UI package's bundle inside it, where its manifest says", () => {
        const folder = path.join(TEST_PACKAGES, UI_TEST_PACKAGE);
        expect(packageEntries(TEST_PACKAGES).find((entry) => entry.id === UI_TEST_PACKAGE)).toEqual({
            id: UI_TEST_PACKAGE,
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
            packageEntries(PACKAGES, TEST_PACKAGES).map((entry) => ({
                name: entry.id,
                entry: entry.entry,
                path: entry.outputDir,
                filename: entry.filename,
                library: entry.id.replace(/[@.]/g, "_"),
            })),
        );
    });
});
