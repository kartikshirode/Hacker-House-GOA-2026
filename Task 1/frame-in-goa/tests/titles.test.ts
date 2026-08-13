import { describe, expect, it } from "vitest";
import { generateTitle, TITLE_POOLS } from "@/lib/titles";

describe("generateTitle", () => {
  it("builds from both pools", () => {
    const t = generateTitle(() => 0);
    expect(t).toBe(`${TITLE_POOLS.GOA[0]} ${TITLE_POOLS.BUILDER[0]}`);
  });

  it("never returns the excluded title", () => {
    for (let i = 0; i < 100; i++) {
      const prev = generateTitle();
      expect(generateTitle(Math.random, prev)).not.toBe(prev);
    }
  });
});
