import { type Theme } from "@mui/material";
import { makeStyles } from "@mui/styles";

const useStyles = makeStyles((theme: Theme) => ({
  "navbar-logo-container": {
    width: "40px",
    height: "40px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
    "& svg": {
      width: "100%",
      height: "100%",
      display: "block",
      flexShrink: 0,
    },
  },
  "navbar-container": {
    position: "fixed",
    height: "100vh",
    width: "72px",
    backgroundColor: "#171717",
    padding: "24px 12px",
    display: "flex",
    flexDirection: "column",
    rowGap: "34px",
    alignItems: "center",
    zIndex: 1000,
  },
  "navigation-items-wrapper": {
    display: "flex",
    flexDirection: "column",
    rowGap: "16px",
  },
  "navigation-item-container": {
    height: "48px",
    width: "48px",
    display: "flex",
    flexDirection: "column",
    justifyContent: "center",
    alignItems: "center",
    padding: "12px",
  },
  iconContainer: {
    "&:hover": {
      cursor: "pointer",
      borderRadius: "8px",
      background: "#35312D",
    },
    "&.active": {
      borderRadius: "8px",
      background: "#35312D",

      "& svg": {
        "& path": {
          fill: "rgba(255, 255, 255, 0.40)",
        },
      },
    },
  },
  "navbar-item-container": {
    "& .navbar-item": {
      backgroundColor: "transparent",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      alignItems: "center",
      width: "72px",
      height: "72px",
      textDecoration: "none",

      "& .navbar-item-icon-container": {
        alignItems: "center",
        display: "flex",
        justifyContent: "center",
        position: "relative",
        height: "36px",
        width: "36px",
        borderRadius: "8px",
        marginBottom: "4px",

        "& .navbar-item-icon": {
          transition: "transform .125s cubic-bezier(.17,.67,.55,1.09)",
          "& path": { opacity: 0.6 },
        },
      },

      "& .item-display-name": {
        color: "#E1DEDA",
        textAlign: "center",
        fontSize: "10px",
        fontWeight: 500,
        lineHeight: "14px",
        letterSpacing: "0.3px",
      },

      "&:hover": {
        "& .navbar-item-icon-container": {
          background: "rgba(223, 190, 159, 0.20)",
          "& .navbar-item-icon": {
            transform: "scale(1.15)",
            "& path": {
              fill: "#FFFFFF",
              stroke: "#FFFFFF",
            },
          },
        },
        "& .item-display-name": { color: "#FFF", fontWeight: 700 },
      },

      "&.active": {
        "& .navbar-item-icon-container": {
          background: "rgba(223, 190, 159, 0.20)",

          "& .navbar-item-icon": {
            transform: "scale(1.15)",

            "& path": {
              fill: "#FFFFFF",
              stroke: "#FFFFFF",
              opacity: 1,
            },
          },
        },
        "& .item-display-name": { color: "#FFF", fontWeight: 700 },
      },
    },
  },
}));

export default useStyles;
