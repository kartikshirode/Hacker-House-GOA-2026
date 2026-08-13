import { describe, expect, it } from "vitest";
import { sniffHeic } from "@/lib/image-pipeline";

function header(brand: string): Uint8Array {
  const bytes = new Uint8Array(16);
  const put = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) bytes[off + i] = s.charCodeAt(i);
  };
  put(4, "ftyp");
  put(8, brand);
  return bytes;
}

describe("sniffHeic", () => {
  it.each(["heic", "heix", "hevc", "mif1", "msf1", "HEIC"])("detects brand %s", (b) => {
    expect(sniffHeic(header(b))).toBe(true);
  });

  it("rejects jpeg and png headers", () => {
    expect(sniffHeic(new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0, 0, 0, 0]))).toBe(false);
    expect(sniffHeic(new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]))).toBe(false);
  });

  it("rejects mp4-style brands and short buffers", () => {
    expect(sniffHeic(header("isom"))).toBe(false);
    expect(sniffHeic(new Uint8Array(4))).toBe(false);
  });
});
