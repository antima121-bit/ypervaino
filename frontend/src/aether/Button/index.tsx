import {
  CircularProgress,
  Button as MuiButton,
  Tooltip,
  type ButtonProps as MuiButtonProps,
} from "@mui/material";
import React from "react";
import useStyles from "./style";
import clsx from "clsx";

export enum ButtonVariants {
  text = "text",
  contained = "contained",
  outlined = "outlined",
}

export enum ButtonColors {
  primary = "primary",
  secondary = "secondary",
  tertiary = "tertiary",
  warning = "warning",
  success = "success",
  error = "error",
  custom = "custom",
}

export enum ButtonSizes {
  xsmall = "xsmall",
  small = "small",
  medium = "medium",
  large = "large",
}

type ButtonColor = ButtonColors;
type ButtonSize = ButtonSizes;

export interface ButtonCustomColorProps {
  color?: string;
  backgroundColor?: string;
  borderColor?: string;
}

export interface ButtonProps extends Omit<MuiButtonProps, "color" | "size"> {
  color?: ButtonColor | null;
  size?: ButtonSize;
  loading?: boolean;
  customColors?: ButtonCustomColorProps;
  disabledTooltip?: string;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = ButtonVariants.contained,
      size = ButtonSizes.medium,
      color = null,
      children,
      className,
      disabled,
      loading = false,
      startIcon,
      endIcon,
      disabledTooltip,
      customColors = { color: "#000000", backgroundColor: "#ffffff" },
      ...props
    },
    ref
  ) => {
    let _color = color;
    if (variant === ButtonVariants.contained && !_color) {
      _color = ButtonColors.primary;
    } else if (variant === ButtonVariants.outlined && !_color) {
      _color = ButtonColors.secondary;
    } else if (!_color) {
      _color = ButtonColors.primary;
    }

    const classes = useStyles({
      color: _color,
      customColors,
      size,
    });

    const buttonClasses = clsx(
      classes.root,
      classes[variant],
      classes[size],
      className
    );

    const muiSize =
      size === ButtonSizes.xsmall || size === ButtonSizes.small
        ? "small"
        : size === ButtonSizes.large
          ? "large"
          : "medium";

    const loaderSize = {
      [ButtonSizes.xsmall]: 16,
      [ButtonSizes.small]: 18,
      [ButtonSizes.medium]: 20,
      [ButtonSizes.large]: 24,
    }[size];

    const buttonContent = (): JSX.Element => {
      return (
        <MuiButton
          ref={ref}
          className={buttonClasses}
          size={muiSize}
          disabled={disabled || loading}
          startIcon={
            loading ? (
              <CircularProgress
                size={loaderSize}
                color="inherit"
                className={classes.loader}
              />
            ) : (
              startIcon
            )
          }
          endIcon={endIcon}
          {...props}
        >
          {children}
        </MuiButton>
      );
    };

    if (disabled && disabledTooltip) {
      return (
        <Tooltip title={disabledTooltip} arrow disableInteractive>
          <span>{buttonContent()}</span>
        </Tooltip>
      );
    }

    return buttonContent();
  }
);

Button.displayName = "Button";

export default Button;
