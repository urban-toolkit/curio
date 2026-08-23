/**
 * dev/92 B-2 — the restart-honesty sentence: one composer, backend-declared
 * libs verbatim, "recommended" strength (running nodes keep old imports).
 */
import { restartNotice } from "../../services/packageRestartCopy";

describe("packageRestartCopy (dev/92)", () => {
    it("names the exact libraries pip changed", () => {
        expect(restartNotice({ libs: ["torch", "shapely"] })).toBe(
            "Restart Curio to pick up torch, shapely — running nodes keep the " +
            "previously loaded versions until then.",
        );
    });

    it("single-lib composition stays clean", () => {
        expect(restartNotice({ libs: ["geo-sdk"] })).toContain(
            "pick up geo-sdk —",
        );
    });
});
