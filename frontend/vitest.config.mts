import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Vite resolves tsconfig `paths` (the @/* alias) natively now, so the
  // vite-tsconfig-paths plugin it used to need is redundant and warns on
  // startup.
  resolve: { tsconfigPaths: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    exclude: ["node_modules/**", ".next/**", "out/**"],
  },
});
