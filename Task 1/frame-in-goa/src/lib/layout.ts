// Single source of geometry for every format. Both the live preview and the
// export path render through these numbers, so they can never drift apart.

export type FormatId = "card" | "team" | "pfp" | "poster";

export interface PhotoWindow {
  x: number;
  y: number;
  w: number;
  h: number;
  /** corner radius; >= w/2 means a circle */
  r: number;
}

export interface FormatSpec {
  id: FormatId;
  width: number;
  height: number;
  /** photo windows for a given photo count (team varies, others fixed) */
  windows: (photoCount: number) => PhotoWindow[];
  maxPhotos: number;
}

export const FORMATS: Record<FormatId, FormatSpec> = {
  card: {
    id: "card",
    width: 1080,
    height: 1350,
    maxPhotos: 1,
    windows: () => [{ x: 220, y: 385, w: 640, h: 640, r: 36 }],
  },
  team: {
    id: "team",
    width: 1600,
    height: 900,
    maxPhotos: 3,
    windows: (n) => {
      const count = Math.max(1, Math.min(3, n));
      const size = count === 1 ? 480 : count === 2 ? 420 : 360;
      const gap = count === 3 ? 60 : 120;
      const total = count * size + (count - 1) * gap;
      const x0 = (1600 - total) / 2;
      const y = 250;
      return Array.from({ length: count }, (_, i) => ({
        x: x0 + i * (size + gap),
        y,
        w: size,
        h: size,
        r: 32,
      }));
    },
  },
  pfp: {
    id: "pfp",
    width: 1080,
    height: 1080,
    maxPhotos: 1,
    windows: () => [{ x: 140, y: 140, w: 800, h: 800, r: 400 }],
  },
  poster: {
    id: "poster",
    width: 1080,
    height: 1620,
    maxPhotos: 1,
    windows: () => [{ x: 290, y: 405, w: 500, h: 500, r: 250 }],
  },
};

export const TEXT_LIMITS = {
  name: 28,
  role: 32,
  teamName: 24,
} as const;

// Visual styles. "print" is the riso print-shop look; the scene styles put
// the AI-illustrated Goa art behind the photo. Every format has all three.
export type StyleId = "print" | "day" | "sunset";

export const STYLES: { id: StyleId; label: string }[] = [
  { id: "print", label: "PRINT SHOP" },
  { id: "day", label: "GOA DAY" },
  { id: "sunset", label: "GOA SUNSET" },
];

export function styleSupports(_style: StyleId, _format: FormatId): boolean {
  return true;
}
