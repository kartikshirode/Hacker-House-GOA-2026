import { EVENT } from "./brand";
import { formatSeat } from "./seat";

export function buildCaption(seat: number | null, passUrl?: string): string {
  const seatPart = seat !== null ? ` Seat ${formatSeat(seat)}.` : "";
  const urlPart = passUrl ? ` Get yours: ${passUrl}` : "";
  return `Boarding for ${EVENT.name}.${seatPart}${urlPart} ${EVENT.hashtag}`;
}

export function buildIntentUrl(caption: string): string {
  return `https://x.com/intent/tweet?text=${encodeURIComponent(caption)}`;
}
