/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Only these exact variables are passed to the browser bundle (no VITE_ prefix needed).
// Everything else in the environment (e.g. server secrets) stays out of the build.
const PUBLIC_ENV = ["API_BASE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY"] as const;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), ""); // .env files + process.env (Vercel env vars)
  const define = Object.fromEntries(
    PUBLIC_ENV.map((k) => [`__${k}__`, JSON.stringify(env[k] ?? env[`VITE_${k}`] ?? "")]),
  );
  return {
    plugins: [react()],
    define,
    server: { port: 5173, host: true },
    build: {
      rollupOptions: {
        output: { manualChunks: { charts: ["recharts"], vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"] } },
      },
    },
    test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
  };
});
