import React from "react";
import {
  type IconButtonProps as MuiIconButtonProps,
  CircularProgress,
  IconButton as MuiIconButton,
  Tooltip,
} from "@mui/material";
import clsx from "clsx";
import useStyles from "./style";

export interface CustomColorProps {
  color?: string;
  backgroundColor?: string;
  borderColor?: string;
}

type IconButtonVariant = "icon" | "contained" | "outlined";
type IconButtonSize = "xsmall" | "small" | "medium" | "large";
type IconButtonColor =
  | "primary"
  | "secondary"
  | "tertiary"
  | "warning"
  | "error"
  | "custom";

export interface IconButtonProps
  extends Omit<MuiIconButtonProps, "variant" | "size" | "color"> {
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  color?: IconButtonColor;
  customColors?: CustomColorProps;
  tooltip?: string;
  disabledTooltip?: string;
  loading?: boolean;
}

const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(
  (
    {
      variant = "icon",
      size = "small",
      color = "primary",
      children,
      className,
      customColors = { color: "#000000", backgroundColor: "#ffffff" },
      tooltip,
      disabledTooltip,
      disabled,
      loading = false,
      ...props
    },
    ref
  ) => {
    const classes = useStyles({
      color,
      customColors,
    });

    const buttonClasses = clsx(
      classes.root,
      classes[variant],
      classes[size],
      className
    );
    const tooltipTitle = disabled ? disabledTooltip || "" : tooltip || "";

    const buttonElement = (
      <MuiIconButton
        ref={ref}
        className={buttonClasses}
        disabled={disabled}
        {...props}
      >
        {loading ? <CircularProgress size={18} /> : children}
      </MuiIconButton>
    );

    return (
      <Tooltip title={tooltipTitle} arrow>
        {disabled ? <span>{buttonElement}</span> : buttonElement}
      </Tooltip>
    );
  }
);

IconButton.displayName = "IconButton";

export default IconButton;
