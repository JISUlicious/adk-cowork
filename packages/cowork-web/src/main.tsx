import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { bootstrapTheme } from "./theme";
import { getServerFromTauri, isTauri } from "./transport/tauri";

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
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App baseUrl={baseUrl} token={token} />
    </StrictMode>,
  );
}

void bootstrap();
