import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: Object.fromEntries(
      ["/api", "/oauth", "/.well-known", "/mcp"].map((path) => [
        path,
        "http://127.0.0.1:8000",
      ]),
    ),
  },
});
