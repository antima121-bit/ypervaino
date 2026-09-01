import { type Components, type Theme } from "@mui/material/styles";

const overrides: Components<Theme> = {
  MuiCssBaseline: {
    styleOverrides: `
        @font-face {
        font-family: "Manrope", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans",
        "Droid Sans", "Helvetica Neue", sans-serif;
        }
    `,
  },
  MuiInputBase: {
    styleOverrides: {
      root: {
        height: "48px",
        backgroundColor: "#fff",

        "&.MuiInputBase-sizeSmall": {
          height: "40px",
        },
        "&::before": {
          borderBottom: "1px solid rgba(0, 0, 0, 0.42) !important",
        },
        "&::after": {
          borderBottom: "2px solid #FF7D04 !important",
        },
        "&:hover:not(.Mui-disabled, .Mui-error):before": {
          borderBottom: "1px solid rgba(0, 0, 0, 0.42) !important",
        },
      },
      input: {
        color: "#35312D",
        fontSize: "1rem",
        fontStyle: "normal",
        fontWeight: 400,
        lineHeight: "150%",
        "&.Mui-disabled": {
          WebkitTextFillColor: "#7C7972",
        },
      },
      inputMultiline: {
        fontSize: "1rem",
      },
    },
  },
  MuiOutlinedInput: {
    styleOverrides: {
      root: {
        "&.Mui-disabled": {
          background: "#F3F2F0",
        },
        "& .MuiOutlinedInput-notchedOutline": {
          border: "1px solid #E1DEDA",
          borderRadius: "8px",
        },
        "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
          borderColor: "#FF7D04",
          boxShadow: "0px 0px 0px 4px rgba(255, 125, 4, 0.13)",
        },
        "&.MuiInputBase-multiline .MuiOutlinedInput-notchedOutline": {
          borderRadius: "8px",
        },
        "&.Mui-error": {
          "& .MuiOutlinedInput-notchedOutline": {
            borderColor: "#E1DEDA",
            boxShadow: "none",
          },

          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: "#E1DEDA",
            boxShadow:
              "0px 0px 0px 4px #FEE4E2, 0px 1px 2px 0px rgba(16, 24, 40, 0.05)",
          },
        },
        "&.MuiInputBase-multiline": {
          height: "unset",
        },
      },
    },
  },
  MuiAutocomplete: {
    styleOverrides: {
      root: {
        "& .MuiOutlinedInput-root": {
          padding: 0,
          "& .MuiAutocomplete-input": {
            padding: "10px 14px",
          },
        },
      },
      option: {
        padding: "10px",
        fontWeight: 600,
        fontSize: "1rem",
        lineHeight: "175%",
      },
    },
  },
  MuiFormHelperText: {
    styleOverrides: {
      root: {
        color: "#7C7972",
        fontSize: "0.875rem",
        fontStyle: "normal",
        fontWeight: 400,
        lineHeight: "150%",
        marginLeft: 0,
        marginTop: "6px",
      },
    },
  },
  MuiTableContainer: {
    styleOverrides: {
      root: {
        border: "1px solid #FCFCFB",
        borderRadius: "12px",
        boxShadow:
          "0px 1px 2px 0px rgba(16, 24, 40, 0.06), 0px 1px 3px 0px rgba(16, 24, 40, 0.10)",

        "&::-webkit-scrollbar": {
          width: 0,
        },

        "& .MuiTableCell-root": {
          padding: "16px 24px",
        },

        "& .MuiTableCell-head": {
          backgroundColor: "#FCFCFB",
        },

        "& .MuiTableRow-root": {
          "&:last-child td": {
            borderBottom: 0,
          },
        },
      },
    },
  },
  MuiPaper: {
    styleOverrides: {
      rounded: {
        borderRadius: 8,
        boxShadow:
          "0px 4px 6px -2px rgba(16, 24, 40, 0.03),0px 12px 16px -4px rgba(16, 24, 40, 0.08)",
      },
    },
  },
  MuiDialog: {
    styleOverrides: {
      paper: {
        padding: 24,
      },
    },
  },
  MuiDrawer: {
    styleOverrides: {
      paper: {
        borderRadius: "8px 0 0 8px",
      },
    },
  },
  MuiFormControlLabel: {
    styleOverrides: {
      root: {
        "& .MuiTypography-root": {
          fontSize: "0.875rem",
          fontStyle: "normal",
          fontWeight: 600,
          lineHeight: " 150%",
        },
      },
    },
  },
  MuiRadio: {
    styleOverrides: {
      root: {
        padding: "8px",
        "& .MuiSvgIcon-root": {
          height: 16,
          width: 16,
        },
        "&.Mui-checked": {
          color: "#FF7D04",
        },
      },
    },
  },
  MuiTabs: {
    styleOverrides: {
      indicator: {
        height: "2px",
        backgroundColor: "#FF7D04",
      },
    },
  },
  MuiTab: {
    styleOverrides: {
      root: {
        fontSize: "16px",
        fontWeight: 600,

        "&.Mui-selected": {
          color: "#E06F06",
        },
      },
    },
  },
  MuiCircularProgress: {
    styleOverrides: {
      root: {
        "&.MuiCircularProgress-colorPrimary": {
          color: "#FF7D04",
        },
      },
    },
  },
  MuiButton: {
    styleOverrides: {
      root: {
        whiteSpace: "nowrap",
      },
    },
  },
};

export default overrides;
