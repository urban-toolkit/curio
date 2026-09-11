/**
 * Hand a blob to the browser as a file download.
 *
 * A leaf module on purpose. This lived in `api/packagesApi.ts`, whose import
 * graph reaches the whole node-package registry - so a component that wanted
 * nothing but "save these bytes as a file" pulled that entire chain in with it,
 * and any test rendering such a component died on an unrelated registry mock
 * before its first assertion.
 *
 * The blob never lives in JS memory longer than the click handler: it goes
 * straight to `URL.createObjectURL` and the URL is revoked immediately after.
 */
export function triggerBlobDownload(blob: Blob, filename: string): void {
  const objUrl = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = objUrl;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(objUrl);
}

export default triggerBlobDownload;
