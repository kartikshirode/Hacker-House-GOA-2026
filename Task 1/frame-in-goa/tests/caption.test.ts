import { describe, expect, it } from "vitest";
import { buildCaption, buildIntentUrl } from "@/lib/caption";

describe("buildCaption", () => {
  it("always carries the required hashtag", () => {
    expect(buildCaption(null)).toContain("#FrameInGoa");
    expect(buildCaption(42, "https://example.com/pass/x")).toContain("#FrameInGoa");
  });

  it("uses the shared seat formatter", () => {
    expect(buildCaption(42)).toContain("Seat #042 / 247.");
    expect(buildCaption(300)).toContain("Seat #300.");
  });

  it("includes the pass url when given", () => {
    expect(buildCaption(1, "https://e.com/pass/abc")).toContain("https://e.com/pass/abc");
  });
});

describe("buildIntentUrl", () => {
  it("targets the documented x.com intent and encodes the caption", () => {
    const url = buildIntentUrl(buildCaption(7));
    expect(url.startsWith("https://x.com/intent/tweet?text=")).toBe(true);
    expect(decodeURIComponent(url)).toContain("#FrameInGoa");
  });
});
