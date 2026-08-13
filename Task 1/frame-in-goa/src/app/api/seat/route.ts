import { Redis } from "@upstash/redis";
import { NextResponse } from "next/server";
import { fallbackSeat } from "@/lib/seat";

const PASS_ID = /^[A-Za-z0-9_-]{21}$/;

// One atomic script: check the mapping, increment only for a new id, store,
// return. Concurrent retries for the same id can never burn two seats.
const SEAT_SCRIPT = `
local existing = redis.call('GET', KEYS[1])
if existing then return tonumber(existing) end
local seat = redis.call('INCR', KEYS[2])
redis.call('SET', KEYS[1], seat)
return seat
`;

export async function POST(request: Request): Promise<NextResponse> {
  const { passId } = (await request.json().catch(() => ({}))) as { passId?: string };
  if (!passId || !PASS_ID.test(passId)) {
    return NextResponse.json({ error: "bad passId" }, { status: 400 });
  }
  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    // Not provisioned: same stable-hash fallback the client would compute,
    // returned as a 200 so no console ever shows a failed request.
    return NextResponse.json({ seat: fallbackSeat(passId), fallback: true });
  }
  try {
    const redis = Redis.fromEnv();
    const seat = await redis.eval(SEAT_SCRIPT, [`seat:${passId}`, "seat-counter"], []);
    return NextResponse.json({ seat: Number(seat) });
  } catch {
    return NextResponse.json({ seat: fallbackSeat(passId), fallback: true });
  }
}
