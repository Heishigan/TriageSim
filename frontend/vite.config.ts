import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The built app goes into the Python package, so users need no Node.js.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../src/triagesim/web", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
