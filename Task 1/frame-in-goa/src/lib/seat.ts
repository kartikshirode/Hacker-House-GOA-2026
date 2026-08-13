import { EVENT } from "./brand";

// One formatter shared by the card renderer and the caption builder, so the
// card and the tweet can never disagree about the seat label.
export function formatSeat(n: number): string {
  const num = `#${String(n).padStart(3, "0")}`;
  return n <= EVENT.capacity ? `${num} / ${EVENT.capacity}` : num;
}

// Deterministic fallback seat when the counter API is unreachable. Stable per
// pass id so refreshes agree with themselves.
export function fallbackSeat(passId: string): number {
  let h = 2166136261;
  for (let i = 0; i < passId.length; i++) {
    h ^= passId.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (Math.abs(h) % EVENT.capacity) + 1;
}
