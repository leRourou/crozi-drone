import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const repoRoot = fileURLToPath(new URL("..", import.meta.url));
const sharedModule = fileURLToPath(new URL("../vendor/edth/audio_capture.js", import.meta.url));
const contracts = fileURLToPath(new URL("../contracts", import.meta.url));
const backend = process.env.CROZIDRONE_BACKEND ?? "http://127.0.0.1:8000";
// Hôtes HTTPS de tunnel autorisés (ngrok, Tailscale Serve) ; ajouter les vôtres via CROZIDRONE_ALLOWED_HOSTS.
const extraHosts = (process.env.CROZIDRONE_ALLOWED_HOSTS ?? "").split(",").filter(Boolean);

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Le module partagé est importé tel quel, hors de front/ (jamais copié ni converti).
    // Contrats partagés avec le serveur (profils…), importés au build depuis la racine du dépôt.
    alias: { "@edth/capture": sharedModule, "@contracts": contracts },
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
