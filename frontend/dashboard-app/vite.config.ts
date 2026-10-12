import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // `npm run dev` talks to the chatbot container directly; in Docker, nginx routes /api/chat.
    proxy: {
      "/api/chat": "http://localhost:8090",
    },
  },
});
