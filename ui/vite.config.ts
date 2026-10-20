import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  build: {
    // Bundled into the Python package so `conveyor` can serve the UI locally.
    outDir: "../src/conveyor/_ui",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
  },
});
