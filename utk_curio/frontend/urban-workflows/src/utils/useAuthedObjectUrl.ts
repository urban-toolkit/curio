import { useEffect, useState } from 'react';
import { backendUrl } from './backendUrl';
import { getToken } from './authApi';

/**
 * An object URL for a same-origin `/api/...` file, fetched with the token.
 *
 * Curio's backend resolves WHICH user is asking from the bearer token, and a
 * bare `<img src>` cannot send a header, so it would resolve to the shared
 * guest and 404 for everyone signed in. Null *path* fetches nothing.
 */
export function useAuthedObjectUrl(path: string | null): { url: string | null; failed: boolean } {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!path) return;
    let revoked: string | null = null;
    let cancelled = false;
    setUrl(null);
    setFailed(false);
    const token = getToken();
    fetch(`${backendUrl()}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((blob) => {
        if (cancelled) return;
        revoked = URL.createObjectURL(blob);
        setUrl(revoked);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    // Revoke on unmount and whenever the path changes, or every re-render
    // leaks a blob for the lifetime of the document.
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [path]);

  return { url, failed };
}
