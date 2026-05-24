import { getPaletteNodeTypes } from "../../../../registry";

/** Changes whenever package descriptors are registered — same signal as the outer palette rerender. */
export function paletteDescriptorBootstrapKey(): string {
    const types = getPaletteNodeTypes();
    return `${types.length}|${types.map((d) => d.id).join(",")}`;
}
