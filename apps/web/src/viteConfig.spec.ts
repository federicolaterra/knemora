import { describe, expect, it } from "vitest";

import { securityHeaders } from "./securityHeaders";

describe("Vite security headers", () => {
  it("allows the native graph layout worker", () => {
    expect(securityHeaders()["Content-Security-Policy"]).toContain(
      "worker-src 'self' blob:",
    );
  });
});
