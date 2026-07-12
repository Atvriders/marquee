/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  build: {
    // Local/dev build lands directly in the Python package's static dir so
    // FastAPI serves it. The Docker build overrides this with --outDir dist.
    outDir: fileURLToPath(new URL("../backend/marquee/api/static", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://localhost:3022",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/setupTests.ts",
    css: false,
  },
});
