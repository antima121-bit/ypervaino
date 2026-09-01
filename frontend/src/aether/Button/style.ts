import { makeStyles } from "@mui/styles";
import { type Theme } from "@mui/material/styles";
import { ButtonSizes, type ButtonCustomColorProps } from ".";

const useStyles = makeStyles((theme: Theme) => ({
  root: {
    borderRadius: "8px",
    textTransform: "none",
    boxSizing: "border-box",

    "&.MuiButton-root": {
      minWidth: "auto",

      "& .MuiButton-startIcon": {
        marginLeft: 0,
        marginRight: 8,
      },

      "& .MuiButton-endIcon": {
        marginLeft: 8,
        marginRight: 0,
      },

      "& .MuiCircularProgress-root": {
        color: "inherit",
        display: "inline-flex",

        "& svg": {
          width: "100%",
          height: "100%",
        },
      },

      "&.Mui-disabled": {
        backgroundColor: "#E1DEDA !important",
        color: "#B5B1AD !important",

        "& svg": {
          "& path": {
            fill: "#B5B1AD",
          },
        },
      },
    },
  },
  loader: {
    flexShrink: 0,
  },
  text: (props: {
    color: string;
    customColors: ButtonCustomColorProps;
    size: ButtonSizes;
  }) => ({
    color: {
      primary: "#F07400",
      secondary: "#E7FDF3",
      tertiary: "#fff3cd",
      warning: "#f8d7da",
      error: "#E53811",
      custom: props?.customColors?.color,
    }[props.color],

    "& svg": {
      height: {
        xsmall: "16px",
        small: "18px",
        medium: "20px",
        large: "24px",
      }[props.size],
      width: {
        xsmall: "16px",
        small: "18px",
        medium: "20px",
        large: "24px",
      }[props.size],

      "& path": {
        fill: {
          primary: "#F07400",
          secondary: "#E7FDF3",
          tertiary: "#fff3cd",
          warning: "#f8d7da",
          error: "#E53811",
          custom: props?.customColors?.backgroundColor,
        }[props.color],
      },
    },

    "&:hover": {
      backgroundColor: "transparent",
      color: {
        primary: "#FF7B00",
        secondary: "#E7FDF3",
        tertiary: "#fff3cd",
        warning: "#f8d7da",
        error: "#EF866F",
        custom: props?.customColors?.backgroundColor,
      }[props.color],

      "& svg": {
        "& path": {
          fill: {
            primary: "#FF7B00",
            secondary: "#E7FDF3",
            tertiary: "#fff3cd",
            warning: "#f8d7da",
            error: "#EF866F",
            custom: props?.customColors?.backgroundColor,
          }[props.color],
        },
      },
    },
  }),
  contained: (props: {
    color: string;
    customColors: ButtonCustomColorProps;
  }) => ({
    color: "#FFF",
    background: {
      primary: "#F07400",
      secondary: "#FFF",
      tertiary: "#fff3cd",
      warning: "#f8d7da",
      error: "#E53811",
      custom: props?.customColors?.backgroundColor,
    }[props.color],

    "& svg": {
      height: "16px",
      width: "16px",

      "& path": {
        fill: {
          primary: "#FFF",
          secondary: "#282624",
          tertiary: "#FFF",
          warning: "#FFF",
          error: "#FFF",
          custom: props?.customColors?.color,
        }[props.color],
      },
    },

    "&:hover": {
      background: {
        primary: "#FF7B00",
        secondary: "#FFF",
        tertiary: "#fff3cd",
        warning: "#f8d7da",
        error: "#EF866F",
        custom: props?.customColors?.backgroundColor,
      }[props.color],
    },
  }),
  outlined: (props: {
    color: string;
    customColors: ButtonCustomColorProps;
  }) => ({
    border: "1px solid",
    background: "#FFF",

    color: {
      primary: "#F07400",
      secondary: "#282624",
      tertiary: "#282624",
      warning: "#FFF",
      error: "#FFF",
      custom: props?.customColors?.color,
    }[props.color],
    borderColor: {
      primary: "#F07400",
      secondary: "#E1DEDA",
      tertiary: "#282624",
      warning: "#FFF",
      error: "#FFF",
      custom: props?.customColors?.borderColor,
    }[props.color],
    "& svg": {
      height: "16px",
      width: "16px",

      "& path": {
        fill: {
          primary: "#F07400",
          secondary: "#282624",
          tertiary: "#282624",
          warning: "#FFF",
          error: "#FFF",
          custom: props?.customColors?.color,
        }[props.color],
      },
    },

    "&:hover": {
      backgroundColor: "#F9F8F8",
    },
  }),

  xsmall: {
    "&.MuiButton-root": {
      height: "32px",
      padding: "8px 16px",
      fontSize: "14px",
      fontWeight: "600",
      letterSpacing: "0.14px",
    },
  },
  small: {
    "&.MuiButton-root": {
      height: "40px",
      padding: "8px 16px",
      fontSize: "16px",
      fontWeight: "700",
      letterSpacing: "0.16px",
    },
  },
  medium: {
    "&.MuiButton-root": {
      height: "48px",
      padding: "12px 24px",
      fontSize: "16px",
      fontWeight: "700",
      letterSpacing: "0.16px",
    },
  },
  large: {
    "&.MuiButton-root": {
      height: "56px",
      padding: "16px 32px",
      fontSize: "16px",
      fontWeight: "700",
      letterSpacing: "0.16px",
    },
  },
}));

export default useStyles;
