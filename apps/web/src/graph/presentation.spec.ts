import { describe, expect, it } from "vitest";

import { graphNodeSize, usesLargeNodes } from "./presentation";

describe("graph presentation", () => {
  it("uses larger visible nodes below the configured threshold", () => {
    expect(usesLargeNodes(3, 50)).toBe(true);
    expect(graphNodeSize(0, 3, 50)).toBe(12);
    expect(graphNodeSize(4, 3, 50)).toBeGreaterThan(12);
  });

  it("keeps the existing scale at the threshold and when disabled", () => {
    expect(usesLargeNodes(50, 50)).toBe(false);
    expect(graphNodeSize(0, 50, 50)).toBe(3);
    expect(graphNodeSize(0, 3, 0)).toBe(3);
  });
});
