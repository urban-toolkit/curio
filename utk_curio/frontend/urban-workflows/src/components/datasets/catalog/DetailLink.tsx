import React from "react";
import { Link } from "react-router-dom";

export interface DetailLinkProps {
  to: string;
  className?: string;
  /** Takes a plain click instead of the router, so the modal holding this link
   *  can close itself and ask first over unsaved work. Left out, as on the
   *  full-page view, this is an ordinary link. */
  onFollow?: (to: string) => void;
  children: React.ReactNode;
}

/**
 * An in-app link inside a dataset's details.
 *
 * A click with a modifier (new tab, new window) is left to the browser: it
 * leaves the modal and the page behind it where they are, so there is nothing
 * to close or to ask about.
 */
export const DetailLink: React.FC<DetailLinkProps> = ({ to, className, onFollow, children }) => (
  <Link
    to={to}
    className={className}
    onClick={(event) => {
      if (!onFollow) return;
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      onFollow(to);
    }}
  >
    {children}
  </Link>
);

export default DetailLink;
