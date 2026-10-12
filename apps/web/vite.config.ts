import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

import { securityHeaders } from "./src/securityHeaders";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    headers: securityHeaders(),
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    headers: securityHeaders(),
  },
  test: {
    environment: "jsdom",
    exclude: ["tests/e2e/**", "node_modules/**", "dist/**"],
  },
});
