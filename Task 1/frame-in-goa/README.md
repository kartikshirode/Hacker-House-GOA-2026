# Frame in Goa

My submission for the HH Goa 2026 shortlisting task. Upload a photo, get a branded builder pass, download it or share it on X with #FrameInGoa.

Live: https://frame-in-goa-ruby.vercel.app

## What it does

Four formats from one canvas renderer: Builder ID card (1080x1350), team frame for 1-3 people (1600x900), circular PFP frame (1080x1080) and a poster ID (1080x1620) with a scannable QR back to the app. The card and poster also come in three styles: the riso print-shop look, a daytime Goa beach scene and a sunset scene with bunting and palm silhouettes. Everything renders in the browser; photos never touch a server unless you create a share link.

The parts that took actual thought:

- Real HEIC support. Magic-byte sniffing plus a lazy-loaded libheif wasm converter, prefetched on idle. Works in Chrome and Firefox, not just Safari. About 900 ms for a 1440px HEIC.
- Face-aware auto-crop. MediaPipe BlazeFace centers your face in the window on upload, eyes slightly above center. Drag and pinch still win if you disagree with it.
- A share flow where the preview actually works. Share to X uploads the finished PNG plus a 1200x630 crop to Vercel Blob and opens a pre-filled post linking a per-pass page whose og:image is your actual card. Verified with a Twitterbot user agent against production.
- Seat numbers. Each pass gets a number, drawn on the card and echoed in the caption by one shared formatter.

## Stack

Next.js 16 App Router, TypeScript, Tailwind v4, Canvas 2D, Vercel Blob, optional Upstash Redis for the seat counter (falls back to a stable hash without it). Fonts are Imbue, Victor Mono and Noto Sans Devanagari, loaded through the FontFace API before any canvas text draws.

## Run it

```
npm install
npm run dev      # app on :3000
npm test         # vitest units
```

/fixtures renders every format against edge cases (long names, Devanagari, extreme aspect ratios) through the real renderer.

Share links need a linked Vercel Blob store (BLOB_READ_WRITE_TOKEN). The seat counter uses UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN when present.
