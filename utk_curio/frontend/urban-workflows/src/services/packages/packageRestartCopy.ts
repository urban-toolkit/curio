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

/**
 * Append the restart sentence to whatever a surface was already going to say.
 *
 * Three install paths began running pip only when the file-first routes started
 * honouring declared dependencies (/upload, /factory/install), so they can now
 * change a library under the running server exactly as the drawer's install
 * can - and they were the ones not saying so. Composed rather than toasted
 * separately: "Imported X." and "restart to pick up shapely" are one event, and
 * an error toast now stays until dismissed, so a second toast per event is a
 * second thing to dismiss.
 */
export function withRestartNotice(
    verdict: string,
    recommendation?: RestartRecommendation | null,
): string {
    if (!recommendation?.libs?.length) return verdict;
    return `${verdict} ${restartNotice(recommendation)}`;
}

export function restartNotice(recommendation: RestartRecommendation): string {
    const libs = recommendation.libs.join(", ");
    return (
        `Restart Curio to pick up ${libs} — running nodes keep the ` +
        "previously loaded versions until then."
    );
}
