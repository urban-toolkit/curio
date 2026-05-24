import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import type CSS from "csstype";
import { useHeaderIconDragClick } from "../utils/headerIconDragClick";

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
    <FontAwesomeIcon
      icon={icon}
      title={title}
      style={style as any}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate();
        }
      }}
      {...handlers}
    />
  );
}
