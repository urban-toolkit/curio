import React, { useState } from "react";

import {
  CatalogKindIcon,
  type CatalogKindIconSize,
} from "../../components/catalog/CatalogKindVisuals";
import styles from "./LakeSourceIcon.module.css";

export interface LakeSourceIconProps {
  /** The source's icon endpoint, or null when it ships none. */
  iconUrl: string | null;
  name: string;
  size?: CatalogKindIconSize;
}

/**
 * A source's mark, or the shared lake glyph.
 *
 * The ONE place that decision is made. It looks small enough to inline at each
 * call site, which is exactly how a fallback ends up implemented three ways and
 * wrong in one of them: the card, the drawer hero and the detail header all
 * need it, and they need it to agree.
 *
 * Two ways to end up with no icon, and both land here:
 *   - the source ships none, so `iconUrl` is null;
 *   - it names one that is missing, unreadable or over the size cap, so the
 *     route 404s and the `<img>` fires `onError`.
 * The second is why this is stateful rather than a ternary. A broken icon must
 * cost a logo, not leave a broken-image box in the grid.
 *
 * The glyph and the image occupy the same box, so a grid of mixed sources does
 * not go ragged when one of them has no mark.
 */
export const LakeSourceIcon: React.FC<LakeSourceIconProps> = ({
  iconUrl,
  name,
  size = "lg",
}) => {
  const [failed, setFailed] = useState(false);

  if (!iconUrl || failed) {
    return <CatalogKindIcon kind="lake" size={size} title={name} />;
  }

  return (
    <span
      className={[styles.frame, styles[`size_${size}`]].filter(Boolean).join(" ")}
      title={name}
    >
      <img
        className={styles.image}
        src={iconUrl}
        alt=""
        /* Decorative: the source's name is always beside it, so announcing the
           mark as well would read the name twice. */
        aria-hidden
        loading="lazy"
        onError={() => setFailed(true)}
      />
    </span>
  );
};

export default LakeSourceIcon;
