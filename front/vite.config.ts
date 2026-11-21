import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const sharedModule = fileURLToPath(new URL("../vendor/edth/audio_capture.js", import.meta.url));
const backend = process.env.THC_BACKEND ?? "http://127.0.0.1:8000";
// Hôtes HTTPS de tunnel autorisés (ngrok, Tailscale Serve) ; ajouter les vôtres via THC_ALLOWED_HOSTS.
const extraHosts = (process.env.THC_ALLOWED_HOSTS ?? "").split(",").filter(Boolean);

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Le module partagé est importé tel quel, hors de front/ (jamais copié ni converti).
    alias: { "@edth/capture": sharedModule },
  },
  server: {
    fs: { allow: [repoRoot] },
    allowedHosts: [".ngrok-free.app", ".ngrok.app", ".ts.net", ...extraHosts],
    proxy: { "/ws": { target: backend, ws: true, changeOrigin: true } },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    coverage: { provider: "v8", reporter: ["text", "lcov"], include: ["src/**/*.ts"] },
  },
});
