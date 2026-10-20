import React, { memo, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { refreshPackageRegistry } from "../../../registry/packageRegistryBootstrap";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { BUILTIN_PACKAGE_ID } from "../../../registry/packagesClient";
import { NodeDescriptor } from "../../../registry/types";
import { useUserContext } from "../../../providers/UserProvider";
import {
    PackagesPaletteDropdown,
    groupPalettePackages,
    paletteDescriptorBootstrapKey,
} from "./toolsMenuPackagePalette";
import { BuiltinPaletteDropdown } from "./builtinPalette";
import { DatasetsPaletteDropdown } from "./datasetPalette";
import { AgentsPaletteDropdown } from "./agentsPalette";
import { ModelsPaletteDropdown } from "./modelsPalette";
import { RunAllButton } from "./RunAllButton";
import styles from "./ToolsMenu.module.css";

const NOOP = () => () => {};

const ToolsMenu = memo(function ToolsMenu() {
    // Re-render whenever the registry mutates (e.g. when package descriptors
    // land asynchronously via packagesClient.ts).
    const paletteVersion = useSyncExternalStore(
        typeof window !== "undefined" ? subscribeToRegistry : NOOP,
        paletteDescriptorBootstrapKey,
        () => "ssr",
    );
    void paletteVersion;

    const { user } = useUserContext();
    useEffect(() => {
        const uid = user?.id;
        if (uid == null) return;
        void refreshPackageRegistry();
    }, [user?.id]);

    const paletteTypes = getPaletteNodeTypes();
    // The curio.builtin package is manifest-driven like any other, but the UI
    // gives it the rail's own Built-in palette. Only third-party packages land
    // in the Node Catalog palette, and never a model package's node: a model's
    // node is added by dropping its card from the Model Catalog.
    const isBuiltin = (d: NodeDescriptor) => d.package?.packageId === BUILTIN_PACKAGE_ID;
    const isModelNode = (d: NodeDescriptor) => d.package?.kind === "model";
    const coreTypes = paletteTypes.filter(isBuiltin);
    const packageTypes = paletteTypes.filter((d) => !isBuiltin(d) && !isModelNode(d));
    const packageGroups = groupPalettePackages(packageTypes);

    // Every palette trigger lives in the left rail and their panels open into
    // the same strip to the right of it, so only one may be open at a time,
    // and the rail starts with all of them closed. A palette closes ONLY when
    // its own trigger is clicked again (or another trigger takes the strip) -
    // outside clicks and Escape deliberately leave it open.
    const [activePalette, setActivePalette] = useState<
        "builtin" | "datasets" | "packages" | "agents" | "models" | null
    >(null);
    const setBuiltinOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "builtin" : prev === "builtin" ? null : prev));
    }, []);
    const setDatasetsOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "datasets" : prev === "datasets" ? null : prev));
    }, []);
    const setPackagesOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "packages" : prev === "packages" ? null : prev));
    }, []);
    const setAgentsOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "agents" : prev === "agents" ? null : prev));
    }, []);
    const setModelsOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "models" : prev === "models" ? null : prev));
    }, []);

    return (
        <div id="tools-palette-dock" className={styles.paletteDock}>
            <div id="tools-menu" className={styles.builtinStack}>
                <BuiltinPaletteDropdown
                    nodeTypes={coreTypes}
                    open={activePalette === "builtin"}
                    setOpen={setBuiltinOpen}
                />
                <PackagesPaletteDropdown
                    groups={packageGroups}
                    open={activePalette === "packages"}
                    setOpen={setPackagesOpen}
                />
                <DatasetsPaletteDropdown open={activePalette === "datasets"} setOpen={setDatasetsOpen} />
                <AgentsPaletteDropdown open={activePalette === "agents"} setOpen={setAgentsOpen} />
                <ModelsPaletteDropdown open={activePalette === "models"} setOpen={setModelsOpen} />
                <RunAllButton />
            </div>
        </div>
    );
});

export default ToolsMenu;
