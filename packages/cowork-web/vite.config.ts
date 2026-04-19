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
        // No static headers here. The React client puts ``x-cowork-token``
        // on every fetch (see CoworkClient.headers()), so adding a second
        // copy here would either be redundant (single-token mode) or
        // *overwrite* the client's value (multi-user mode, where each
        // tab authenticates as a different user via ``?token=…``). Let
        // the client own the token.
      },
    },
  },
  define: {
    // Build-time default token — used in browser mode when neither the
    // Tauri sidecar nor a ``?token=…`` URL param supplies one. Fine for
    // single-token dev loops; ignored under multi-user auth where each
    // tab explicitly sets its own key.
    __COWORK_TOKEN__: JSON.stringify(serverToken),
  },
});
