/**
 * A menu the chat opens from a button: the header's More menu and a rail
 * group's list of nodes. Open, it holds a layer of the modal stack, so the
 * chat's own Escape stands down; Escape or a press anywhere else closes it,
 * Escape handing the focus back to its button, as the top bar's menus do.
 * The Escape that closes it is answered (`answerEscape`): in a browser the
 * menu's close is committed before the chat's own listener runs, which then
 * finds no layer open and would close the chat too. It takes the focus as it
 * opens, on its current item if it has one, and the arrow keys walk its items.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { answerEscape, escapeAnswered, holdModalStack } from "../../../ModalShell";

const ITEMS = '[role="menuitem"]:not([aria-disabled="true"])';

export interface MenuPopup<K> {
  /** What is open, or null: one menu, or one of a few (a rail's groups). */
  open: K | null;
  toggle: (key: K) => void;
  close: (refocus?: boolean) => void;
  menuRef: React.MutableRefObject<HTMLDivElement | null>;
  /** The button that opened the menu, refocused when Escape closes it. */
  anchorRef: React.MutableRefObject<HTMLElement | null>;
  onMenuKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
}

export function useMenuPopup<K = true>(): MenuPopup<K> {
  const [open, setOpen] = useState<K | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const anchorRef = useRef<HTMLElement | null>(null);

  const close = useCallback((refocus = false) => {
    setOpen(null);
    if (refocus) anchorRef.current?.focus();
  }, []);

  const toggle = useCallback((key: K) => setOpen((was) => (was === key ? null : key)), []);

  useEffect(() => {
    if (open === null) return undefined;
    const release = holdModalStack();
    const menu = menuRef.current;
    const first =
      menu?.querySelector<HTMLElement>(`[aria-current="true"]${ITEMS}`) ?? menu?.querySelector<HTMLElement>(ITEMS);
    first?.focus();
    const onPress = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      setOpen(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || escapeAnswered(event)) return;
      answerEscape(event);
      setOpen(null);
      anchorRef.current?.focus();
    };
    document.addEventListener("pointerdown", onPress, true);
    document.addEventListener("keydown", onKey);
    return () => {
      release();
      document.removeEventListener("pointerdown", onPress, true);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const onMenuKeyDown = useCallback((event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") return;
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLElement>(ITEMS) ?? []);
    if (items.length === 0) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? items.length - 1
          : (at + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
    items[next].focus();
  }, []);

  return { open, toggle, close, menuRef, anchorRef, onMenuKeyDown };
}
