import React, { useState } from "react";
import { Dropdown } from "react-bootstrap";

export function useRightClickMenu() {
  const [showMenu, setShowMenu] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ x: 0, y: 0 });

  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    setMenuPosition({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY });
    setShowMenu(true);

    // Add an event listener to close the menu when clicking anywhere on the document
    document.addEventListener("click", handleCloseMenu);
  };

  const handleCloseMenu = () => {
    setShowMenu(false);
    document.removeEventListener("click", handleCloseMenu);
  };

  return {
    onContextMenu,
    showMenu,
    menuPosition,
  };
}
