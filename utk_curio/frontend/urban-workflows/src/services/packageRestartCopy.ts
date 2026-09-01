/**
 * dev/92 B-2 — the restart-honesty copy, ONE composer for every surface
 * (the retentionCopy.ts pattern): the backend says WHICH libraries pip
 * actually installed/changed under the running server; this module owns the
 * sentence. "Recommended", not "required" — new-dep-only installs work
 * without a restart; it is version CHANGES that leave running nodes on the
 * previously loaded imports until Curio restarts (dev/91 §0.1).
 */
export interface RestartRecommendation {
    libs: string[];
}

export function restartNotice(recommendation: RestartRecommendation): string {
    const libs = recommendation.libs.join(", ");
    return (
        `Restart Curio to pick up ${libs} — running nodes keep the ` +
        "previously loaded versions until then."
    );
}
