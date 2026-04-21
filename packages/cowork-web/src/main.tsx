import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { applyAppearance, loadPreferences } from "./preferences";
import { bootstrapTheme } from "./theme";
import { getServerFromTauri, isTauri } from "./transport/tauri";

// Apply user appearance (density / layout / accent + static
// refinement) and theme BEFORE React mounts so the first paint
// already reflects the chosen palette — avoids a flash of the
// default look.
applyAppearance(loadPreferences());
bootstrapTheme();

async function bootstrap() {
  let baseUrl: string | undefined;
  let token: string | undefined;

  if (isTauri()) {
    const info = await getServerFromTauri();
    if (info) {
      baseUrl = info.url;
      token = info.token;
    } else {
      console.error("Tauri sidecar did not publish server info");
    }
  } else {
    // Browser mode: let the page-load URL override the build-time token
    // via ``?token=…``. Useful for multi-user dev — the same Vite bundle
    // embeds one build-time token, but different tabs can authenticate
    // as different users without rebuilding.
    const fromQuery = new URLSearchParams(window.location.search).get("token");
    if (fromQuery) token = fromQuery;
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App baseUrl={baseUrl} token={token} />
    </StrictMode>,
  );
}

void bootstrap();
