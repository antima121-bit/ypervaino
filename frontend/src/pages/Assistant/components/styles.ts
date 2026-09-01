import { type Theme } from "@mui/material";
import { makeStyles } from "@mui/styles";

export const useAssistantHeaderStyles = makeStyles((theme: Theme) => ({
  assistantHeaderContainer: {
    width: "calc(100% - 72px)",
    height: "80px",
    position: "fixed",
    display: "flex",
    minWidth: "1200px",
    padding: "0px 32px",
    justifyContent: "space-between",
    alignItems: "stretch",
    background: "#FFF",
    boxShadow: "0px 1px 0px 0px #E6E6E6",
    zIndex: 1000,
  },
  assistantDetailsContainer: {
    display: "flex",
    padding: "12px 0px",
    width: "430px",
    columnGap: "24px",
    overflow: "hidden",
  },
  assistantNavigationContainer: {
    flex: 1,
    display: "flex",
    alignItems: "stretch",
    justifyContent: "center",
  },
  assistantActionContainer: {
    width: "240px",
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
  },
  assistantTitleContainer: {
    display: "flex",
    flexDirection: "column",
    justifyContent: "center",
    width: "100%",
    overflow: "hidden",
  },
  chipsContainer: {
    display: "inline-flex",
    alignItems: "center",
    gap: "0px",
  },
}));

export const useAssistantNavigationStyles = makeStyles((theme: Theme) => ({
  assistantNavigationContainer: {
    display: "flex",
    alignItems: "center",
    columnGap: "8px",
  },
  navigationItemContainer: {
    height: "100%",
    display: "flex",
    alignItems: "center",
    padding: "12px 8px",
    cursor: "pointer",

    "& .navigation-item-content": {
      display: "flex",
      alignItems: "center",
      columnGap: "8px",
      borderRadius: "8px",
      padding: "12px",
    },

    "&:hover": {
      "& .navigation-item-content": {
        backgroundColor: "#F9F8F8",
      },
    },

    "&.active": {
      borderBottom: "3px solid #FF7D04",
      padding: "12px 8px 9px 8px",
    },
  },
  navigationItemIcon: {
    display: "flex",
    alignItems: "center",

    "& svg": {
      height: "20px",
      width: "20px",
    },
  },
  navigationItemLabel: {
    display: "flex",
    alignItems: "center",
  },
  overviewSeparator: {
    height: "48px",
    borderRight: "1px solid #E1DEDA",
  },
}));

export const useTabHeaderStyles = makeStyles((theme: Theme) => ({
  tabHeaderContainer: {
    display: "inline-flex",
    padding: "16px 24px",
    alignItems: "center",
    gap: "24px",
    borderRadius: "8px",
    background: "#FFF",
  },
  headerIconContainer: {
    height: "32px",
    width: "32px",

    "& svg": {
      height: "100%",
      width: "100%",
    },
  },
}));

export const useTabNavigationStyles = makeStyles((theme: Theme) => ({
  tabNavigationContainer: {
    display: "flex",
    width: "240px",
    minWidth: "200px",
    padding: "24px 16px",
    flexDirection: "column",
    alignItems: "stretch",
    gap: "24px",
    borderRadius: "8px",
    background: "#FFF",
    boxShadow:
      "0px 4px 16px -4px rgba(16, 24, 40, 0.08), 0px 4px 6px -2px rgba(16, 24, 40, 0.03)",
    alignSelf: "flex-start",
  },
  categoryContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "8px",
  },
  categoryNavigationsContainer: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",

    "& .navigation-link-container": {
      textDecoration: "none",
      display: "flex",
      height: "40px",
      padding: "0px 8px",
      alignItems: "center",
      gap: "8px",

      "&:hover:not(.disabled) , &.active:not(.disabled) ": {
        cursor: "pointer",
        borderRadius: "8px",
        background: "#FFF5EB",

        "& span": {
          color: "#E06F06",
        },
      },

      "&.disabled": {
        "& span": {
          color: "#B5B1AD",
        },
      },
    },
  },
  categorySeparator: {
    height: "1px",
    width: "100%",
    backgroundColor: "#E1DEDA",
  },
  categoryIcon: {
    width: "20px",
    height: "20px",

    "& path": {
      fill: "#282624",
    },
  },
  categoryIconActive: {
    "& path": {
      fill: "var(--primary-500)",
    },
  },
  categoryTitleActive: {
    color: "var(--primary-500)",
  },
}));

export const useContentHeaderStyles = makeStyles((theme) => ({
  container: {
    display: "flex",
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "16px 0px",
    margin: "0px 24px",
    borderBottom: "1px solid#E1DEDA",
  },
  badgeTitle: {
    fontSize: "14px",
    fontWeight: 600,
    lineHeight: "24px",
  },
  iconDiv: {
    display: "flex",
    padding: "8px",
    justifyContent: "center",
    alignItems: "center",
    borderRadius: "8px",
    background: "var(--colors-shades-stone-100, #F9F8F8)",
    marginRight: "16px",
  },
}));
