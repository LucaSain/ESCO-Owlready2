import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library does not auto-cleanup outside of Jest's global
// afterEach hook, so do it ourselves between tests to avoid leaking DOM
// nodes (and duplicate role matches) across test cases.
afterEach(() => {
  cleanup();
});
