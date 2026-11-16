import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The SPA and the API share one origin, in development (through this proxy)
// and in production (through the reverse proxy). That is what lets the
// session live in an HttpOnly, SameSite cookie with no CORS configuration.
const apiTarget = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // changeOrigin stays false so Django sees the browser's Host header and
      // its CSRF origin check compares like with like.
      "/api": { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
