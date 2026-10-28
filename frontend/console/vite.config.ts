/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The console always calls the API same-origin under /api: nginx proxies it in the
// container, and the dev server proxies it to the local API (WTPDM_API_URL).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: process.env.WTPDM_API_URL ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: { echarts: ["echarts"], markdown: ["react-markdown", "remark-gfm"] },
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
