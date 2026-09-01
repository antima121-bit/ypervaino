import React from "react";
import {
  type TypographyProps as MuiTypographyProps,
  Typography as MuiTypography,
} from "@mui/material";
import clsx from "clsx";
import useStyles from "./style";

export enum TypographyVariants {
  textTiny = "textTiny",
  textSmall = "textSmall",
  text = "text",
  textLarge = "textLarge",
  textXL = "textXL",
  textXXL = "textXXL",
  textXXXL = "textXXXL",
}

export enum TypographyColors {
  default = "default",
  muted = "muted",
  subtle = "subtle",
  disabled = "disabled",
  placeholder = "placeholder",
  error = "error",
  white = "white",
  primary = "primary",
}

export enum TypographyWeights {
  normal = "normal",
  medium = "medium",
  semiBold = "semiBold",
  bold = "bold",
}

type TypographyVariant = TypographyVariants;
type TypographyColor = TypographyColors | string;
type TypographyWeight = TypographyWeights;

export interface TypographyProps extends Omit<MuiTypographyProps, "variant"> {
  variant?: TypographyVariant;
  color?: TypographyColor;
  weight?: TypographyWeight;
  renderInLines?: number;
}

const Typography = React.forwardRef<HTMLSpanElement, TypographyProps>(
  (
    {
      variant = TypographyVariants.text,
      color = TypographyColors.default,
      weight = TypographyWeights.normal,
      children,
      className,
      renderInLines = null,
      sx,
      ...props
    },
    ref
  ) => {
    const classes = useStyles({ renderInLines: renderInLines ?? 0 });

    const isCustomColor =
      typeof color === "string" &&
      !Object.values(TypographyColors).includes(color as TypographyColors);
    const colorClass = isCustomColor ? undefined : classes[color as TypographyColors];
    const customColorStyle = isCustomColor ? { color } : {};

    const typographyClasses = clsx(
      classes.root,
      classes[variant],
      colorClass,
      classes[weight],
      className
    );

    return (
      <MuiTypography
        ref={ref}
        className={typographyClasses}
        sx={{ ...customColorStyle, ...sx }}
        {...props}
      >
        {children}
      </MuiTypography>
    );
  }
);

Typography.displayName = "Typography";

export default Typography;
