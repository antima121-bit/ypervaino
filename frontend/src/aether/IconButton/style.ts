import { makeStyles } from "@mui/styles";
import { type Theme } from "@mui/material/styles";
import { type CustomColorProps } from ".";

const ICON_COLOR: Record<string, string> = {
  primary: "#F07400",
  secondary: "#35312D",
  tertiary: "#282624",
  warning: "#FFA959",
  error: "#E53811",
};

const SIZE_BOX: Record<string, { box: number; icon: number }> = {
  xsmall: { box: 32, icon: 16 },
  small: { box: 40, icon: 24 },
  medium: { box: 48, icon: 24 },
  large: { box: 56, icon: 28 },
};

interface IconButtonStyleProps {
  color: string;
  customColors: CustomColorProps;
}

const useStyles = makeStyles((theme: Theme) => ({
  root: {
    padding: "8px",
    borderRadius: "8px",
    "&.Mui-disabled svg path": {
      fill: "#9E9B97",
    },
  },
  icon: (props: IconButtonStyleProps) => {
    const fill = props.color === "custom" ? props.customColors?.color : ICON_COLOR[props.color];
    return {
      backgroundColor: "transparent",
      "& svg path": { fill },
      "&:hover": { "& svg path": { fill: props.color === "primary" ? "#FF7B00" : fill } },
    };
  },
  contained: (props: IconButtonStyleProps) => {
    const bg = props.color === "custom" ? props.customColors?.backgroundColor : ICON_COLOR[props.color];
    return {
      backgroundColor: bg,
      "& svg path": { fill: "#FFF" },
      "&:hover": { backgroundColor: props.color === "primary" ? "#FF7B00" : bg },
    };
  },
  outlined: {
    backgroundColor: "#FFF",
    border: "1px solid #E1DEDA",
    "&:hover": { backgroundColor: "#F9F8F8" },
  },
  xsmall: (props: IconButtonStyleProps) => ({
    width: SIZE_BOX.xsmall.box,
    height: SIZE_BOX.xsmall.box,
    "& svg": { width: SIZE_BOX.xsmall.icon, height: SIZE_BOX.xsmall.icon },
  }),
  small: (props: IconButtonStyleProps) => ({
    width: SIZE_BOX.small.box,
    height: SIZE_BOX.small.box,
    "& svg": { width: SIZE_BOX.small.icon, height: SIZE_BOX.small.icon },
  }),
  medium: (props: IconButtonStyleProps) => ({
    width: SIZE_BOX.medium.box,
    height: SIZE_BOX.medium.box,
    "& svg": { width: SIZE_BOX.medium.icon, height: SIZE_BOX.medium.icon },
  }),
  large: (props: IconButtonStyleProps) => ({
    width: SIZE_BOX.large.box,
    height: SIZE_BOX.large.box,
    "& svg": { width: SIZE_BOX.large.icon, height: SIZE_BOX.large.icon },
  }),
}));

export default useStyles;
