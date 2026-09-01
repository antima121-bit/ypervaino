import { type PaletteOptions } from "@mui/material/styles/createPalette";

const palette: PaletteOptions = {
  base: {
    white: "#ffffff",
    black: "#282624",
  },
  stone: {
    50: "#fcfcfb",
    100: "#f9f8f8",
    200: "#f3f2f0",
    300: "#edebe9",
    400: "#e7e5e1",
    500: "#e1deda",
    600: "#b5b1ad",
    700: "#7c7972",
    800: "#35312d",
    900: "#282624",
  },
  primary: {
    light: "#fbf3ef",
    main: "#f07400",
    dark: "#331901",
    50: "#fbf3ef",
    100: "#ffe5cd",
    200: "#ffcb9b",
    300: "#ffb168",
    400: "#ff7b00",
    500: "#f07400",
    600: "#c9671d",
    700: "#994b02",
    800: "#663202",
    900: "#331901",
  },
  sky: {
    50: "#f5fcff",
    100: "#eaf9fe",
    200: "#d6f2fe",
    300: "#c1ecfd",
    400: "#ade5fd",
    500: "#98dffc",
    600: "#78c7e7",
    700: "#3a91b4",
    800: "#216986",
    900: "#034c69",
  },
  secondary: {
    light: "#F7F2FD",
    main: "#AD79EF",
    dark: "#2B124B",
  },
  error: {
    light: "#FCE8E4",
    main: "#E53811",
    dark: "#2E0B03",
  },
  background: {
    default: "#f9f8f8",
  },
};

declare module "@mui/material/styles/createPalette" {
  interface PaletteOptions {
    base?: {
      white: string;
      black: string;
    };
    stone?: PaletteColorOptions;
    primary?: PaletteColorOptions;
    secondary?: PaletteColorOptions;
    sky?: {
      50: string;
      100: string;
      200: string;
      300: string;
      400: string;
      500: string;
      600: string;
      700: string;
      800: string;
      900: string;
    };
    error?: PaletteColorOptions;
  }

  interface Palette {
    base?: {
      white: string;
      black: string;
    };
    stone?: PaletteColor;
    primary: PaletteColor;
    secondary: PaletteColor;
    sky?: {
      50: string;
      100: string;
      200: string;
      300: string;
      400: string;
      500: string;
      600: string;
      700: string;
      800: string;
      900: string;
    };
    error: PaletteColor;
  }
}

export default palette;
