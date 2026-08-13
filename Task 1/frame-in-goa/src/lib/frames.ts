// AI-illustrated scene backgrounds, generated offline with Gemini and shipped
// as static PNGs. Warmed once; the renderer stays synchronous and falls back
// to the hand-painted scene when a background is missing.

const cache = new Map<string, ImageBitmap>();

export function getFrameBg(format: string, style: string): ImageBitmap | null {
  return cache.get(`${format}-${style}`) ?? null;
}

export async function warmFrames(): Promise<void> {
  const jobs: Promise<void>[] = [];
  for (const format of ["card", "poster", "team", "pfp"]) {
    for (const style of ["day", "sunset"]) {
      const key = `${format}-${style}`;
      if (cache.has(key)) continue;
      jobs.push(
        (async () => {
          try {
            const res = await fetch(`/frames/${key}.png`);
            if (!res.ok) return;
            cache.set(key, await createImageBitmap(await res.blob()));
          } catch {
            // painted fallback covers it
          }
        })(),
      );
    }
  }
  await Promise.all(jobs);
}
