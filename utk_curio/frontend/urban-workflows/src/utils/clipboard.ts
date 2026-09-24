/**
 * Copy a short string, and say whether it worked.
 *
 * ``navigator.clipboard`` rejects on an insecure origin and when the document
 * is not focused, so the result is reported rather than assumed. Extracted from
 * ``CopyButton``, which had the only implementation: a menu row cannot show
 * that component's idle/copied/failed state and reports through a toast
 * instead, and two hand-rolled copies is how the two end up behaving
 * differently.
 */
export async function copyText(value: string, label: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch (err) {
    console.warn(`Copying ${label} to clipboard failed`, err);
    return false;
  }
}
