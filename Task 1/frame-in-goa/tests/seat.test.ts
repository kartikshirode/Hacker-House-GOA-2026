import { describe, expect, it } from "vitest";
import { fallbackSeat, formatSeat } from "@/lib/seat";

describe("formatSeat", () => {
  it("pads and shows capacity at or below 247", () => {
    expect(formatSeat(42)).toBe("#042 / 247");
    expect(formatSeat(1)).toBe("#001 / 247");
    expect(formatSeat(247)).toBe("#247 / 247");
  });

  it("drops the capacity suffix past 247", () => {
    expect(formatSeat(248)).toBe("#248");
    expect(formatSeat(1024)).toBe("#1024");
  });
});

describe("fallbackSeat", () => {
  it("is stable for the same id", () => {
    expect(fallbackSeat("abc123XYZ_-abc123XYZ_")).toBe(fallbackSeat("abc123XYZ_-abc123XYZ_"));
  });

  it("stays in 1..247", () => {
    for (let i = 0; i < 200; i++) {
      const seat = fallbackSeat(`pass-${i}`);
      expect(seat).toBeGreaterThanOrEqual(1);
      expect(seat).toBeLessThanOrEqual(247);
    }
  });
});
