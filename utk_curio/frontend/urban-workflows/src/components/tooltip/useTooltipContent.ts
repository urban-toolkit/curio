import type React from "react";
import { useEffect, useId, useLayoutEffect } from "react";
import type { TooltipSide } from "./tooltipPlacement";
import { tooltipStore } from "./tooltipStore";

/** What a target spreads to ask for registered content. */
export interface TooltipTargetProps {
  "data-tooltip-content"?: string;
  "data-tooltip-side"?: TooltipSide;
}

/**
 * Rich content for the one Curio tooltip: a list, a preview, anything more
 * than a line of text, which a `data-tooltip` attribute cannot hold.
 *
 * Registers *content* and returns the props the target spreads; the
 * TooltipLayer shows it as it shows any `data-tooltip`, with the same rules
 * and the same card. The latest content is what shows, and an open tooltip
 * follows it as it changes. Nothing to show (null) asks for no tooltip.
 */
export function useTooltipContent(
  content: React.ReactNode,
  options: { side?: TooltipSide } = {},
): TooltipTargetProps {
  const id = `curio-tooltip-content-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  // Each render, so the tooltip shows what the target shows now.
  useLayoutEffect(() => {
    tooltipStore.register(id, content);
  });
  useEffect(() => () => tooltipStore.unregister(id), [id]);
  if (content === null || content === undefined || content === false) return {};
  return { "data-tooltip-content": id, ...(options.side ? { "data-tooltip-side": options.side } : {}) };
}

export default useTooltipContent;
