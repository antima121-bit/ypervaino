import { createTheme } from "@mui/material";
import palette from "./palette";
import typography from "./typography";
import shadows, { type BoxShadowsProps } from "./boxShadows";
import overrides from "./override";

export const monoFont = "'Roboto Mono', monospace";

declare module "@mui/material/styles" {
  interface Theme {
    boxShadows: BoxShadowsProps;
  }

  interface ThemeOptions {
    boxShadows?: BoxShadowsProps;
  }
}

const theme = createTheme({
  palette,
  typography,
  components: overrides,
  boxShadows: shadows,
});

export default theme;
