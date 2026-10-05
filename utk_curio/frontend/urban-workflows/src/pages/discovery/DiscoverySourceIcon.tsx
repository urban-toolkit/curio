import React, { useState } from "react";

import {
  CatalogKindIcon,
  type CatalogKindIconSize,
} from "../../components/catalog/CatalogKindVisuals";
import { useAuthedObjectUrl } from "../../utils/useAuthedObjectUrl";
import styles from "./DiscoverySourceIcon.module.css";

export interface DiscoverySourceIconProps {
  /** The source's icon endpoint (a backend `/api/...` path), or null when it
   * ships none. */
  iconUrl: string | null;
  name: string;
  size?: CatalogKindIconSize;
}

/**
 * A source's mark, or the shared source glyph.
 *
 * The ONE place that decision is made. It looks small enough to inline at each
 * call site, which is exactly how a fallback ends up implemented three ways and
 * wrong in one of them: the card, the drawer hero and the detail header all
 * need it, and they need it to agree.
 *
 * The route answers on the backend and reads the user from the bearer token,
 * which a bare `<img src>` can neither reach nor send, so the mark is fetched
 * with the token and shown through an object URL, as collection thumbnails are.
 *
 * Three ways to end up with no icon, and all land here:
 *   - the source ships none, so `iconUrl` is null;
 *   - it names one that is missing, unreadable or over the size cap, so the
 *     route answers an error and the fetch fails;
 *   - the bytes arrive but are not an image, so the `<img>` fires `onError`.
 * The glyph also stands in while the mark is on its way. A broken icon must
 * cost a logo, not leave a broken-image box in the grid.
 *
 * The glyph and the image occupy the same box, so a grid of mixed sources does
 * not go ragged when one of them has no mark.
 */
export const DiscoverySourceIcon: React.FC<DiscoverySourceIconProps> = ({
  iconUrl,
  name,
  size = "lg",
}) => {
  const { url, failed: fetchFailed } = useAuthedObjectUrl(iconUrl);
  const [decodeFailed, setDecodeFailed] = useState(false);

  if (!url || fetchFailed || decodeFailed) {
    return <CatalogKindIcon kind="source" size={size} title={name} />;
  }

  return (
    <span
      className={[styles.frame, styles[`size_${size}`]].filter(Boolean).join(" ")}
      title={name}
    >
      <img
        className={styles.image}
        src={url}
        alt=""
        /* Decorative: the source's name is always beside it, so announcing the
           mark as well would read the name twice. */
        aria-hidden
        loading="lazy"
        onError={() => setDecodeFailed(true)}
      />
    </span>
  );
};

export default DiscoverySourceIcon;
