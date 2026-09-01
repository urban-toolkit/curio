import React from "react";
import { Outlet } from "react-router-dom";
import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import styles from "./CatalogMasterPage.module.css";

export const CatalogMasterPage: React.FC = () => {
  return (
    <div className={styles.pageShell}>
      <GlobalPageHeader />
      <AppSectionTabs />
      <div className={styles.outlet}>
        <Outlet />
      </div>
      <VersionBadge />
    </div>
  );
};

export default CatalogMasterPage;
