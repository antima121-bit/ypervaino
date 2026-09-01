import { makeStyles } from "@mui/styles";
import { type Theme } from "@mui/material/styles";

const useStyles = makeStyles((theme: Theme) => ({
  root: ({ renderInLines }: { renderInLines?: number }) => ({
    ...(renderInLines && {
      display: "-webkit-box",
      overflow: "hidden",
      WebkitLineClamp: renderInLines,
      textOverflow: "ellipsis",
      WebkitBoxOrient: "vertical",
    }),
  }),
  textTiny: {
    fontSize: "10px",
    lineHeight: "16px",
    letterSpacing: "0.2px",
  },
  textSmall: {
    fontSize: "12px",
    lineHeight: "20px",
    letterSpacing: "0px",
  },
  text: {
    fontSize: "14px",
    lineHeight: "24px",
    letterSpacing: "0px",
  },
  textLarge: {
    fontSize: "16px",
    lineHeight: "28px",
    letterSpacing: "0px",
  },
  textXL: {
    fontSize: "20px",
    lineHeight: "28px",
    letterSpacing: "-0.2px",
  },
  textXXL: {
    fontSize: "24px",
    lineHeight: "32px",
    letterSpacing: "-0.3px",
  },
  textXXXL: {
    fontSize: "32px",
    lineHeight: "40px",
    letterSpacing: "-0.5px",
  },
  default: {
    color: "var(--text-color-default)",
  },
  muted: {
    color: "var(--text-color-muted)",
  },
  subtle: {
    color: "var(--text-color-subtle)",
  },
  disabled: {
    color: "var(--text-color-disabled)",
  },
  placeholder: {
    color: "var(--text-color-placeholder)",
  },
  error: {
    color: "var(--text-color-error)",
  },
  white: {
    color: "var(--text-color-white)",
  },
  primary: {
    color: "var(--text-color-primary)",
  },
  normal: {
    fontWeight: "var(--font-weight-normal)",
  },
  medium: {
    fontWeight: "var(--font-weight-medium)",
  },
  semiBold: {
    fontWeight: "var(--font-weight-semi-bold)",
  },
  bold: {
    fontWeight: "var(--font-weight-bold)",
  },
}));

export default useStyles;
