import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: { proxy: { "/api": loadEnv(mode, ".", "VITE_").VITE_API_URL ?? "http://127.0.0.1:8001" } },
  test: { environment: "jsdom", setupFiles: "./tests/setup.ts" },
}));
