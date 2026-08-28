import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import type CSS from "csstype";
import { useHeaderIconDragClick } from "../utils/headerIconDragClick";

/**
 * A node-header control: minimize, pin, comments, delete, save-template.
 *
 * A real ``<button>`` rather than a ``role="button"`` SVG. The previous shape
 * put ``role``, ``tabIndex`` and a hand-rolled ``onKeyDown`` on the icon itself
 * and passed ``title`` to ``FontAwesomeIcon`` — but ``title`` is in that
 * component's ``DEFAULT_PROP_KEYS``, so it was consumed instead of reaching the
 * DOM, and FontAwesome additionally stamps ``aria-hidden="true"`` on any icon
 * with no ``aria-label``. The result was a control that was in the tab order
 * and invisible to assistive technology at the same time, with no hover tooltip
 * either. ``EditableNodeHeaderLabel`` next door already used real
 * ``aria-label``s; this brings the rest of the header band in line.
 *
 * The button carries the name and the tooltip, the icon is decorative, and
 * activation, focus ring and Enter/Space come from the element instead of being
 * re-implemented. ``useHeaderIconDragClick`` is unchanged: it activates on
 * pointerdown+pointerup and swallows the native click, so press-and-drag on the
 * header still moves the node.
 */
export function HeaderIconButton({
  icon,
  title,
  style,
  onActivate,
}: {
  icon: IconDefinition;
  title?: string;
  style?: CSS.Properties;
  onActivate: () => void;
}) {
  const handlers = useHeaderIconDragClick(onActivate);
  return (
    <button
      type="button"
      aria-label={title}
      title={title}
      style={{ ...resetStyle, ...style }}
      {...handlers}
    >
      <FontAwesomeIcon icon={icon} aria-hidden />
    </button>
  );
}

/** Strip the native chrome so the button reads as the bare icon it replaces. */
const resetStyle: CSS.Properties = {
  background: "none",
  border: "none",
  padding: 0,
  margin: 0,
  font: "inherit",
  lineHeight: 1,
  color: "inherit",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
};
