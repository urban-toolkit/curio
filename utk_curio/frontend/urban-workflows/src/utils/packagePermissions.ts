/**
 * dev/91 §5 — plain-language meanings for package permission strings, ONE
 * map shared by every review surface (the install dialog and the agent
 * review card) so the trust edge reads identically everywhere.
 */
export const PACKAGE_PERMISSION_DESCRIPTIONS: Record<string, string> = {
    "server-code":
        "runs server-side code in the package backend sandbox — isolated per call, never inside Curio itself",
    "server-network":
        "its server-side code may reach the network",
};

/** The plain-language meaning, or null for a permission with no registered copy. */
export function describePackagePermission(permission: string): string | null {
    return PACKAGE_PERMISSION_DESCRIPTIONS[permission] ?? null;
}
