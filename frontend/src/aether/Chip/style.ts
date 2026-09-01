import { makeStyles } from "@mui/styles";
import { type Theme } from "@mui/material/styles";
import { type CustomColorProps } from ".";

const COLOR_MAP: Record<string, { bg: string; text: string; border: string }> = {
  default: { bg: "#F3F2F0", text: "#344054", border: "#E1DEDA" },
  success: { bg: "#E7FDF3", text: "#027A48", border: "#027A48" },
  warning: { bg: "#fff3cd", text: "#856404", border: "#856404" },
  error: { bg: "#f8d7da", text: "#721c24", border: "#721c24" },
  none: { bg: "transparent", text: "#282624", border: "#E1DEDA" },
};

const SIZE_PADDING: Record<string, string> = {
  xsmall: "2px 8px",
  small: "2px 8px",
  medium: "2px 10px",
  large: "4px 12px",
};

interface ChipStyleProps {
  size: string;
  color: string;
  customColors: CustomColorProps;
}

const useStyles = makeStyles((theme: Theme) => ({
  root: {
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    borderRadius: "16px",
    mixBlendMode: "multiply",
    width: "fit-content",
  },
  startIconContainer: {
    display: "flex",
    alignItems: "center",
    "& svg": { width: "14px", height: "14px" },
  },
  endIconContainer: {
    display: "flex",
    alignItems: "center",
    "& svg": { width: "14px", height: "14px" },
  },
  contained: (props: ChipStyleProps) => {
    const c = props.color === "custom"
      ? { bg: props.customColors?.backgroundColor, text: props.customColors?.color, border: "transparent" }
      : COLOR_MAP[props.color] ?? COLOR_MAP.default;
    return {
      backgroundColor: c.bg,
      color: c.text,
    };
  },
  outlined: (props: ChipStyleProps) => {
    const c = props.color === "custom"
      ? { bg: "transparent", text: props.customColors?.color, border: props.customColors?.borderColor }
      : COLOR_MAP[props.color] ?? COLOR_MAP.default;
    return {
      backgroundColor: "transparent",
      color: c.text,
      border: `1.5px solid ${c.border}`,
    };
  },
  xsmall: (props: ChipStyleProps) => ({ padding: SIZE_PADDING.xsmall }),
  small: (props: ChipStyleProps) => ({ padding: SIZE_PADDING.small }),
  medium: (props: ChipStyleProps) => ({ padding: SIZE_PADDING.medium }),
  large: (props: ChipStyleProps) => ({ padding: SIZE_PADDING.large }),
}));

export default useStyles;
