/**
 * The header above a node's code or spec, as a test reads it (#662): its row of
 * categories (Inputs, Scenarios, Widgets, Selections, Shared), each with its
 * name, its count and whether it is open, and the chips of a category once it
 * is opened. Opening a category the header does not have throws, so a test that
 * needs a tag fails where the header has no category for it.
 */
import { fireEvent } from "@testing-library/react";

export type StripCategory = "inputs" | "scenarios" | "widgets" | "selections" | "shared";

export interface CategoryButton {
  category: string | null;
  /** Its name and its count, as drawn: `Inputs 3`. */
  label: string;
  open: boolean;
}

/** The header's row of categories, in order. */
export function headerRow(container: ParentNode): CategoryButton[] {
  return Array.from(container.querySelectorAll("[data-widget-strip] [data-strip-category]")).map((button) => ({
    category: button.getAttribute("data-strip-category"),
    label: `${button.querySelector("[data-strip-name]")?.textContent ?? ""} ${button.querySelector("[data-strip-count]")?.textContent ?? ""}`,
    open: button.getAttribute("aria-expanded") === "true",
  }));
}

/** The button of *category* in the header, or null. */
export function categoryButton(container: ParentNode, category: StripCategory): HTMLElement | null {
  return container.querySelector<HTMLElement>(`[data-widget-strip] [data-strip-category="${category}"]`);
}

/** The chips *category* shows, once open; null while it is closed. */
export function chipsOf(container: ParentNode, category: StripCategory): HTMLElement | null {
  return container.querySelector<HTMLElement>(`[data-widget-strip] [data-strip-chips="${category}"]`);
}

/** Opens *category*, unless it is open, and gives its chips. Throws when the header has no such category. */
export function openCategory(container: ParentNode, category: StripCategory): HTMLElement {
  const button = categoryButton(container, category);
  if (!button) {
    const row = headerRow(container).map((entry) => entry.label).join(", ") || "nothing";
    throw new Error(`the header has no ${category} category; its row reads ${row}`);
  }
  if (button.getAttribute("aria-expanded") !== "true") fireEvent.click(button);
  const chips = chipsOf(container, category);
  if (!chips) throw new Error(`${category} did not open under the header's row`);
  return chips;
}

/**
 * Opens each category the header has, in its row's order, and hands *visit*
 * its chips while it is the one open: opening a category closes the one open.
 */
export function eachCategory(
  container: ParentNode,
  visit: (category: StripCategory, chips: HTMLElement) => void,
): void {
  for (const entry of headerRow(container)) {
    const category = entry.category as StripCategory;
    visit(category, openCategory(container, category));
  }
}

/** What dragging *tag* carries as text: the chip it writes. */
export function draggedText(tag: Element): string | undefined {
  const store = new Map<string, string>();
  fireEvent.dragStart(tag, {
    dataTransfer: { setData: (type: string, value: string) => void store.set(type, value), effectAllowed: "" },
  });
  return store.get("text/plain");
}
