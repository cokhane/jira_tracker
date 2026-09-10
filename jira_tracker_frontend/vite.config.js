import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on :5173 (already allowed by the FastAPI CORS config).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
