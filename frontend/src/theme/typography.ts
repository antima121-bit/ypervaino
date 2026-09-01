import { type TypographyOptions } from "@mui/material/styles/createTypography";

const typography: TypographyOptions = {
  fontFamily: "Manrope, sans-serif",
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
};

declare module "@mui/material/styles" {
  interface TypographyVariants {
    textTiny: React.CSSProperties;
    textSmall: React.CSSProperties;
    text: React.CSSProperties;
    textLarge: React.CSSProperties;
    textXL: React.CSSProperties;
    textXXL: React.CSSProperties;
    textXXXL: React.CSSProperties;
  }

  interface TypographyVariantsOptions {
    textTiny?: React.CSSProperties;
    textSmall?: React.CSSProperties;
    text?: React.CSSProperties;
    textLarge?: React.CSSProperties;
    textXL?: React.CSSProperties;
    textXXL?: React.CSSProperties;
    textXXXL?: React.CSSProperties;
  }
}

declare module "@mui/material/Typography" {
  interface TypographyPropsVariantOverrides {
    tinyCaution: true;
    textTiny: true;
    textSmall: true;
    text: true;
    textLarge: true;
    textXL: true;
    textXXL: true;
    textXXXL: true;
  }
}

export default typography;
