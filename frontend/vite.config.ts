import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import svgr from "vite-plugin-svgr";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  base: "/app/",
  plugins: [
    react(),
    svgr({
      svgrOptions: { exportType: "named", namedExport: "ReactComponent" },
    }),
    tsconfigPaths(),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8765",
      "/sample_data": "http://localhost:8765",
    },
  },
  build: {
    outDir: "dist",
  },
});
