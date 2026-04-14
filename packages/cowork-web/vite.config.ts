import { resolve } from "path";
import { config as loadEnv } from "dotenv";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Load .env from monorepo root so COWORK_TOKEN / COWORK_PORT are available
loadEnv({ path: resolve(__dirname, "../../.env") });

const serverPort = process.env.COWORK_PORT || "9100";
const serverToken = process.env.COWORK_TOKEN || "";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/v1": {
        target: `http://127.0.0.1:${serverPort}`,
        changeOrigin: true,
        ws: true,
        headers: serverToken ? { "x-cowork-token": serverToken } : {},
      },
    },
  },
  define: {
    __COWORK_TOKEN__: JSON.stringify(serverToken),
  },
});
