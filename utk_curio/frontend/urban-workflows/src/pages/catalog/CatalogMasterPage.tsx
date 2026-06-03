import React from "react";
import { NavLink, Outlet } from "react-router-dom";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import styles from "./CatalogMasterPage.module.css";

function tabClassName({ isActive }: { isActive: boolean }): string {
  return [styles.tabLink, isActive ? styles.tabLinkActive : ""].filter(Boolean).join(" ");
}

export const CatalogMasterPage: React.FC = () => {
  return (
    <div className={styles.pageShell}>
      <GlobalPageHeader />
      <nav className={styles.tabBar} aria-label="Catalog sections">
        <NavLink to="/catalog/nodes" className={tabClassName} end>
          Nodes
        </NavLink>
        <NavLink to="/catalog/data" className={tabClassName}>
          Data
        </NavLink>
      </nav>
      <div className={styles.outlet}>
        <Outlet />
      </div>
      <VersionBadge />
    </div>
  );
};

export default CatalogMasterPage;
