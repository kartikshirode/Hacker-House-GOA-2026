// Brand tokens pulled from hhgoa.com production CSS. Do not eyeball-adjust.
export const BRAND = {
  green: "#0B6839",
  greenDeep: "#07472A",
  yellow: "#FEE101",
  cream: "#FFFBE8",
  pink: "#FF0080",
  red: "#E40014",
  ink: "#0E0E0E",
} as const;

export const EVENT = {
  name: "Hacker House Goa 2026",
  dates: "28-31 OCT 2026",
  place: "GOA, INDIA",
  tagline: "LESS NOISE. MORE SIGNAL.",
  studio: "2:47PM STUDIO",
  hashtag: "#FrameInGoa",
  capacity: 247,
} as const;

export const FONTS = {
  display: "Imbue",
  mono: "Victor Mono",
  devanagari: "Noto Sans Devanagari",
} as const;

// Canvas font stacks. System fallbacks catch scripts the webfonts don't cover.
export const STACK = {
  display: `"Imbue", Georgia, serif`,
  mono: `"Victor Mono", ui-monospace, monospace`,
  devanagari: `"Noto Sans Devanagari", sans-serif`,
} as const;
