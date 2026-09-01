import React from "react";
import useStyles from "./style";
import clsx from "clsx";
import Typography, {
  TypographyVariants,
  TypographyWeights,
} from "aether/Typography";

export enum ChipVariants {
  contained = "contained",
  outlined = "outlined",
}

export enum ChipColors {
  default = "default",
  success = "success",
  warning = "warning",
  error = "error",
  none = "none",
  custom = "custom",
}

export enum ChipSizes {
  xsmall = "xsmall",
  small = "small",
  medium = "medium",
  large = "large",
}

type ChipVariant = ChipVariants;
type ChipColor = ChipColors;
type ChipSize = ChipSizes;

export interface CustomColorProps {
  color?: string;
  backgroundColor?: string;
  borderColor?: string;
}

export interface ChipProps {
  label: string;
  variant?: ChipVariant;
  color?: ChipColor;
  customColors?: CustomColorProps;
  size?: ChipSize;
  className?: string;
  startIcon?: React.ReactNode;
  endIcon?: React.ReactNode;
}

const Chip = React.forwardRef<HTMLDivElement, ChipProps>(
  (
    {
      variant = ChipVariants.contained,
      color = ChipColors.default,
      size = ChipSizes.small,
      label,
      className,
      customColors = { color: "#000000", backgroundColor: "#ffffff" },
      startIcon,
      endIcon,
    },
    ref
  ) => {
    const classes = useStyles({ size, color, customColors });

    const chipClasses = clsx(
      classes.root,
      classes[variant],
      classes[size],
      className
    );

    return (
      <div ref={ref} className={chipClasses}>
        {startIcon ? (
          <div className={classes.startIconContainer}>{startIcon}</div>
        ) : null}
        {size === ChipSizes.xsmall ? (
          <Typography
            style={{ whiteSpace: "nowrap", color: "inherit" }}
            variant={TypographyVariants.textSmall}
            weight={TypographyWeights.semiBold}
          >
            {label}
          </Typography>
        ) : (
          <Typography
            style={{ whiteSpace: "nowrap", color: "inherit" }}
            weight={TypographyWeights.semiBold}
          >
            {label}
          </Typography>
        )}
        {endIcon ? (
          <div className={classes.endIconContainer}>{endIcon}</div>
        ) : null}
      </div>
    );
  }
);

Chip.displayName = "Chip";

export default Chip;
